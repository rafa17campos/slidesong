"""Worker for heavy jobs on a machine with an NVIDIA GPU (CUDA + NVENC). Started by hand.

    uvicorn slidesong.worker:app --host 0.0.0.0 --port 8097

Shared by several apps (Slidesong, a photo library service…), each with its own token; one job at a time.
Env: WORKER_TOKEN (Slidesong's), WORKER_TOKENS ("name:token,…", other clients), IMMICH_URL + IMMICH_API_KEY
(read-only: the worker fetches photos and faces itself), else SLIDESONG_IMAGES_URL (photos through Slidesong),
SLIDESONG_VCODEC=h264_nvenc, WHISPER_DEVICE=cuda.
One job at a time. Results are deleted once downloaded (or after 6 h).
/score and /tag take video_mode: "fast" (default) analyses a video on Immich's preview only, "deep" on frames sampled
from the video too (videoframes.py; docs/analysers.md, "Videos"). WORKER_FRAME_CACHE_MB caps the frames kept between
jobs (2048).
"""
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

# Windows: CUDA DLLs installed with pip (nvidia-cublas-cu12; cuDNN ships with ctranslate2)
if sys.platform == "win32":
    import site
    for sp in site.getsitepackages():
        for bin_dir in Path(sp, "nvidia").glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import analyze, render, videoframes
from . import config

TOKEN = os.environ.get("WORKER_TOKEN", "")  # Slidesong's (it also lets the worker fetch photos through Slidesong)


def _tokens() -> dict[str, str]:
    """Clients and their tokens: WORKER_TOKEN is Slidesong's; WORKER_TOKENS="name:token,name:token" adds others
    (e.g. a photo library service), each revocable on its own."""
    out = {"slidesong": TOKEN} if TOKEN else {}
    for part in os.environ.get("WORKER_TOKENS", "").split(","):
        name, _, tok = part.partition(":")
        if name.strip() and tok.strip():
            out[name.strip()] = tok.strip()
    return out


TOKENS = _tokens()
# With its own read-only Immich key the worker fetches photos and faces itself, inside the home network: any client
# just sends asset ids. Without it, photos come through Slidesong (SLIDESONG_IMAGES_URL), for Slidesong only.
IMMICH = os.environ.get("IMMICH_URL", "").rstrip("/")
IMMICH_KEY = os.environ.get("IMMICH_API_KEY", "")
WORK = Path(os.environ.get("WORKER_DIR", tempfile.gettempdir())) / "slidesong-worker"
WORK.mkdir(parents=True, exist_ok=True)
FRAMES = WORK / "frames"  # video frames (deep video mode), shared by jobs: a video's tag and score jobs extract once
FRAME_CACHE_BYTES = int(float(os.environ.get("WORKER_FRAME_CACHE_MB") or 2048) * 2 ** 20)
VIDEO_MODES = ("fast", "deep")

app = FastAPI(title="Slidesong worker")
_jobs: dict[str, dict] = {}
_busy = threading.Lock()


def auth(authorization: str = Header("")) -> str:
    """The calling client's name."""
    for name, tok in TOKENS.items():
        if hmac.compare_digest(authorization, f"Bearer {tok}"):
            return name
    raise HTTPException(401)


def _can_fetch(client: str):
    if not (IMMICH and IMMICH_KEY) and not (client == "slidesong" and config.env("IMAGES_URL")):
        raise HTTPException(503, "this worker cannot fetch photos for this client (no IMMICH_URL / IMMICH_API_KEY)")


