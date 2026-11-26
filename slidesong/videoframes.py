"""Videos analysed on frames of their own (the worker's `deep` video mode, docs/analysers.md, "Videos").

The worker expands a video into frame images (JPEG files), the analysers analyse images, and the per-frame lines are
folded back into one record per video. Frames are sampled every EVERY seconds from FIRST_AT on, spread wider on long
videos so there are never more than MAX_FRAMES; Immich's preview is always analysed too (its face boxes are relative
to it). Frames are read with ffmpeg seeking straight into Immich's playback stream (HTTP Range), so a long video is
not downloaded whole, and kept in a cache shared by jobs: the tagger's job and the scorer's job of the same videos
extract them once.
"""
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FIRST_AT = 1.0  # s: many videos open on black or a fade
EVERY = 5.0  # s between frames, up to MAX_FRAMES * EVERY seconds of video
MAX_FRAMES = 30
END_MARGIN = 0.2  # s: no frame this close to the end (seeking there often finds none)
FRAME_SIZE = 1440  # px, the longer side: about Immich's preview
RECV_BUFFER = 262144  # ffmpeg's TCP receive buffer: a big one lets Immich send megabytes ffmpeg never reads
AT_ONCE = 4  # ffmpeg processes per video at the same time
FRAME_TIMEOUT = 120  # s per frame
CACHE_HOURS = 6
CACHE_FORMAT = 1  # bump when the frames themselves change (size, tone mapping): older cache entries are redone
# The video itself: the first video stream that is not a cover picture. ffmpeg would otherwise pick the one with the
# most pixels, and a phone's motion-photo clip carries its 12 MP still as a second, one-frame video stream.
STREAM = "0:V:0"
HDR = ("smpte2084", "arib-std-b67")  # PQ and HLG: tone-mapped to SDR, as Immich does for its own preview
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
SCALE = (f"scale=w='if(gte(iw,ih),min({FRAME_SIZE},iw),-2)':h='if(gte(iw,ih),-2,min({FRAME_SIZE},ih))'")

# Tagger: a tag seen on one frame only is kept when it is one of these (the sensitive-photo warnings would rather
# have one too many) or when the preview has it (a deep record never has fewer tags than the fast one).
# The keys of slidesong.suggest.SENSITIVE (tests/test_videoframes.py checks they stay the same).
ANY_FRAME_TAGS = frozenset({"shirtless", "swimwear", "bikini", "swim", "sunbathe", "diaper", "bath", "belly"})
MIN_FRAMES = 2  # any other tag: seen on at least this many of the analysed images

# Scorer: these are the median over every analysed image (the preview included); the rest of the record (faces,
# version, any field another scorer adds) is the preview's.
MEDIAN_FIELDS = {"aesthetic": 3, "sharp": 3, "bright": 3, "clip_hi": 4, "clip_lo": 4}


def parse_duration(v):
    """A video's duration in seconds from Immich's asset: milliseconds (Immich 2+) or "H:MM:SS.ffffff" (older).
    None when it says nothing usable."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 0 else None
    try:
        h, m, s = str(v).split(":")
        d = int(h) * 3600 + int(m) * 60 + float(s)
        return d if d > 0 else None
    except ValueError:
        return None


def sample_times(duration):
    """Seconds into the video of the frames to analyse: from FIRST_AT every max(EVERY, duration / MAX_FRAMES).
    Empty for a video too short for one (it is analysed on its preview only)."""
    if not duration:
        return []
    step = max(EVERY, duration / MAX_FRAMES)
    out, t = [], FIRST_AT
    while t <= duration - END_MARGIN and len(out) < MAX_FRAMES:
        out.append(round(t, 2))
        t += step
    return out


def seconds(t):
    """A frame's time as text, to the hundredth and without trailing zeros: 6, 10.33, 12345.67."""
    return f"{t:.2f}".rstrip("0").rstrip(".")


def frame_id(asset, t):
    """The id a frame goes by through the analysers: "<asset id>@<seconds>"."""
    return f"{asset}@{seconds(t)}"


