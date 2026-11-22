"""Song analysis: duration, beats and lyrics aligned to the audio (faster-whisper)."""
import difflib
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

import numpy as np
from . import config
from . import lexicon

MODELS_DIR = config.DATA / "models"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")

PACES = {"slow": 5.5, "normal": 4.0, "fast": 2.0}  # target seconds per shot (bent by the song section)


def duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def beats(path):
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    tempo, bt = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    return tempo, [round(float(b), 3) for b in bt]


def clean_lyrics(text: str):
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"[\[\(].*[\]\)]", s):  # [Verse], (Chorus), empty lines
            continue
        s = re.sub(r"\[[^\]]*\]", "", s).strip()
        if s:
            lines.append(s)
    return lines


SECTION_KINDS = lexicon.section_kinds()  # (kind, words that identify it in a Suno-style tag), checked in order
MOOD_HIGH = ("energetic", "upbeat", "powerful", "explosive", "driving", "anthem", "big", "loud", "rock", "dance")
MOOD_LOW = ("intimate", "soft", "gentle", "calm", "quiet", "tender", "ballad", "fading", "slow", "piano", "whisper")


def parse_section(tag: str):
    """'[Bridge – Intimate vocals, piano…, gradual build]' -> {kind, label, mood, build}."""
    t = tag.strip("[]() ").lower()
    head = re.split(r"\s[–—-]\s|:", t, maxsplit=1)[0]
    kind = "verse"
    for k, words in SECTION_KINDS:
        if any(w in head for w in words):
            kind = k
            break
    if "final chorus" in head or "last chorus" in head:
        kind = "chorus"
    mood = "high" if any(w in t for w in MOOD_HIGH) else "low" if any(w in t for w in MOOD_LOW) else "mid"
    return {"kind": kind, "label": tag.strip("[]() "), "mood": mood, "build": "build" in t}


def lyric_sections(text: str):
    """Section of each line returned by clean_lyrics (same order), from Suno tags like [Chorus – …]."""
    out, cur = [], {"kind": "verse", "label": "", "mood": "mid", "build": False}
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.fullmatch(r"[\[\(].*[\]\)]", s):
            cur = parse_section(s)
            continue
        if re.sub(r"\[[^\]]*\]", "", s).strip():
            out.append(dict(cur))
    return out


def audio_features(path, beat_times):
    """Per-beat onset strength and loudness (0..1 percentiles) and the downbeat phase (bar of 4)."""
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    hop = 512
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    times = librosa.frames_to_time(np.arange(len(onset)), sr=sr, hop_length=hop)
    bt = np.array(beat_times) if beat_times else np.arange(0, times[-1], 0.5)
    idx = np.clip(np.searchsorted(times, bt), 0, len(onset) - 1)
    win = 2  # ±2 frames (~±46 ms)
    strength = np.array([onset[max(0, i - win): i + win + 1].max() for i in idx])
    loud = np.array([rms[max(0, i - 10): i + 11].mean() for i in idx])
    pct = lambda x: (np.argsort(np.argsort(x)) / max(1, len(x) - 1)).round(3).tolist()
    phase = int(np.argmax([strength[k::4].sum() for k in range(4)])) if len(strength) >= 8 else 0
    # smoothed loudness per second, to spot quiet passages without lyrics
    sec = librosa.frames_to_time(1, sr=sr, hop_length=hop)
    per_s = max(1, int(round(1 / sec)))
    curve = [float(rms[i:i + per_s].mean()) for i in range(0, len(rms), per_s)]
    top = max(curve) or 1.0
    return {"beat_strength": pct(strength), "beat_loud": pct(loud), "downbeat_phase": phase,
            "loudness": [round(c / top, 3) for c in curve]}


def norm(w: str) -> str:
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", w)