def _immich_faces(items):
    """Face boxes (relative), person names and person ids from Immich for the items that came without them."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    todo = [it for it in items if "faces" not in it]
    if not todo or not (IMMICH and IMMICH_KEY):
        return
    client = httpx.Client(base_url=IMMICH + "/api", headers={"x-api-key": IMMICH_KEY}, timeout=60)

    def one(it):
        try:
            fl = client.get("/faces", params={"id": it["id"]}).json()
        except Exception:
            fl = []
        it["faces"] = [{"box": [f["boundingBoxX1"] / f["imageWidth"], f["boundingBoxY1"] / f["imageHeight"],
                                f["boundingBoxX2"] / f["imageWidth"], f["boundingBoxY2"] / f["imageHeight"]],
                        "name": (f.get("person") or {}).get("name") or "",
                        "person_id": (f.get("person") or {}).get("id")}
                       for f in fl if isinstance(f, dict) and f.get("imageWidth") and f.get("imageHeight")]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, todo))


def _cleanup():
    for jid, j in list(_jobs.items()):
        if time.time() - j["created"] > 6 * 3600:
            shutil.rmtree(WORK / jid, ignore_errors=True)
            _jobs.pop(jid, None)
    videoframes.clean_cache(FRAMES, max_bytes=FRAME_CACHE_BYTES)


class Cancelled(Exception):
    pass


def _start(kind, fn):
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "the worker is busy with another job")
    _cleanup()
    jid = secrets.token_hex(8)
    d = WORK / jid
    d.mkdir()
    _jobs[jid] = {"kind": kind, "state": "running", "progress": 0.0, "error": None, "created": time.time()}

    def check():
        if _jobs[jid].get("cancel"):
            raise Cancelled()

    def prog(x):
        check()
        _jobs[jid]["progress"] = round(float(x), 3)
    prog.check = check

    def target():
        try:
            fn(d, prog)
            _jobs[jid].update(state="done", progress=1.0)
        except Cancelled:
            _jobs[jid].update(state="cancelled")
        except Exception as e:
            traceback.print_exc()
            _jobs[jid].update(state="error", error=str(e))
        finally:
            _busy.release()

    return jid, d, target


@app.get("/health")
def health():
    import shutil as sh
    sc, tg = analyser(SCORER_DIR), analyser(TAGGER_DIR)
    return {"ok": True, "busy": _busy.locked(), "scorer": bool(_scorer_python()),
            "tagger": bool(_venv_python(TAGGER_DIR)),
            "vcodec": config.env("VCODEC", "libx264"),
            "whisper": os.environ.get("WHISPER_DEVICE", "cpu"), "ffmpeg": bool(sh.which("ffmpeg")),
            # video_mode=deep can be honoured (with analysers whose manifest says local_images)
            "video_modes": list(VIDEO_MODES),
            "video_deep": bool(IMMICH and IMMICH_KEY and sh.which("ffmpeg") and sh.which("ffprobe")),
            # which analysers these are (docs/analysers.md): clients keep each record with its scorer's identity
            "scorer_version": sc.get("version"), "scorer_name": sc.get("name"), "scorer_info": sc,
            "tagger_model": tg.get("name"), "tagger_info": tg}


def analyser(folder) -> dict:
    """An analyser's manifest (analyser.json: kind, name, version, script, and for a scorer its face_focus
    thresholds). Older folders without one: the scorer's VERSION read from score.py."""
    try:
        m = json.loads((Path(folder) / "analyser.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        pass
    try:
        v = re.search(r"^VERSION = (\d+)", (Path(folder) / "score.py").read_text(encoding="utf-8"), re.M)
        # the reference scorer before it had a manifest
        return {"kind": "scorer", "name": "aesthetic-v2.5", "version": int(v.group(1)), "script": "score.py",
                "face_focus": {"blurry": 1.6, "soft": 1.8}} if v else {}
    except OSError:
        return {}


@app.post("/render", dependencies=[Depends(auth)])
async def post_render(project: str = Form(...), quality: str = Form("preview"), song: UploadFile = File(...)):
    p = json.loads(project)
    size = render.SIZES.get(quality, render.SIZES["preview"])
    data = await song.read()
    ext = Path(song.filename or "song.mp3").suffix or ".mp3"

    def fn(d, prog):
        (d / f"song{ext}").write_bytes(data)
        render.render(p, p["assets"], d / f"song{ext}", d / "out.mp4", size, prog, use_original=quality.startswith("final"),
                      fps=render.FINAL_FPS if quality.startswith("final") else render.FPS)

    jid, d, target = _start("render", fn)
    threading.Thread(target=target, daemon=True).start()
    return {"id": jid}


@app.post("/clips", dependencies=[Depends(auth)])
async def post_clips(project: str = Form(...)):
    """One video file per shot (for editing in another app), returned as a zip with clips.json."""
    p = json.loads(project)

    def fn(d, prog):
        import zipfile
        info = render.render_clips(p, p["assets"], d / "clips", (1920, 1080), prog, use_original=True)
        with zipfile.ZipFile(d / "clips.zip", "w", zipfile.ZIP_STORED) as z:
            z.writestr("clips.json", json.dumps(info))
            for c in info:
                z.write(d / "clips" / c["file"], c["file"])

    jid, d, target = _start("clips", fn)
    threading.Thread(target=target, daemon=True).start()
    return {"id": jid}


@app.post("/transcribe", dependencies=[Depends(auth)])
async def post_transcribe(lines: str = Form(...), song: UploadFile = File(...), language: str = Form("")):
    lyrics = json.loads(lines)
    data = await song.read()
    ext = Path(song.filename or "song.mp3").suffix or ".mp3"

    def fn(d, prog):
        (d / f"song{ext}").write_bytes(data)
        words = analyze.transcribe(d / f"song{ext}", lyrics, prog, language or None)
        (d / "words.json").write_text(json.dumps(words, ensure_ascii=False))

    jid, d, target = _start("transcribe", fn)
    threading.Thread(target=target, daemon=True).start()
    return {"id": jid}


SCORER_DIR = Path(os.environ.get("SCORER_DIR", Path(__file__).resolve().parent.parent / "scorer"))


TAGGER_DIR = Path(os.environ.get("TAGGER_DIR", Path(__file__).resolve().parent.parent / "tagger"))


def _venv_python(folder):
    for cand in (folder / ".venv" / "Scripts" / "python.exe", folder / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return None


def _scorer_python():
    return _venv_python(SCORER_DIR)


def _run_script(folder, script, data, d, prog, result_name, fold=None):
    """Run `script` from `folder`'s venv on `data` (list of items), reporting progress by output lines. `fold` turns
    the output lines into the result's records (the frames of a video into one record)."""
    import subprocess
    py = _venv_python(folder)
    inp, out = d / "in.json", d / "out.jsonl"
    source = ({"immich_url": IMMICH, "immich_key": IMMICH_KEY} if IMMICH and IMMICH_KEY
              else {"images_url": config.env("IMAGES_URL", ""), "token": TOKEN})
    inp.write_text(json.dumps({**source, "items": data}, ensure_ascii=False), encoding="utf-8")
    err = d / "stderr.log"  # a file, not a pipe: MediaPipe logs a lot and a full pipe would stall the script
    with open(err, "wb") as ef:
        proc = subprocess.Popen([py, "-X", "utf8", str(folder / script), str(inp), str(out)], cwd=str(folder),
                                env={**os.environ, "PYTHONUTF8": "1"}, stdout=subprocess.DEVNULL, stderr=ef)
    while proc.poll() is None:
        time.sleep(1.0)
        try:
            prog.check()
            if out.exists():
                prog(sum(1 for _ in open(out, encoding="utf-8")) / max(1, len(data)))
        except Cancelled:
            proc.kill()  # the GPU is freed right away
            raise
    log = err.read_text(encoding="utf-8", errors="replace")
    for line in log.splitlines():
        if line.startswith("warning: "):
            print(f"{script}: {line}", flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{script} failed: " + log[-400:])
    recs = [json.loads(l) for l in open(out, encoding="utf-8") if l.strip()]
    (d / result_name).write_text(json.dumps(fold(recs) if fold else recs), encoding="utf-8")


def _video_mode(v):
    v = (v or "").strip() or "fast"
    if v not in VIDEO_MODES:
        raise HTTPException(400, "video_mode is fast or deep")
    return v


def _part(prog, a, b):
    """`prog` for one part of a job, from a to b of the whole."""
    def p(x):
        prog(a + (b - a) * x)
    p.check = prog.check
    return p


def _deep_ready(manifest):
    """Whether videos can be analysed deep with this analyser; why not in the worker's log."""
    why = None
    if not (IMMICH and IMMICH_KEY):
        why = "the worker has no Immich key of its own (IMMICH_URL + IMMICH_API_KEY)"
    elif not manifest.get("local_images"):
        why = f"the analyser {manifest.get('name') or '?'} does not read local images (local_images in analyser.json)"
    elif not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        why = "ffmpeg or ffprobe is not on the PATH"
    if why:
        print(f"video_mode=deep: {why}; videos are analysed on their preview (fast)", flush=True)
    return not why


def _immich_assets(ids):
    """{asset id: Immich's asset (type, duration, checksum…) or None when it cannot be had}; the failures (HTTP
    status or error) in the worker's log, once per job."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    client = httpx.Client(base_url=IMMICH + "/api", headers={"x-api-key": IMMICH_KEY}, timeout=60)

    failed = {}

    def one(i):
        try:
            r = client.get(f"/assets/{i}")
            if r.status_code == 200:
                return i, r.json()
            why = f"HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            why = type(e).__name__
        failed[why] = failed.get(why, 0) + 1
        return i, None
    with ThreadPoolExecutor(8) as pool:
        out = dict(pool.map(one, ids))
    if failed:
        print(f"video_mode=deep: Immich did not describe {sum(failed.values())} of {len(ids)} assets "
              f"({', '.join(f'{k}: {n}' for k, n in failed.items())}); they are analysed as fast. The worker's "
              "Immich key needs asset.read.", flush=True)
    return out


def _video_frames(data, prog):
    """(asset ids of the videos analysed deep, {asset id: [(seconds, frame file)]}). Items that say they are
    photos ("type": "IMAGE", as Immich names it) are not looked up."""
    assets = _immich_assets([it["id"] for it in data if str(it.get("type", "")).upper() != "IMAGE"])
    videos = [(i, a) for i, a in assets.items() if isinstance(a, dict) and a.get("type") == "VIDEO"]
    ex = videoframes.Extractor(IMMICH, IMMICH_KEY, FRAMES, prog.check, lambda m: print(m, flush=True))
    frames = {}
    try:
        for k, (i, a) in enumerate(videos):
            times = videoframes.sample_times(videoframes.parse_duration(a.get("duration")))
            if times:  # else too short for a frame of its own: its preview only
                frames[i] = ex.frames(i, a.get("checksum") or "", times)
                if i in ex.unreadable:
                    print(f"warning: video {i}: ffmpeg could not read it, analysed on its preview only", flush=True)
            prog((k + 1) / len(videos))
    finally:
        videoframes.clean_cache(FRAMES, keep=ex.used, max_bytes=FRAME_CACHE_BYTES)
    return {i for i, _ in videos}, frames


def _analyse(folder, kind, default_script, data, d, prog, video_mode):
    """Run an analyser on `data`; with video_mode deep, each video is expanded into frames first and folded back
    into one record after."""
    m = analyser(folder)
    videos, frames, fold = set(), {}, None
    if video_mode == "deep" and _deep_ready(m):
        videos, frames = _video_frames(data, _part(prog, 0, 0.3))
        if videos:
            prog = _part(prog, 0.3, 1)
            fold = lambda recs: videoframes.fold(recs, videos, kind)  # noqa: E731
    _run_script(folder, m.get("script", default_script), videoframes.expand(data, frames), d, prog, "result.json",
                fold)


@app.post("/score")
async def post_score(items: str = Form(...), video_mode: str = Form(""), client: str = Depends(auth)):
    """Quality scores for a list of photos ({id, faces?}) with scorer/score.py in its own venv. Faces left out
    are looked up in Immich (when the worker has its own key). video_mode: fast (default) or deep."""
    py = _scorer_python()
    if not py:
        raise HTTPException(503, "scorer not installed on this worker")
    mode = _video_mode(video_mode)
    _can_fetch(client)
    data = json.loads(items)

    def fn(d, prog):
        _immich_faces(data)
        _analyse(SCORER_DIR, "score", "score.py", data, d, prog, mode)

    jid, d, target = _start("score", fn)
    threading.Thread(target=target, daemon=True).start()
    return {"id": jid}


@app.post("/tag")
async def post_tag(items: str = Form(...), video_mode: str = Form(""), client: str = Depends(auth)):
    """Object/scene tags (RAM++) for a list of photos ({id}) with tagger/tag.py in its own venv. video_mode: fast
    (default) or deep."""
    if not _venv_python(TAGGER_DIR):
        raise HTTPException(503, "tagger not installed on this worker")
    mode = _video_mode(video_mode)
    _can_fetch(client)
    data = json.loads(items)

    def fn(d, prog):
        _analyse(TAGGER_DIR, "tag", "tag.py", data, d, prog, mode)

    jid, d, target = _start("tag", fn)
    threading.Thread(target=target, daemon=True).start()
    return {"id": jid}


@app.get("/jobs/{jid}", dependencies=[Depends(auth)])
def job(jid: str):
    j = _jobs.get(jid)
    if not j:
        raise HTTPException(404)
    return {k: v for k, v in j.items() if k != "created"}


@app.get("/jobs/{jid}/result", dependencies=[Depends(auth)])
def result(jid: str):
    j = _jobs.get(jid)
    if not j or j["state"] != "done":
        raise HTTPException(404)
    f = WORK / jid / {"render": "out.mp4", "transcribe": "words.json", "score": "result.json",
                      "tag": "result.json", "clips": "clips.zip"}[j["kind"]]
    return FileResponse(f)


@app.post("/jobs/{jid}/cancel", dependencies=[Depends(auth)])
def cancel(jid: str):
    if jid not in _jobs:  # unknown (e.g. the worker restarted): the client queues the batch again
        raise HTTPException(404)
    if _jobs[jid]["state"] == "running":
        _jobs[jid]["cancel"] = True
    return {"ok": True}


@app.delete("/jobs/{jid}", dependencies=[Depends(auth)])
def delete(jid: str):
    if jid not in _jobs:
        raise HTTPException(404)
    if _jobs[jid]["state"] != "running":
        shutil.rmtree(WORK / jid, ignore_errors=True)
        _jobs.pop(jid, None)
    return {"ok": True}