def split_id(fid):
    """(asset id, seconds) of a frame id; (id, None) for anything else (a photo, a video's preview)."""
    asset, at, t = str(fid).rpartition("@")
    if not at:
        return fid, None
    try:
        return asset, float(t)
    except ValueError:
        return fid, None


def expand(items, frames):
    """The analysers' items: every item as it is, each video followed by its frames ({id, image}).
    `frames`: {asset id: [(seconds, path)]}."""
    out = []
    for it in items:
        out.append(it)
        for t, path in frames.get(it["id"], ()):
            out.append({"id": frame_id(it["id"], t), "image": str(path)})
    return out


def _group(records):
    """{asset id: [(seconds or None for the preview, record)]} keeping the analysers' order."""
    out = {}
    for r in records:
        asset, t = split_id(r.get("id", ""))
        out.setdefault(asset, []).append((t, r))
    return out


def fold(records, videos, kind):
    """One record per item from the analysers' lines: photos as they are, each video in `videos` (asset ids
    analysed deep) folded from its preview's and frames' lines. In the analysers' order; an item with no line
    at all stays out (as an unreadable photo does)."""
    out = []
    for asset, lines in _group(records).items():
        if asset in videos:
            out.append((fold_tags if kind == "tag" else fold_scores)(asset, lines))
        else:
            out.extend(r for t, r in lines if t is None)
    return out


def _video_fields(lines):
    return {"video_mode": "deep", "video_frames": len(lines)}


def fold_tags(asset, lines):
    """The tags of a video: the preview's, the sensitive ones seen on any frame, and the rest seen on at least
    MIN_FRAMES of the analysed images. In the order they first appear."""
    preview = next((r for t, r in lines if t is None), {})
    seen, order = {}, []
    for _, r in lines:
        for tag in dict.fromkeys(r.get("tags") or []):
            if tag not in seen:
                order.append(tag)
            seen[tag] = seen.get(tag, 0) + 1
    keep = set(preview.get("tags") or [])
    tags = [t for t in order if t in keep or t in ANY_FRAME_TAGS or seen[t] >= MIN_FRAMES]
    return {**{k: v for k, v in preview.items() if k != "tags"}, "id": asset, "tags": tags, **_video_fields(lines)}


def fold_scores(asset, lines):
    """The score of a video: MEDIAN_FIELDS as the median over every analysed image, the rest (faces, the scorer's
    version) from the preview, plus aesthetic_best and best_at (seconds into the video of the best-looking image,
    0 when it is the preview)."""
    preview = next((r for t, r in lines if t is None), None)
    rec = dict(preview or lines[0][1])
    rec["id"] = asset
    if preview is None:
        rec.pop("faces", None)  # faces are measured on the preview only
    for k, nd in MEDIAN_FIELDS.items():
        vals = [r[k] for _, r in lines if isinstance(r.get(k), (int, float))]
        if vals:
            rec[k] = round(float(statistics.median(vals)), nd)
    scored = [(t, r["aesthetic"]) for t, r in lines if isinstance(r.get("aesthetic"), (int, float))]
    if scored:
        t, a = max(scored, key=lambda x: x[1])
        rec["aesthetic_best"], rec["best_at"] = round(float(a), 3), t or 0
    return {**rec, **_video_fields(lines)}