def transcribe(path, lyrics_lines, progress=None, language=None):
    """Words with their times. `language` ("es", "en"…): the song's; None lets Whisper detect it."""
    from faster_whisper import WhisperModel
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dev = os.environ.get("WHISPER_DEVICE", "cpu")
    model = WhisperModel(os.environ.get("WHISPER_MODEL_GPU", "large-v3") if dev == "cuda" else WHISPER_MODEL, device=dev,
                         compute_type="float16" if dev == "cuda" else "int8", download_root=str(MODELS_DIR))
    prompt = " ".join(lyrics_lines)[:400]
    # decode with ffmpeg (avoids depending on the PyAV version)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    segs, info = model.transcribe(audio, language=language or None, word_timestamps=True, initial_prompt=prompt,
                                  condition_on_previous_text=False, vad_filter=False)
    words = []
    for s in segs:
        for w in s.words or []:
            words.append({"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)})
        if progress and info.duration:
            progress(min(0.99, s.end / info.duration))
    return words


def align(lyrics_lines, words, dur):
    """Assign start/end to each lyric line by matching its words against the transcription."""
    ltoks, lidx = [], []
    for i, line in enumerate(lyrics_lines):
        for w in line.split():
            n = norm(w)
            if n:
                ltoks.append(n)
                lidx.append(i)
    ttoks = [norm(w["w"]) for w in words]
    sm = difflib.SequenceMatcher(None, ltoks, ttoks, autojunk=False)
    times = {}  # lyric token index -> (start, end)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = (words[b + k]["start"], words[b + k]["end"])
    out = []
    for i, line in enumerate(lyrics_lines):
        toks = [k for k, li in enumerate(lidx) if li == i]
        hit = [times[k] for k in toks if k in times]
        out.append({"text": line, "start": min(h[0] for h in hit) if hit else None,
                    "end": max(h[1] for h in hit) if hit else None,
                    "match": round(len(hit) / max(1, len(toks)), 2)})
    # drop unreliable stray matches (a single word of a long line)
    for l in out:
        if l["start"] is not None and l["match"] < 0.25:
            l["start"] = l["end"] = None
    # enforce order and fill gaps, interpolating by word count
    last = 0.0
    for l in out:
        if l["start"] is not None and l["start"] < last:
            l["start"] = l["end"] = None
        elif l["start"] is not None:
            last = l["end"]
    i = 0
    while i < len(out):
        if out[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j]["start"] is None:
            j += 1
        t0 = out[i - 1]["end"] if i > 0 else (words[0]["start"] if words else 0.0)
        t1 = out[j]["start"] if j < len(out) else (words[-1]["end"] if words else dur)
        if t1 <= t0:
            t1 = min(dur, t0 + 2.0 * (j - i))
        weights = [max(1, len(out[k]["text"].split())) for k in range(i, j)]
        tot = sum(weights)
        t = t0
        for k, wgt in zip(range(i, j), weights):
            d = (t1 - t0) * wgt / tot
            out[k]["start"], out[k]["end"], out[k]["guess"] = round(t, 2), round(t + d, 2), True
            t += d
        i = j
    return out


def make_snap(beat_times, dur):
    """t -> the nearest beat if it is within 0.35 s (shot cuts fall on beats)."""
    beat_arr = np.array(beat_times) if beat_times else np.arange(0, dur, 0.5)

    def snap(t, tol=0.35):
        k = np.argmin(np.abs(beat_arr - t))
        return float(beat_arr[k]) if abs(beat_arr[k] - t) <= tol else t
    return snap


def relabel(slots, lines):
    """Recompute which lyric line(s) each existing shot shows, keeping shots, photos and pins."""
    return assign_lines(slots, lines)


def plan_slots(dur, beat_times, lines, pace="normal"):
    """Split the song into shots. A shot starts with a lyric line; the pace decides how lines become shots:
    slow lets consecutive short lines of the same section share a photo, fast splits lines in two on a beat.
    The song bends it: choruses / high-energy parts go faster, bridge, intro and outro slower."""
    target = PACES.get(pace, 4.0)
    snap = make_snap(beat_times, dur)

    # a line sung from the very start (< 0.5 s) opens the first shot instead of being dropped
    timed = [(k, l) for k, l in enumerate(lines) if l.get("start") is not None and l["start"] < dur - 1]
    # segments from each line start to the next one (plus the intro before the first line)
    starts = {}
    for k, l in timed:
        starts.setdefault(snap(l["start"]) if l["start"] > 0.5 else 0.0, []).append(k)
    bounds = sorted({0.0, dur} | set(starts))
    segs = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        ks = starts.get(a, [])
        sec = (lines[ks[0]].get("section") or {"kind": "verse", "mood": "mid"}) if ks else {"kind": "intro", "mood": "low"}
        segs.append({"a": a, "b": b, "lines": ks, "sec": sec})

    def eff(sec):
        f = 1.0
        if sec.get("kind") == "chorus" or sec.get("mood") == "high":
            f = 0.75
        elif sec.get("kind") in ("bridge", "outro", "intro") or sec.get("mood") == "low":
            f = 1.3
        return target * f

    def off(x, t):  # how far a shot length is from the target, as a ratio (2 s vs 4 s == 8 s vs 4 s)
        return max(x / t, t / x) if x > 0 else 99.0

    # neighbouring lines of the same section share one shot when that is closer to the target length
    groups = []
    for g in segs:
        last = groups[-1] if groups else None
        if (last and last["lines"] and g["lines"] and last["sec"].get("kind") == g["sec"].get("kind")
                and off(g["b"] - last["a"], eff(g["sec"])) < off(last["b"] - last["a"], eff(g["sec"]))):
            last["b"], last["lines"] = g["b"], last["lines"] + g["lines"]
        else:
            groups.append(dict(g))
    cuts = []
    for g in groups:  # long shots for this pace / section: split on beats into the number of parts nearest the target
        L, t = g["b"] - g["a"], eff(g["sec"])
        n = min(range(1, 7), key=lambda n: off(L / n, t))
        cuts.append(g["a"])
        for k in range(1, n):
            cuts.append(snap(g["a"] + (g["b"] - g["a"]) * k / n))
    cuts.append(dur)
    # merge very short shots
    merged = [cuts[0]]
    for c in cuts[1:]:
        if c - merged[-1] < 1.5 and c != dur:
            continue
        merged.append(c)
    if len(merged) > 2 and merged[-1] - merged[-2] < 1.5:
        merged.pop(-2)
    slots = []
    for a, b in zip(merged[:-1], merged[1:]):
        slots.append({"start": round(a, 3), "end": round(b, 3)})
    return assign_lines(slots, lines)


def assign_lines(slots, lines):
    """Lyric of every shot: each line goes to the shot where most of it is sung (a line starting in the last
    instants of a shot belongs to the next one). A shot with no line of its own shows the line still being
    sung over at least half a second of it ("lyric_cont": the next photo of the same line), else nothing
    (an instrumental gap)."""
    def span(l):
        return l["start"], max(l.get("end") or l["start"], l["start"] + 0.3)

    def ov(s, l):
        a, b = span(l)
        return min(s["end"], b) - max(s["start"], a)
    owned = {i: [] for i in range(len(slots))}
    for k, l in enumerate(lines):
        if l.get("start") is None or not slots:
            continue
        i = max(range(len(slots)), key=lambda i: (ov(slots[i], l), -i))
        if ov(slots[i], l) > 0:
            owned[i].append(k)
    for i, s in enumerate(slots):
        ks = owned[i]
        cont = False
        if not ks:
            best = max(((ov(s, l), k) for k, l in enumerate(lines) if l.get("start") is not None), default=(0, None))
            if best[1] is not None and best[0] >= min(0.5, 0.4 * (s["end"] - s["start"])):
                ks, cont = [best[1]], True
        s.update(lyric=" ".join(lines[k]["text"] for k in ks), line_idx=ks, lyric_cont=cont)
    return slots


def carry_over(old, new):
    """Keep the photos of re-planned shots (new pace or re-analysis): each old photo goes to the new shot it
    overlaps most in time, pinned ones first; a new shot takes at most one. Photos with no free shot are
    dropped (the next suggestion fills the gaps). Returns how many pinned photos had to be dropped."""
    taken, lost = set(), 0
    olds = sorted([s for s in old if s.get("asset")], key=lambda s: not s.get("locked"))
    for s in olds:
        best, best_ov = None, 0.0
        for k, n in enumerate(new):
            ov = min(s["end"], n["end"]) - max(s["start"], n["start"])
            if k not in taken and ov > best_ov:
                best, best_ov = k, ov
        if best is None or best_ov < 0.5:
            lost += bool(s.get("locked"))
            continue
        taken.add(best)
        n = new[best]
        n["asset"], n["locked"] = s["asset"], bool(s.get("locked"))
        for key in ("clip_start", "why", "alts", "burst", "burst_best"):
            if s.get(key) is not None:
                n[key] = s[key]
    return lost