class Extractor:
    """Frames of Immich videos, through ffmpeg, cached in `cache` (one folder per video and version of it)."""

    def __init__(self, immich, key, cache, check=lambda: None, log=print):
        self.immich, self.key, self.cache = immich.rstrip("/"), key, Path(cache)
        self.check, self.log = check, log
        self._zscale = None
        self.used = set()  # cache folders of this job's videos
        self.unreadable = set()  # videos ffmpeg failed on at every time asked (not merely found no frame at)

    def _input(self, url):
        return ["-headers", f"x-api-key: {self.key}\r\n", "-recv_buffer_size", str(RECV_BUFFER), "-i", url]

    def _run(self, cmd, timeout):
        """Run ffmpeg/ffprobe, killed when the job is cancelled or it takes too long. (returncode, stdout); -1 when
        it could not even start."""
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return -1, ""
        with p:
            end = time.monotonic() + timeout
            while True:
                try:
                    out, _ = p.communicate(timeout=0.25)
                    return p.returncode, out.decode("utf-8", "replace")
                except subprocess.TimeoutExpired:
                    pass
                try:
                    self.check()
                except BaseException:
                    p.kill()
                    p.wait()
                    raise
                if time.monotonic() > end:
                    p.kill()
                    p.wait()
                    return -1, ""

    def has_zscale(self):
        if self._zscale is None:
            try:
                out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                                     timeout=30).stdout
                self._zscale = " zscale " in out
            except (OSError, subprocess.SubprocessError):
                self._zscale = False
        return self._zscale

    def _filters(self, url, asset):
        rc, out = self._run(["ffprobe", "-v", "error", *self._input(url), "-select_streams", "V:0",
                             "-show_entries", "stream=color_transfer", "-of", "csv=p=0"], FRAME_TIMEOUT)
        if out.strip() in HDR:
            if self.has_zscale():
                return TONEMAP + "," + SCALE
            self.log(f"warning: video {asset} is HDR and this ffmpeg has no zscale filter: its frames are not "
                     "tone-mapped (they look flat and grey, and score lower than they should)")
        return SCALE

    def frames(self, asset, checksum, times):
        """[(seconds, path)] of the frames at `times` that could be read; reused from the cache when this version
        of the video (its checksum) was already extracted at these times. Only a complete extraction is cached:
        frames missing because Immich or the network failed for a moment are tried again by the next job."""
        tag = hashlib.sha1(f"{checksum}|{CACHE_FORMAT}|{times}".encode()).hexdigest()[:12]
        d = self.cache / f"{asset}-{tag}"
        meta = d / "frames.json"
        self.used.add(d.name)
        try:
            got = json.loads(meta.read_text(encoding="utf-8"))
            files = [(float(t), d / f) for t, f in got]
            if all(p.exists() for _, p in files):
                os.utime(d)  # recently used: the cache keeps it longer
                return files
        except (OSError, ValueError, TypeError):
            pass
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        url = f"{self.immich}/api/assets/{asset}/video/playback"
        vf = self._filters(url, asset)

        def one(t):
            """(t, file name) of the frame; None when the video has no frame there (ffmpeg succeeded but wrote
            nothing: the stream ends before the container says); False when ffmpeg failed or timed out."""
            f = d / f"{seconds(t)}.jpg"
            rc, _ = self._run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", seconds(t), *self._input(url),
                               "-map", STREAM, "-frames:v", "1", "-vf", vf, "-q:v", "3", str(f)], FRAME_TIMEOUT)
            if rc != 0:
                return False
            return (t, f.name) if f.exists() and f.stat().st_size > 0 else None

        with ThreadPoolExecutor(AT_ONCE) as pool:
            res = list(pool.map(one, times))
        got = [x for x in res if x]
        if False not in res:  # nothing failed: the same frames next time (Immich down for a moment: try again)
            meta.write_text(json.dumps(got), encoding="utf-8")
        elif not got:
            self.unreadable.add(asset)
        return [(t, d / f) for t, f in got]


def clean_cache(cache, keep=(), max_bytes=None, hours=CACHE_HOURS):
    """Drop cached videos unused for `hours`, then the least recently used ones while the cache holds more than
    `max_bytes`; never those in `keep` (folders a running job still needs)."""
    cache = Path(cache)
    if not cache.is_dir():
        return
    keep = {Path(k).name for k in keep}
    dirs = []
    for d in cache.iterdir():
        if not d.is_dir() or d.name in keep:
            continue
        try:
            age = time.time() - d.stat().st_mtime
        except OSError:
            continue
        if age > hours * 3600:
            shutil.rmtree(d, ignore_errors=True)
        else:
            dirs.append((d.stat().st_mtime, d, sum(f.stat().st_size for f in d.iterdir() if f.is_file())))
    if max_bytes is None:
        return
    total = sum(s for _, _, s in dirs) + sum(f.stat().st_size for k in keep if (cache / k).is_dir()
                                             for f in (cache / k).iterdir() if f.is_file())
    for _, d, size in sorted(dirs, key=lambda x: x[0]):
        if total <= max_bytes:
            break
        shutil.rmtree(d, ignore_errors=True)
        total -= size
