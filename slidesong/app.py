"""Slidesong: web app that turns Immich photos plus a song into a video."""
import asyncio
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import traceback
import unicodedata
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from . import analyze, backup, export, history, i18n, insights, lexicon, immich, insight, learn, lyrics_llm, plan, remote, render, scores, suggest
from . import config
from .i18n import localize, tr

ROOT = Path(__file__).resolve().parent.parent
DATA = config.DATA
PROJECTS = DATA / "projects"
LOCAL_NAME = config.env("LOCAL_NAME", "this server")  # shown in the UI when a job runs here
PROJECTS.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(_app):
    try:
        await asyncio.to_thread(cleanup_after_restart)
    except Exception as e:
        print("cleanup failed:", e)
    try:
        await asyncio.to_thread(insight.warm_up)
    except Exception as e:  # the ML service may be down; the panel will retry on demand
        print("warm-up failed:", e)
    yield


def cleanup_after_restart():
    """Jobs live in this process only: after a restart, the ones still marked running were interrupted.
    Mark them so, and remove what they left half-written; keep the preview-clip cache to a month."""
    for d in PROJECTS.iterdir() if PROJECTS.exists() else ():
        f = d / "project.json"
        if not f.exists():
            continue
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        stale = [k for k, j in (p.get("jobs") or {}).items() if j.get("state") == "running"]
        if stale:
            for k in stale:
                p["jobs"][k].update(state="error", error="Interrupted when Slidesong restarted")
            save(p, touch=False)
        for part in [*d.glob("renders/*.part.mp4"), *d.glob("renders/*.dl"), *d.glob("exports/tmp*"),
                     *d.glob("upload*.part")]:
            shutil.rmtree(part, ignore_errors=True) if part.is_dir() else part.unlink(missing_ok=True)
    shutil.rmtree(BACKUP_TMP, ignore_errors=True)  # a backup being downloaded when it stopped
    clips = DATA / "cache" / "clips"
    if clips.exists():
        month = time.time() - 30 * 86400
        for c in clips.iterdir():
            if c.suffix in (".src", ".tmp") or c.name.endswith(".tmp.mp4") or c.stat().st_mtime < month:
                c.unlink(missing_ok=True)


app = FastAPI(title="Slidesong", lifespan=lifespan)

# Only answer to our own names (the public one, the tailnet / LAN ones, localhost): a page elsewhere cannot point
# a hostname of its own at this server (DNS rebinding) and drive the API from the owner's browser.
# SLIDESONG_ALLOWED_HOSTS="slidesong.example.com,*.example.com,localhost,127.0.0.1,192.168.1.10"; unset = any host.
# The project JSON is ~0.5 MB and polled during jobs: compress text, never media (already compressed, ranged).
app.add_middleware(GZipMiddleware, minimum_size=1024, exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + (
    "video/mp4", "video/quicktime", "audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg", "audio/flac",
    "image/jpeg", "image/webp", "image/png", "image/avif", "image/heic", "image/heif", "application/zip",
    "font/woff2", "application/octet-stream"))

class Language:
    """Each request's language (its Accept-Language header) for the messages it gets back (i18n.py)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            i18n.use(headers.get(b"accept-language", b"").decode("latin-1"))
        await self.app(scope, receive, send)


app.add_middleware(Language)


class HostRedirects:
    """Old names of this server send people to the new one, same path (SLIDESONG_HOST_REDIRECTS=
    "old.example.com=new.example.com,…"): bookmarks and shared links keep working after a rename."""

    def __init__(self, app, redirects: dict[str, str]):
        self.app, self.redirects = app, redirects

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1").split(":")[0].lower()
            to = self.redirects.get(host)
            if to:
                query = scope.get("query_string", b"").decode("latin-1")
                url = f"https://{to}{scope.get('raw_path', b'').decode('latin-1') or scope['path']}"
                code = 301 if scope["method"] in ("GET", "HEAD") else 308
                await RedirectResponse(url + (f"?{query}" if query else ""), status_code=code)(scope, receive, send)
                return
        await self.app(scope, receive, send)


_redirects = dict(x.split("=", 1) for x in (config.env("HOST_REDIRECTS", "") or "").replace(" ", "").split(",")
                  if "=" in x)
if _redirects:
    app.add_middleware(HostRedirects, redirects={k.lower(): v for k, v in _redirects.items()})

_hosts = [h.strip() for h in config.env("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)

_locks: dict[str, threading.RLock] = {}
_glock = threading.Lock()


# ---------------- storage ----------------
def lock(pid):
    with _glock:
        return _locks.setdefault(pid, threading.RLock())


def pdir(pid) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{3,80}", pid or ""):
        raise HTTPException(404)
    d = PROJECTS / pid
    if not (d / "project.json").exists():
        raise HTTPException(404, tr("Project not found"))
    return d


def load(pid) -> dict:
    return json.loads((pdir(pid) / "project.json").read_text())


def save(p: dict, touch=True):
    """Atomic write. `touch` = this is a change of the project (it moves up in the list); derived data
    (the plan, cached photo sizes) is saved without touching."""
    d = PROJECTS / p["id"]
    if touch:
        p["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = d / "project.json.tmp"
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1, default=str))
    tmp.replace(d / "project.json")


FROZEN = "The project is locked: unlock it (⋯ menu) or create a new version to change it"


def editable(p):
    """User edits are refused on a blocked ("frozen") project: it is kept as it is. Videos can still be made."""
    if p.get("frozen"):
        raise HTTPException(423, tr(FROZEN))
    return p


JOB_BLOCKS_EDITS = {"analyze", "suggest"}  # jobs that write the shots back when they end


def update(pid, fn, undo=None, key=None, job=False, touch=True):
    """Load, change with fn, save. With `undo` (a label for the page), the edit can be undone (history.py);
    `key` names the control so a run of edits on it (a slider, typing) is one undo step. Every user edit has
    an undo label, so that is also where a blocked project refuses them."""
    with lock(pid):
        p = load(pid)
        if undo:
            editable(p)
            # analyze and suggest write the shots back when they end: an edit made meanwhile would be lost
            running = _running.get(pid)
            if not job and running in JOB_BLOCKS_EDITS:
                raise HTTPException(409, tr("Wait until «{job}» finishes to change anything", job=i18n.JOB_NAME[running]))
        before = history.snapshot(p) if undo else None
        fn(p)
        if undo and history.snapshot(p) != before:
            history.push(PROJECTS / pid, undo, before, key, learn.now())  # what this edit teaches is logged after
            p["edit_rev"] = p.get("edit_rev", 0) + 1  # renders remember it: "this video is N changes old"
        save(p, touch)
        return p


def slugify(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "video"


# ---------------- background jobs ----------------
_running: dict[str, str] = {}


def run_job(pid, name, fn):
    with _glock:
        if pid in _running:
            raise HTTPException(409, tr("A job is already running: {job}", job=i18n.JOB_NAME.get(_running[pid], _running[pid])))
        _running[pid] = name

    def set_job(**kw):
        def f(p):
            p.setdefault("jobs", {}).setdefault(name, {}).update(kw)
        update(pid, f)

    last = [0.0]
    stop = _cancel[pid] = threading.Event()

    def progress(x):
        if stop.is_set():  # every long step reports progress: that is where a cancel takes effect
            raise remote.Cancelled()
        if time.time() - last[0] > 1.0:
            last[0] = time.time()
            set_job(progress=round(float(x), 3))

    # where it runs: a machine name, on the GPU worker or here, and whether it is waiting for that worker
    progress.where = lambda w, remote=False, waiting=False: set_job(where=w, remote=remote, waiting=waiting)

    def check(_=None):
        if stop.is_set():
            raise remote.Cancelled()
    progress.check = check

    def target():
        set_job(state="running", progress=0, error=None, where=None, remote=None, waiting=False, started=datetime.now().isoformat(timespec="seconds"))
        try:
            fn(progress)
            if stop.is_set():
                raise remote.Cancelled()
            set_job(state="done", progress=1, finished=datetime.now().isoformat(timespec="seconds"))
        except remote.Cancelled:
            set_job(state="cancelled", error=None, finished=datetime.now().isoformat(timespec="seconds"))
        except Exception as e:
            traceback.print_exc()
            set_job(state="error", error=str(e))
        finally:
            with _glock:
                _running.pop(pid, None)
                _cancel.pop(pid, None)

    i18n.thread(target, daemon=True).start()


_cancel: dict[str, threading.Event] = {}


@app.post("/api/projects/{pid}/cancel")
def api_cancel(pid: str):
    """Stop the project's running job (here and on the GPU worker); nothing half-done is kept."""
    ev = _cancel.get(pid)
    if ev:
        ev.set()
    return {"ok": True, "running": _running.get(pid)}


def job_analyze(pid):
    def fn(progress):
        p = load(pid)
        song = PROJECTS / pid / p["song"]["file"]
        lines = analyze.clean_lyrics(p.get("lyrics", ""))
        lang = suggest.lyrics_language(p)  # None: Whisper detects it
        dur = analyze.duration(song)
        tempo, bt = analyze.beats(song)
        progress(0.1)
        words = []
        if lines:
            words = None
            sub = lambda x: progress(0.1 + 0.85 * x)
            if remote.wait_free(progress):
                progress.where(remote.NAME, True)
                try:
                    words = remote.transcribe(song, lines, sub, lang)
                except remote.WorkerGone:
                    words = None
            if words is None:
                progress.where(LOCAL_NAME, False)
                words = analyze.transcribe(song, lines, sub, lang)
        al = analyze.align(lines, words, dur) if lines else []

        feats = analyze.audio_features(song, bt)
        for line, sec in zip(al, analyze.lyric_sections(p.get("lyrics", ""))):
            line["section"] = sec
        for line, ai in zip(al, lyrics_llm.annotate([l["text"] for l in al], p.get("title", ""), p.get("people") or [],
                                                    lang)):
            line["ai"] = ai

        def f(p):
            p["song"].update(duration=dur, tempo=tempo, beats=bt, words=words, features=feats)
            p["lines"] = al
            p["transition_overrides"] = {}
            new = analyze.plan_slots(dur, bt, al, p.get("pace", "normal"))
            # keep the photos (and pins) already chosen, also those of before a new MP3 was uploaded
            analyze.carry_over(p.get("slots") or p.get("slots_kept") or [], new)
            p.pop("slots_kept", None)
            p["slots"] = new
        update(pid, f)
        history.clear(PROJECTS / pid)  # older shots do not fit the new analysis
    return fn


SCORE_LIMIT = int(config.env("SCORE_LIMIT", "3000"))  # max new photos scored per suggestion


def score_missing(asset_ids, progress=None):
    """Compute and store GPU quality scores for the given photos that do not have them yet (best first)."""
    if insights.pull(asset_ids) == 0:  # another app keeps them and has them all
        return 0
    w = remote.available() or {}
    scores.use_scorer(w.get("scorer_info"))  # a different scorer on the worker: its photos get scored again
    todo = scores.missing(asset_ids)[:SCORE_LIMIT]
    if not todo or not w.get("scorer"):
        tag_missing(asset_ids, progress)
        return 0
    immich.faces(todo)  # fills the face cache; a photo Immich did not answer for goes without "faces" so
    # the worker looks them up itself (with "faces": [] the record would claim the photo has none)
    items = [{"id": a, **({"faces": [{"box": f["box"], "name": f.get("person") or "", "person_id": f.get("person_id")}
                                     for f in immich._faces_cache[a]]} if a in immich._faces_cache else {})}
             for a in todo]
    done = 0
    for k in range(0, len(items), 500):
        chunk = items[k:k + 500]
        try:
            recs = remote.score(chunk, lambda x: progress and progress((k + x * len(chunk)) / len(items)))
        except remote.WorkerGone as e:
            print("scorer:", e)
            break
        scores.put(recs)
        done += len(recs)
    tag_missing(asset_ids, progress)
    return done


def tag_missing(asset_ids, progress=None):
    """RAM++ tags for scored photos that do not have them yet (best first)."""
    todo = scores.untagged(asset_ids)[:SCORE_LIMIT]
    if not todo or not (remote.available() or {}).get("tagger"):
        return 0
    for k in range(0, len(todo), 500):
        chunk = [{"id": a} for a in todo[k:k + 500]]
        try:
            scores.add_tags(remote.tag(chunk, lambda x: progress and progress((k + x * len(chunk)) / len(todo))))
        except remote.WorkerGone as e:
            print("tagger:", e)
            break
    return len(todo)


# ---------------- the project's photos, analyzed on the GPU as soon as the filters are set ----------------
POOL_KEYS = ("people", "date_from", "date_to", "album_id", "videos")
SUGGEST_KEYS = POOL_KEYS + ("theme", "order", "flex_days", "learned", "shirtless", "avoid", "tuning", "lyrics_lang")
_prep = {}  # pid -> {"state", "total", "done", "error", "again"} (in memory; the results live in scores.sqlite)
_prep_lock = threading.Lock()


def pool_ids(p):
    """Every photo/video the project's filters select (not only one per burst), minus the excluded ones."""
    if not (p.get("people") or p.get("date_from") or p.get("date_to") or p.get("album_id")):
        return []  # no filter yet: that would be the whole library
    ids, _, _, _ = immich.candidates(p.get("people") or [], p.get("date_from"), p.get("date_to"),
                                     videos=(p.get("videos") or "some") != "off")
    album = [a for a in immich.album_assets(p["album_id"])] if p.get("album_id") else []
    excluded = set(p.get("excluded", []))
    return [a for a in dict.fromkeys(list(ids) + album) if a not in excluded]


def _analyzed(ids):
    have = scores.get(ids)
    return sum(1 for a in ids if "tags" in (have.get(a) or {}))


def prepare_pool(pid):
    """Quality scores + RAM++ tags for the whole pool, in chunks; waits while the worker is busy. With another app
    keeping them (insights.py), from there first; what it lacks, with this app's own worker."""
    st = _prep[pid]
    ids = pool_ids(load(pid))
    st.update(total=len(ids), done=_analyzed(ids), error=None)
    if insights.configured():  # what the other app has; the rest the usual way, right away
        if insights.pull(ids) == 0:
            st["done"] = _analyzed(ids)
            return
        st["done"] = _analyzed(ids)
    waited = 0
    k = 0
    while k < len(ids):
        chunk = ids[k:k + 500]
        have = scores.get(chunk)
        if all("tags" in (have.get(a) or {}) for a in chunk):
            k += 500
            continue
        w = remote.available()
        if not (w or {}).get("tagger"):
            if waited > 600:  # worker off (or busy) for 10 min: leave the rest for the next suggestion
                st["error"] = "no GPU worker"
                return
            time.sleep(15)
            waited += 15
            continue
        waited = 0
        immich.faces([a for a in chunk if a not in have])  # face boxes for the scorer
        score_missing(chunk)
        st["done"] = _analyzed(ids)
        k += 500


def start_prepare(pid):
    with _prep_lock:
        st = _prep.get(pid)
        if st and st["state"] == "running":
            st["again"] = True  # filters changed while running: go over the new pool afterwards
            return
        _prep[pid] = {"state": "running", "total": 0, "done": 0, "error": None, "again": False}

    def target():
        while True:
            try:
                prepare_pool(pid)
            except Exception as e:
                traceback.print_exc()
                _prep[pid]["error"] = str(e)
            with _prep_lock:
                if not _prep[pid].pop("again", False):
                    _prep[pid]["state"] = "done"
                    return
                _prep[pid]["again"] = False
    i18n.thread(target, daemon=True).start()


def wait_prepare(pid):
    while (_prep.get(pid) or {}).get("state") == "running":
        if _cancel.get(pid) and _cancel[pid].is_set():
            raise remote.Cancelled()
        time.sleep(2)


def ensure_lyrics_ai(pid):
    """Older projects: understand the lyrics once (translation + photo description per line)."""
    p = load(pid)
    lines = p.get("lines") or []
    if lines and not all(l.get("ai") for l in lines):
        ai = lyrics_llm.annotate([l["text"] for l in lines], p.get("title", ""), p.get("people") or [],
                                 suggest.lyrics_language(p))

        def f(q):
            for line, a in zip(q.get("lines") or [], ai):
                line["ai"] = a
        update(pid, f)


def job_suggest(pid):
    def fn(progress):
        ensure_lyrics_ai(pid)
        if remote.available():  # analyze the whole pool first (only what is new; usually already done)
            start_prepare(pid)
            wait_prepare(pid)
        with lock(pid):
            p = load(pid)
        if remote.available():
            progress.where(remote.NAME, True)
        # suggest with the weights there are; relearning (~80 s) runs afterwards, in the background
        suggest.suggest(p, progress, score_missing)
        chosen = [s["asset"] for s in p["slots"] if s.get("asset")]
        meta = immich.asset_meta(chosen, p.get("people"))
        for a in {a for s in p["slots"] for a in s.get("alts", [])} - set(meta):
            inf = immich._info.get(a)
            if inf:  # alternatives: no faces (fetched if they end up being used)
                meta[a] = {"id": a, "date": inf["date"], "fav": inf["fav"], "name": inf["name"], "w": inf["w"], "h": inf["h"],
                           "video": inf.get("type") == "VIDEO", "duration": inf.get("duration") or 0.0}

        def f(q):
            q["slots"] = p["slots"]
            q["vectors"] = p.get("vectors")
            # what this suggestion was made with: the page says which settings changed since (apply on re-suggest)
            q["suggested_with"] = {k: p.get(k) for k in SUGGEST_KEYS}
            q.setdefault("assets", {}).update(meta)
        warm_clips(update(pid, f, undo="suggest the photos", job=True))
        relearn_later()
    return fn


def repeated_photos(p):
    ids = sorted({s["asset"] for s in p.get("slots", []) if s.get("asset")})
    E = immich.vectors(ids)
    vecs = {a: E[k] for k, a in enumerate(ids) if E is not None and E[k].any()} if E is not None else None
    dates, dups = {}, {}
    for a in ids:
        inf = immich._info_one(a) or {}
        if inf.get("date"):
            dates[a] = datetime.fromisoformat(str(inf["date"])[:19])
        dups[a] = inf.get("duplicateId")
    return suggest.repeats(p.get("slots", []), dates, vecs, dups)


VIDEO_KEYS = ("shot_overrides", "pair_overrides", "transition_overrides", "move", "captions", "title_overlay",
              "subtitles", "motion")


def video_hash(p):
    """A fingerprint of everything that changes the video, to tell whether a render is up to date
    (undoing back to the rendered state makes it up to date again; settings for the next suggestion do not count)."""
    import hashlib
    state = {k: p.get(k) for k in VIDEO_KEYS}
    state["shots"] = [(s.get("asset"), s.get("clip_start"), s.get("start"), s.get("end")) for s in p.get("slots") or []]
    state["subs"] = [bool(l.get("sub")) for l in p.get("lines") or []]
    return hashlib.sha1(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _why(items):
    """Candidate photos with their «why» chips in the request's language."""
    for x in items or []:
        if isinstance(x, dict) and x.get("why"):
            x["why"] = [localize(w) for w in x["why"]]
    return items


def _plan_out(pl):
    if not pl:
        return pl
    return {**pl, "boundaries": [{**b, "reason": localize(b.get("reason"))} for b in pl.get("boundaries") or []]}


def reply(p):
    """A project as the page gets it: the texts stored in it (the «why» of each photo, job errors, transition
    reasons) in the request's language. A copy: the stored project is not touched."""
    q = dict(p)
    q["slots"] = [{**s, "why": {a: [localize(w) for w in ws] for a, ws in s["why"].items()}} if s.get("why") else s
                  for s in p.get("slots") or []]
    q["jobs"] = {k: {**j, "error": localize(j.get("error")), "where": localize(j.get("where"))}
                 for k, j in (p.get("jobs") or {}).items()}
    if p.get("plan"):
        q["plan"] = _plan_out(p["plan"])
    if isinstance(p.get("history"), dict):
        q["history"] = {k: localize(v) for k, v in p["history"].items()}
    if p.get("prep") and p["prep"].get("error"):
        q["prep"] = {**p["prep"], "error": localize(p["prep"]["error"])}
    return q


def plan_reply(pid):
    """An edit's answer when it changes the plan: the plan, with the project's edit_rev (so «Undo» on its
    toast undoes that edit only) and video hash."""
    p = ensure_plan(pid)
    return {**_plan_out(p["plan"]), "edit_rev": p.get("edit_rev", 0), "video_hash": video_hash(p)}


def ensure_plan(pid):
    """Audio features (for older projects) + the edit plan, saved in the project. Returns the project.
    A blocked project keeps the plan it was blocked with: rebuilding it with newer code, or while Immich is
    down, could change a finished video (a second photo, a camera move)."""
    p = load(pid)
    if p.get("frozen") and p.get("plan"):
        return p
    song = p.get("song") or {}
    if song.get("beats") and not song.get("features"):
        feats = analyze.audio_features(PROJECTS / pid / song["file"], song["beats"])
        update(pid, lambda q: q["song"].update(features=feats))
        p = load(pid)
    assets_before = json.dumps(p.get("assets"), sort_keys=True, default=str)
    pl = plan.build(p)
    try:
        pl["repeats"] = repeated_photos(p)
    except Exception as e:  # a warning must never break the plan
        print("repeats:", e)
    same = lambda a, b: json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    if same(p.get("plan"), pl) and json.dumps(p.get("assets"), sort_keys=True, default=str) == assets_before:
        return p  # nothing new: no write (looking at a project must not change it)

    def f(q):
        q["plan"] = pl
        for a, m in p.get("assets", {}).items():  # aspect / faces cached by the planner
            q.setdefault("assets", {}).setdefault(a, {}).update(m)
    return update(pid, f, touch=False)


def subtitle_lines(p):
    """The lyric lines to show as subtitles: [{start, end, text}] (all, only the 💬 ones, or none)."""
    mode = p.get("subtitles") or "off"
    lines = [l for l in p.get("lines") or [] if l.get("start") is not None and l.get("text")]
    if mode == "off" or not lines:
        return []
    if mode == "some":
        lines = [l for l in lines if l.get("sub")]
    dur = (p.get("song") or {}).get("duration") or 1e9
    starts = sorted(l["start"] for l in p.get("lines") or [] if l.get("start") is not None)
    out = []
    for l in lines:
        a = max(0.0, l["start"] - 0.1)
        nxt = next((s for s in starts if s > l["start"] + 0.05), dur)
        b = min(max((l.get("end") or a) + 0.4, a + 1.0), nxt - 0.15, dur)  # the next one starts at nxt - 0.1
        if b > a + 0.3:
            out.append({"start": round(a, 3), "end": round(b, 3), "text": l["text"]})
    return out


def slot_lines(p, i):
    """Indices of the lyric lines a shot shows."""
    s = p["slots"][i]
    if s.get("line_idx"):
        return list(s["line_idx"])
    return [k for k, l in enumerate(p.get("lines") or []) if l.get("text") and l.get("text") == s.get("lyric")
            and l.get("start") is not None and s["start"] - 1 <= l["start"] < s["end"]]


def job_render(pid, quality):
    def fn(progress):
        p = ensure_plan(pid)
        rev = p.get("edit_rev", 0)  # the edits this video includes
        vhash = video_hash(p)
        d = PROJECTS / pid
        (d / "renders").mkdir(exist_ok=True)
        size = render.SIZES[quality]
        missing = [s["asset"] for s in p["slots"] if s.get("asset") and "faces" not in p.get("assets", {}).get(s["asset"], {})]
        if missing:
            p.setdefault("assets", {}).update(immich.asset_meta(missing, p.get("people")))
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{quality}.mp4"
        out = d / "renders" / name
        done = False
        if remote.wait_free(progress):
            progress.where(remote.NAME, True)
            used = {s["asset"] for s in p["slots"] if s.get("asset")}
            used |= {sh["pair"] for sh in p["plan"].get("shots", []) if sh.get("pair")}
            light = {"title_overlay": p.get("title_overlay"), "song": {"duration": p["song"]["duration"]},
                     "subs": subtitle_lines(p),
                     "slots": p["slots"], "plan": p["plan"],
                     "assets": {a: m for a, m in p["assets"].items() if a in used}}
            try:
                remote.render(light, d / p["song"]["file"], out, quality, progress)
                done = True
            except remote.WorkerGone as e:
                print("worker:", e, "-> rendering locally")
        if not done:
            progress.where(LOCAL_NAME, False)
            render.render({**p, "subs": subtitle_lines(p)}, p["assets"], d / p["song"]["file"], out, size, progress,
                          use_original=quality.startswith("final"),
                          fps=render.FINAL_FPS if quality.startswith("final") else render.FPS)

        if quality.startswith("final"):
            try:
                learn.log_accepted(p)  # the version that was rendered, not what was edited meanwhile
            except Exception as e:
                print("feedback log failed:", e)

        def f(q):
            q.setdefault("renders", []).insert(0, {"file": name, "quality": quality, "rev": rev, "vhash": vhash,
                                                   "created": datetime.now().isoformat(timespec="seconds"),
                                                   "size": out.stat().st_size if out.exists() else None})
        update(pid, f)
    return fn


def _export_photo(aid, info, n):
    """(file name, bytes) of a shot's original photo for the export; HEIC becomes JPEG (editors choke on it)."""
    got = immich.fetch(aid, "original")
    if not got:
        return None
    name = Path((info or {}).get("name") or f"{aid}.jpg")
    data = got[0]
    if name.suffix.lower() in (".heic", ".heif", ".avif"):
        import io
        buf = io.BytesIO()
        im = render._open(data)
        icc = im.info.get("icc_profile")
        # editors choke on HEIC: near-lossless JPEG, full colour resolution, same colour profile
        im.convert("RGB").save(buf, "JPEG", quality=97, subsampling=0, icc_profile=icc) if icc else \
            im.convert("RGB").save(buf, "JPEG", quality=97, subsampling=0)
        data, name = buf.getvalue(), name.with_suffix(".jpg")
    return f"shot_{n:03d}_{name.name}", data


def job_export(pid):
    def fn(progress):
        import tempfile
        import zipfile
        p = ensure_plan(pid)
        d = PROJECTS / pid
        (d / "exports").mkdir(exist_ok=True)
        missing = [s["asset"] for s in p["slots"] if s.get("asset") and "faces" not in p.get("assets", {}).get(s["asset"], {})]
        if missing:
            p.setdefault("assets", {}).update(immich.asset_meta(missing, p.get("people")))
        used = {s["asset"] for s in p["slots"] if s.get("asset")}
        used |= {sh["pair"] for sh in p["plan"].get("shots", []) if sh.get("pair")}
        with tempfile.TemporaryDirectory(dir=d / "exports") as tmp:
            tmp = Path(tmp)
            clips = None
            if remote.wait_free(progress):
                progress.where(remote.NAME, True)
                light = {"song": {"duration": p["song"]["duration"]}, "slots": p["slots"], "plan": p["plan"],
                         "assets": {a: m for a, m in p["assets"].items() if a in used}}
                try:
                    remote.clips(light, tmp / "clips.zip", lambda x: progress(0.85 * x))
                    with zipfile.ZipFile(tmp / "clips.zip") as z:
                        z.extractall(tmp / "clips")
                    clips = json.loads((tmp / "clips" / "clips.json").read_text())
                except remote.WorkerGone as e:
                    print("worker:", e, "-> rendering the clips locally")
            if clips is None:
                progress.where(LOCAL_NAME, False)
                clips = render.render_clips(p, p["assets"], tmp / "clips", (1920, 1080), lambda x: progress(0.85 * x))
            photos = []
            for n, s in enumerate(p["slots"], 1):
                a = s.get("asset")
                if a and not (p["assets"].get(a) or {}).get("video"):
                    got = _export_photo(a, immich._info_one(a), n)
                    if got:
                        photos.append(got)
            progress(0.95)
            name = f"{datetime.now():%Y%m%d-%H%M%S}-editable.zip"
            export.write_package(d / "exports" / name, p, tmp / "clips", clips, d / p["song"]["file"], photos,
                                 p.get("title") or "Slidesong", subtitle_lines(p))

        def f(q):
            q.setdefault("exports", []).insert(0, {"file": name, "created": datetime.now().isoformat(timespec="seconds"),
                                                   "size": (d / "exports" / name).stat().st_size})
        update(pid, f)
    return fn


# ---------------- API ----------------
@app.get("/api/people")
def api_people():
    """Immich's named people, with `used` = in how many of the projects they were chosen ("las que más salen")."""
    used = Counter(n for p in _all_projects() for n in p.get("people") or [])
    return [{**x, "used": used.get(x["name"], 0)} for x in immich.people()]


@app.get("/api/config")
def api_config():
    return {"immich_web": os.environ.get("IMMICH_WEB_URL", ""),
            # the source code of what is running (AGPL-3.0 §13): a modified copy must point to its own source
            "source_url": config.env("SOURCE_URL", "https://github.com/rafa17campos/slidesong"),
            # «Copy reference for Claude» (project menu, photo details): text to paste into a chat with an
            # assistant that can read this app's data; off unless SLIDESONG_ASSISTANT_REFERENCES=1
            "assistant_refs": (config.env("ASSISTANT_REFERENCES", "") or "").lower() in ("1", "true", "yes"),
            "song_languages": list(lexicon.LANGUAGES)}  # the languages songs can be read in (slidesong/languages/)


def _read_all():
    """(dir, project) for every readable project; a damaged project.json is reported and skipped."""
    for d in sorted(PROJECTS.iterdir()):
        f = d / "project.json"
        if f.exists():
            try:
                yield d, json.loads(f.read_text())
            except (OSError, ValueError) as e:
                print(f"project {d.name} unreadable:", e)


def _all_projects():
    return [p for _, p in _read_all()]


_learning = threading.Lock()
_learning_prefs = threading.Lock()  # tuning.json: levels and removed corrections


def relearn_later(force=False):
    """Refit the suggestion weights in the background when there are new corrections (never blocks a job)."""
    if not force and learn.corrections() == learn.status().get("corrections", -1) \
            and (learn.DATA / "learning.json").exists():
        return

    def run():
        if not _learning.acquire(blocking=False):
            return  # already learning
        try:
            learn.learn(_all_projects())
        except Exception as e:
            print("learning failed:", e)
        finally:
            _learning.release()
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/learning")
def api_learning():
    return {**learn.status(), "running": _learning.locked()}


def _check_levels(levels: dict):
    for k, v in levels.items():
        if k not in suggest.DEFAULT_WEIGHTS or v not in suggest.LEVELS:
            raise HTTPException(400, tr("Invalid setting"))


@app.get("/api/learning/detail")
def api_learning_detail():
    """Everything the «Learning» page shows: each signal with its hand-tuned default, what learning would
    make of it, the level set by hand; and the projects with how many corrections each has given."""
    st = learn.status()
    learned = st.get("weights") or {}
    levels = suggest.tuning()["levels"]
    evs = learn.events()
    count = Counter(e.get("project") for e in evs if e["action"] in ("set", "reject"))
    accepted = Counter(e.get("project") for e in evs if e["action"] == "accept")
    projects = [{"id": p["id"], "title": p.get("title"), "teaches": p.get("teaches") is not False,
                 "learned": p.get("learned") is not False, "tuning": p.get("tuning") or {},
                 "corrections": count.pop(p["id"], 0), "accepted": accepted.pop(p["id"], 0)}
                for _, p in _read_all()]
    # corrections of deleted projects still teach
    projects += [{"id": pid, "title": None, "teaches": True, "learned": True, "tuning": {}, "corrections": n,
                  "accepted": accepted.pop(pid, 0), "deleted": True} for pid, n in count.items()]
    return {"status": {**st, "running": _learning.locked()},
            "signals": [{"key": k, "default": suggest.DEFAULT_WEIGHTS[k], "learned": learned.get(k),
                         "level": levels.get(k, 0)} for k in suggest.FEATURES],
            "levels": suggest.LEVELS, "projects": projects}


class Levels(BaseModel):
    levels: dict[str, int]


@app.put("/api/learning/levels")
def api_learning_levels(body: Levels):
    """The levels set by hand for every project (a signal left out is «Normal»)."""
    _check_levels(body.levels)
    with _learning_prefs:
        t = suggest.tuning()
        t["levels"] = {k: v for k, v in body.levels.items() if v}
        suggest.save_tuning(t)
    return api_learning_detail()


@app.get("/api/learning/events")
def api_learning_events(project: str | None = None, accepted: bool = False, offset: int = 0, limit: int = 30):
    """The corrections, newest first (with the shots left alone at a final render if `accepted`)."""
    titles = {p["id"]: p.get("title") for _, p in _read_all()}
    evs = [e for e in learn.events() if (accepted or e["action"] != "accept")
           and (not project or e.get("project") == project)]
    evs.reverse()
    page = evs[max(0, offset):max(0, offset) + max(1, min(limit, 100))]
    return {"total": len(evs), "events": [
        {"ts": e.get("ts"), "project": e.get("project"), "title": titles.get(e.get("project")),
         "slot": e.get("slot"), "action": e["action"], "source": e.get("source"), "new": e.get("new"),
         "old": e.get("old"), "lyric": (e.get("cue") or {}).get("lyric")} for e in page]}


@app.delete("/api/learning/events")
def api_learning_remove(ts: str, project: str):
    """Take one correction out of the learning (a mistake, a test); the weights are fitted again."""
    with _learning_prefs:
        gone = learn.remove(ts, project)
    if not gone:
        raise HTTPException(404, tr("That correction is no longer there"))
    relearn_later(force=True)
    return {"ok": True}


class Teach(BaseModel):
    on: bool


@app.post("/api/learning/projects/{pid}")
def api_learning_project(pid: str, body: Teach):
    """Whether a project teaches the app. Turning it off also forgets what it taught (a deleted project's
    corrections can only be forgotten)."""
    if not re.fullmatch(r"[a-z0-9-]{3,80}", pid):
        raise HTTPException(404)
    if (PROJECTS / pid / "project.json").exists():
        update(pid, lambda p: p.update(teaches=body.on), touch=False)
    elif body.on:
        raise HTTPException(404, tr("Project not found"))
    forgotten = 0 if body.on else learn.reset(_all_projects(), only=pid)
    relearn_later(force=True)
    return {"ok": True, "forgotten": forgotten}


class Reset(BaseModel):
    project: str | None = None


@app.post("/api/learning/reset")
def api_learning_reset(body: Reset):
    """«Start over»: forget what everything (or one project) taught. The levels set by hand stay."""
    if body.project is not None and not re.fullmatch(r"[a-z0-9-]{3,80}", body.project):
        raise HTTPException(404)
    if _learning.locked():
        raise HTTPException(409, tr("It is learning right now: wait until it finishes"))
    with _learning_prefs:
        forgotten = learn.reset(_all_projects(), only=body.project)
    relearn_later(force=True)
    return {"ok": True, "forgotten": forgotten}


@app.post("/api/learning/relearn")
def api_relearn():
    relearn_later(force=True)
    return {"running": True}


@app.get("/api/albums")
def api_albums():
    return immich.albums()


@app.get("/api/projects")
def api_projects():
    out = []
    for d, p in _read_all():
        cover = next((s["asset"] for s in p.get("slots", []) if s.get("asset")), None)
        running = _running.get(p["id"])
        job = (p.get("jobs") or {}).get(running) or {} if running else {}
        out.append({"id": p["id"], "title": p["title"], "updated": p.get("updated"), "cover": cover,
                    "slots": len(p.get("slots", [])), "renders": len(p.get("renders", [])),
                    # what the home page needs to say where each project is
                    "song": bool(p.get("song")), "photos": sum(1 for s in p.get("slots", []) if s.get("asset")),
                    "finals": sum(1 for r in p.get("renders", []) if str(r.get("quality", "")).startswith("final")),
                    "running": running, "progress": job.get("progress"),
                    "frozen": bool(p.get("frozen")), "parent": (p.get("parent") or {}).get("id")})
    return sorted(out, key=lambda x: x["updated"] or "", reverse=True)


@app.post("/api/projects")
async def api_create(title: str = Form(..., min_length=1, max_length=120)):
    pid = f"{slugify(title)}-{secrets.token_hex(2)}"
    d = PROJECTS / pid
    d.mkdir(parents=True)
    p = {"id": pid, "title": title, "title_overlay": "", "people": [], "date_from": None, "date_to": None,
         "theme": "", "pace": "normal", "lyrics": "", "song": None, "lines": [], "slots": [], "assets": {},
         "excluded": [], "renders": [], "jobs": {}, "created": datetime.now().isoformat(timespec="seconds"),
         "language": i18n.lang()}
    save(p)
    return {"id": pid}


@app.get("/api/projects/{pid}/coverage")
def api_coverage(pid: str):
    """How many of the project's candidate photos are not analysed on the GPU yet (quality scores and RAM++ tags,
    which the sensitive-photo warnings come from), and whether the GPU worker is there to do it."""
    p = load(pid)
    ids = pool_ids(p)
    if insights.configured():
        insights.pull(ids)  # what the other app already has (insights.py); it queues what it lacks
    pending = set(scores.missing(ids)) | set(scores.untagged(ids))
    w = remote.available() or {}
    hub = insights.status()
    if hub is not None and not w:  # the other app drives its own worker: it can analyse when that one is on
        return {"pool": len(ids), "pending": len(pending), "worker": bool(hub.get("workerOnline")),
                "name": localize(remote.NAME), "can_analyse": bool(hub.get("workerOnline"))}
    return {"pool": len(ids), "pending": len(pending), "worker": bool(w), "name": localize(remote.NAME),
            "can_analyse": bool(w.get("scorer") and w.get("tagger"))}


class Freeze(BaseModel):
    on: bool


@app.post("/api/projects/{pid}/freeze")
def api_freeze(pid: str, f: Freeze):
    """Block a finished project (kept as it is; videos can still be made) or unblock it."""
    if pid in _running:
        raise HTTPException(409, tr("Wait until the running job finishes"))

    if f.on and any(s.get("asset") for s in load(pid).get("slots") or []):
        with lock(pid):
            ensure_plan(pid)  # the plan it is blocked with is the one it will keep

    def g(p):
        if f.on:
            p["frozen"] = {"at": datetime.now().isoformat(timespec="seconds")}
        else:
            p.pop("frozen", None)
    update(pid, g)
    return api_get(pid)


class Duplicate(BaseModel):
    title: str


# what a new version does not take from the original: its files, jobs and history
NOT_COPIED = ("renders", "exports", "jobs", "frozen", "edit_rev", "updated", "prep", "running", "cancelling",
              "server_now", "history")


@app.post("/api/projects/{pid}/duplicate")
def api_duplicate(pid: str, dup: Duplicate):
    """A new version: the whole project (song, analysis, lyrics, photos, pins, framing, texts, settings) under a
    new id, without its videos, exports or undo history. It remembers which project it comes from."""
    title = dup.title.strip()[:120]
    if not title:
        raise HTTPException(400, tr("Give it a name"))
    src = pdir(pid)
    with lock(pid):
        p = load(pid)
    new = f"{slugify(title)}-{secrets.token_hex(2)}"
    d = PROJECTS / new
    d.mkdir(parents=True)
    try:
        if (p.get("song") or {}).get("file") and (src / p["song"]["file"]).exists():
            shutil.copy2(src / p["song"]["file"], d / p["song"]["file"])  # a copy: a new MP3 overwrites it in place
        q = {k: v for k, v in p.items() if k not in NOT_COPIED}
        # lineage: the first project of the family; versions share what they teach the suggestion (learn.py)
        q.update(id=new, title=title, renders=[], exports=[], jobs={}, parent={"id": pid, "title": p.get("title")},
                 lineage=p.get("lineage") or pid,
                 created=datetime.now().isoformat(timespec="seconds"))
        save(q)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return {"id": new}


@app.get("/api/projects/{pid}")
def api_get(pid: str):
    p = load(pid)
    p["running"] = _running.get(pid)
    p["cancelling"] = bool(_cancel.get(pid) and _cancel[pid].is_set())
    p["server_now"] = datetime.now().isoformat(timespec="seconds")  # for elapsed time / ETA in the page
    p["history"] = history.summary(PROJECTS / pid)  # labels of the next undo / redo
    p["video_hash"] = video_hash(p)
    p["lyrics_detected"] = lexicon.detect(p.get("lyrics") or "")  # for «Automatic (Spanish)»
    st = _prep.get(pid)
    if st:
        p["prep"] = {k: st.get(k) for k in ("state", "total", "done", "error")}
    return reply(p)


def _history_step(pid, direction, expect_rev=None):
    # like edits: only analyse and suggest (which write the shots back) block it; a render or export does not
    running = _running.get(pid)
    if running in JOB_BLOCKS_EDITS:
        raise HTTPException(409, tr("Wait until «{job}» finishes", job=i18n.JOB_NAME[running]))
    d = pdir(pid)
    with lock(pid):
        p = editable(load(pid))
        # «Undo» on a toast undoes that action only: refuse if another edit came after it
        if expect_rev is not None and p.get("edit_rev", 0) != expect_rev:
            raise HTTPException(409, tr("You've made another change since: undo in order with ↶"))
        old_pool = [p.get(k) for k in POOL_KEYS]
        entry = history.step(d, p, direction)
        if entry is None:
            raise HTTPException(409, tr("Nothing to undo") if direction == "undo" else tr("Nothing to redo"))
        p["edit_rev"] = p.get("edit_rev", 0) + 1
        save(p)
        if direction == "undo" and entry.get("feedback") is not None:
            try:  # what the undone edit taught the suggestion is forgotten too
                learn.forget(pid, entry["feedback"])
            except Exception as e:
                print("feedback forget failed:", e)
        if p.get("slots") and any(s.get("asset") for s in p["slots"]):
            p = ensure_plan(pid)
    if [p.get(k) for k in POOL_KEYS] != old_pool and remote.available():
        threading.Timer(1.0, start_prepare, args=(pid,)).start()
    return {**api_get(pid), "undone" if direction == "undo" else "redone": localize(entry["label"])}


@app.post("/api/projects/{pid}/undo")
def api_undo(pid: str, expect_rev: int | None = None):
    return _history_step(pid, "undo", expect_rev)


@app.post("/api/projects/{pid}/redo")
def api_redo(pid: str):
    return _history_step(pid, "redo")


# ---------------- backups ----------------
BACKUP_TMP = DATA / "cache" / "backup"
BACKUP_LAST = DATA / "backup.json"  # when the last whole backup was made (shown on the home page)


def _backup_projects(project: str | None):
    if project:
        return [(project, pdir(project))]
    return [(d.name, d) for d, _ in _read_all()]


@app.get("/api/backup/info")
def api_backup_info():
    """What a whole backup takes, to choose whether the videos go in."""
    base = videos = 0
    n = 0
    for d, p in _read_all():
        n += 1
        base += sum(f.stat().st_size for f in backup.project_files(d, p, False))
        videos += backup.videos_size(d, p)
    base += sum((DATA / f).stat().st_size for f in ("feedback.jsonl", "learning.json", "scores.sqlite")
                if (DATA / f).exists())
    last = None
    if BACKUP_LAST.exists():
        try:
            last = json.loads(BACKUP_LAST.read_text())
        except ValueError:
            pass
    return {"projects": n, "size": base, "videos_size": videos, "last": last}


@app.get("/api/backup")
def api_backup(videos: bool = False, project: str | None = None):
    """Download a backup zip: everything, or one project (?project=). Built in a temporary file (a few seconds;
    longer with the videos) and removed once sent."""
    projects = _backup_projects(project)
    BACKUP_TMP.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    name = f"slidesong-{project}-{stamp}.zip" if project else f"slidesong-backup-{stamp}.zip"
    tmp = BACKUP_TMP / f"{secrets.token_hex(6)}.zip"
    try:
        m = backup.build(tmp, data=DATA, projects=projects, videos=videos, whole=not project,
                         project_lock=lock, learn_lock=learn._lock, scores_lock=scores._lock, scores_db=scores.DB)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if not project:
        BACKUP_LAST.write_text(json.dumps({"made": m["made"], "videos": videos, "projects": len(m["projects"]),
                                           "size": tmp.stat().st_size}))
    return FileResponse(tmp, media_type="application/zip", filename=name,
                        headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@app.get("/api/worker")
def api_worker():
    h = remote.health()
    return {"name": localize(remote.NAME), "online": bool(h), "busy": bool(h and h.get("busy")), "info": h}


@app.delete("/api/projects/{pid}")
def api_delete(pid: str):
    d = pdir(pid)
    editable(load(pid))
    if pid in _running:
        raise HTTPException(409, tr("A job is running"))
    shutil.rmtree(d)
    return {"ok": True}


DATE = r"^(\d{4}-\d{2}-\d{2})?$"  # yyyy-mm-dd, or empty to clear


class Settings(BaseModel):
    title: str | None = Field(None, max_length=120)
    title_overlay: str | None = Field(None, max_length=120)
    people: list[str] | None = Field(None, max_length=60)
    date_from: str | None = Field(None, pattern=DATE)
    date_to: str | None = Field(None, pattern=DATE)
    theme: str | None = Field(None, max_length=200)
    pace: str | None = None
    lyrics: str | None = Field(None, max_length=20000)
    album_id: str | None = None
    order: str | None = None  # strict | flex | free
    videos: str | None = None  # off | some | many
    flex_days: int | None = None  # "flexible" order: how many days a photo may move
    learned: bool | None = None  # use the weights learned from corrections (False = defaults only)
    shirtless: str | None = None  # show (just flag) | avoid | never (never proposed; can still be chosen by hand)
    subtitles: str | None = None  # off | all | some (only the lines marked with 💬)
    motion: str | None = None  # calm | normal | lively (camera moves)
    lyrics_lang: str | None = None  # the song's language: "auto" (detected from the lyrics) or "es", "en"…
    avoid: str | None = Field(None, max_length=200)  # «Avoid»: what the photos of this project should not look like
    tuning: dict[str, int] | None = None  # this project's levels per signal (on top of the general ones)


SETTING_NAMES = {"title": "the title", "title_overlay": "the opening text", "people": "the people",
                 "date_from": "the dates", "date_to": "the dates", "theme": "the theme", "pace": "the pace",
                 "lyrics": "the lyrics", "album_id": "the album", "order": "the order", "videos": "the videos",
                 "flex_days": "the date margin", "learned": "the learning", "shirtless": "the sensitive photos",
                 "subtitles": "the subtitles", "motion": "the movement", "avoid": "what to avoid",
                 "tuning": "this project's settings", "lyrics_lang": "the song's language"}


@app.patch("/api/projects/{pid}")
def api_settings(pid: str, s: Settings):
    data = s.model_dump(exclude_unset=True)
    if data.get("album_id") and not immich.UUID_RE.match(data["album_id"]):
        raise HTTPException(400, tr("Invalid album"))
    for k in ("date_from", "date_to", "album_id"):
        if k in data and data[k] == "":
            data[k] = None
    if "flex_days" in data and data["flex_days"] is not None and not 1 <= data["flex_days"] <= 60:
        raise HTTPException(400, tr("Invalid margin"))
    if "videos" in data and data["videos"] not in ("off", "some", "many"):
        raise HTTPException(400, tr("Invalid video option"))
    if "motion" in data and data["motion"] not in plan.MOTION:
        raise HTTPException(400, tr("Invalid movement style"))
    if "subtitles" in data and data["subtitles"] not in ("off", "all", "some"):
        raise HTTPException(400, tr("Invalid subtitles option"))
    if "shirtless" in data and data["shirtless"] not in suggest.SHIRTLESS_PENALTY:
        raise HTTPException(400, tr("Invalid option"))
    if "order" in data and data["order"] not in ("strict", "flex", "free"):
        raise HTTPException(400, tr("Invalid order"))
    if "pace" in data and data["pace"] not in analyze.PACES:
        raise HTTPException(400, tr("Invalid pace"))
    if "lyrics_lang" in data and data["lyrics_lang"] not in ("auto", *lexicon.LANGUAGES):
        raise HTTPException(400, tr("Invalid language"))
    if data.get("tuning") is not None:
        _check_levels(data["tuning"])
        data["tuning"] = {k: v for k, v in data["tuning"].items() if v}  # «Normal» is the absence of a level

    before = editable(load(pid))
    if any(k in data and data[k] != before.get(k) for k in POOL_KEYS) and remote.available():
        threading.Timer(2.0, start_prepare, args=(pid,)).start()  # after this update is saved

    def f(p):
        old_pace = p.get("pace")
        p.update(data)
        # changing the pace rebuilds the shots (if the song was analyzed)
        if "pace" in data and data["pace"] != old_pace and (p.get("song") or {}).get("beats"):
            new = analyze.plan_slots(p["song"]["duration"], p["song"]["beats"], p["lines"], p["pace"])
            analyze.carry_over(p["slots"], new)  # keep the photos (and pins) already chosen
            p["slots"] = new
            p["transition_overrides"] = {}
    names = list(dict.fromkeys(SETTING_NAMES.get(k, k) for k in data))
    what = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)
    return reply(update(pid, f, undo=f"change {what}" if names else None, key="settings:" + ",".join(sorted(data))))


@app.post("/api/projects/{pid}/song")
async def api_song(pid: str, file: UploadFile = File(...)):
    """A new MP3. Checked before it replaces the old one; the shots are rebuilt by the next analysis, which
    carries the chosen photos (and pins) over to the new shots at the same moments."""
    d = pdir(pid)
    editable(load(pid))
    if pid in _running:
        raise HTTPException(409, tr("Wait until the running job finishes"))
    ext = Path(file.filename or "song.mp3").suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
        raise HTTPException(400, tr("Audio format not supported"))
    tmp = d / f"upload{ext}.part"
    try:
        with open(tmp, "wb") as fh:
            while chunk := await file.read(1 << 20):
                fh.write(chunk)
        dur = await run_in_threadpool(analyze.duration, tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, tr("That file doesn't look like a song that can be read"))
    name = "song" + ext
    for old in d.glob("song.*"):
        if old.name != name:
            old.unlink(missing_ok=True)
    tmp.replace(d / name)

    def f(p):
        if any(s.get("asset") for s in p.get("slots") or []):
            p["slots_kept"] = p["slots"]  # the next analysis carries these photos over
        p["song"] = {"file": name, "name": file.filename, "duration": dur,
                     "uploaded": datetime.now().isoformat(timespec="seconds")}
        p["lines"], p["slots"] = [], []
    history.clear(d)
    return await run_in_threadpool(update, pid, f)  # its lock may wait for a plan build: not on the event loop


@app.post("/api/projects/{pid}/analyze")
def api_analyze(pid: str):
    p = editable(load(pid))
    if not p.get("song"):
        raise HTTPException(400, tr("Upload the song first"))
    run_job(pid, "analyze", job_analyze(pid))
    return {"ok": True}


@app.post("/api/projects/{pid}/suggest")
def api_suggest(pid: str):
    p = editable(load(pid))
    if not p.get("slots"):
        raise HTTPException(400, tr("Analyze the song first"))
    run_job(pid, "suggest", job_suggest(pid))
    return {"ok": True}


@app.post("/api/projects/{pid}/render")
def api_render(pid: str, quality: str = "preview"):
    p = load(pid)
    if quality not in render.SIZES:
        raise HTTPException(400)
    if not any(s.get("asset") for s in p.get("slots", [])):
        raise HTTPException(400, tr("No photos chosen"))
    run_job(pid, "render", job_render(pid, quality))
    return {"ok": True}


@app.post("/api/projects/{pid}/export")
def api_export(pid: str):
    p = load(pid)
    if not any(s.get("asset") for s in p.get("slots", [])):
        raise HTTPException(400, tr("No photos chosen"))
    run_job(pid, "export", job_export(pid))
    return {"ok": True}


class SlotChange(BaseModel):
    asset: str | None = None
    action: str  # set | reject | lock | unlock
    why: list[str] | None = None  # reasons shown in the UI (from the swap dialog)
    source: str | None = None     # where the photo was picked: alts | options | search | immich
    shown: list[str] | None = None  # other options that were on screen (for learning)
    clip_start: float | None = None  # action "clip": where the video segment starts (None = centre)
    expect: str | None = None  # the photo the user saw in the shot: refuse if it changed meanwhile (double tap)


class Exchange(BaseModel):
    a: int
    b: int


PHOTO_KEYS = ("asset", "clip_start", "burst", "burst_best", "why", "alts")  # travel with the photo
SHOT_SETTINGS = ("shot_overrides", "move", "pair_overrides")                 # per-shot choices tied to the photo


@app.post("/api/projects/{pid}/exchange")
def api_exchange(pid: str, x: Exchange):
    """Swap the photos of two shots. The photo's own choices go with it (camera move, amount of movement,
    second photo, video segment); the lyric, timing and transitions stay with the shot. Both end up pinned."""
    if x.a == x.b:
        raise HTTPException(400, tr("It's the same shot"))
    before = load(pid)
    n = len(before.get("slots", []))
    if not (0 <= x.a < n and 0 <= x.b < n):
        raise HTTPException(404)
    pa, pb = before["slots"][x.a].get("asset"), before["slots"][x.b].get("asset")

    def f(p):
        sa, sb = p["slots"][x.a], p["slots"][x.b]
        for k in PHOTO_KEYS:
            va, vb = sa.pop(k, None), sb.pop(k, None)
            if vb is not None:
                sa[k] = vb
            if va is not None:
                sb[k] = va
        sa["locked"], sb["locked"] = bool(sa.get("asset")), bool(sb.get("asset"))
        for key in SHOT_SETTINGS:
            d = p.get(key) or {}
            va, vb = d.pop(str(x.a), None), d.pop(str(x.b), None)
            if vb is not None:
                d[str(x.a)] = vb
            if va is not None:
                d[str(x.b)] = va
            if d:
                p[key] = d
    result = update(pid, f, undo=f"swap shots {x.a + 1} and {x.b + 1}")
    try:  # each shot: the user preferred the other photo over the one it had
        if pa and pb:
            learn.log(result, x.a, "set", new=pb, old=pa, source="exchange")
            learn.log(result, x.b, "set", new=pa, old=pb, source="exchange")
    except Exception as e:
        print("feedback log failed:", e)
    return reply(result)


@app.post("/api/projects/{pid}/slots/{i}")
def api_slot(pid: str, i: int, c: SlotChange):
    if c.asset and not immich.UUID_RE.match(c.asset):
        raise HTTPException(400)
    p = load(pid)
    if c.asset and c.asset not in p.get("assets", {}):
        meta = immich.asset_meta([c.asset], p.get("people"))
        if not meta:
            raise HTTPException(404, tr("Can't find that photo in Immich (is it another user's?)"))
    else:
        meta = {}

    before = p["slots"][i].get("asset") if 0 <= i < len(p.get("slots", [])) else None
    shown_alts = list(p["slots"][i].get("alts", [])) if 0 <= i < len(p.get("slots", [])) else []
    new_burst = None
    if c.action == "set" and c.asset and 0 <= i < len(p.get("slots", [])) and c.asset not in p["slots"][i].get("burst", []):
        try:  # a photo picked by hand keeps the 🎞️ burst picker
            new_burst = suggest.burst_for(p, c.asset)
        except Exception as e:
            print("burst lookup failed:", e)

    def f(p):
        if not 0 <= i < len(p["slots"]):
            raise HTTPException(404)
        s = p["slots"][i]
        if c.expect is not None and s.get("asset") != c.expect:
            raise HTTPException(409, tr("The photo of that shot had already changed"))
        p.setdefault("assets", {}).update(meta)
        used = {x.get("asset") for x in p["slots"]}
        if c.action == "set":
            if c.asset not in s.get("burst", []):  # another moment: its own burst (looked up above)
                s.pop("burst_best", None)
                if new_burst:
                    s["burst"] = new_burst
                else:
                    s.pop("burst", None)
            if s.get("asset") and s["asset"] != c.asset and s["asset"] not in s.get("alts", []):
                s.setdefault("alts", []).insert(0, s["asset"])
            s["alts"] = [a for a in s.get("alts", []) if a != c.asset]
            if s.get("asset") != c.asset:
                s.pop("clip_start", None)
            s["asset"], s["locked"] = c.asset, True
            if c.why:
                s.setdefault("why", {})[c.asset] = c.why[:8]
        elif c.action == "reject":
            # "No usar" (reject): excluded from this project; the next free alternative takes its place
            bad = s.get("asset")
            if bad and bad not in p["excluded"]:
                p["excluded"].append(bad)
            alts = [a for a in s.get("alts", []) if a not in p["excluded"] and a not in used]
            s["alts"] = [a for a in s.get("alts", []) if a != bad]
            s["asset"] = alts[0] if alts else None
            s.pop("burst", None)
            s.pop("burst_best", None)
            s.pop("clip_start", None)
            if alts:
                s["alts"].remove(alts[0])
            s["locked"] = False
        elif c.action == "clip":  # which part of a video clip is used
            if c.clip_start is None:
                s.pop("clip_start", None)
            else:
                s["clip_start"] = round(max(0.0, float(c.clip_start)), 2)
        elif c.action == "unlock":
            s["locked"] = False
        elif c.action == "lock":
            s["locked"] = True
        else:
            raise HTTPException(400)
    label = {"set": "change the photo of shot {n}", "reject": "don't use the photo of shot {n}",
             "clip": "choose the video clip of shot {n}", "lock": "pin the photo of shot {n}",
             "unlock": "unpin the photo of shot {n}"}.get(c.action, "change shot {n}")
    result = update(pid, f, undo=label.format(n=i + 1), key=f"clip:{i}" if c.action == "clip" else None)
    try:  # every correction teaches the suggestion (learn.py)
        if c.action == "set" and c.asset != before:
            learn.log(result, i, "set", new=c.asset, old=before,
                      shown=[a for a in (c.shown or []) if a != c.asset], source=c.source)
        elif c.action == "reject" and before:
            learn.log(result, i, "reject", old=before, shown=shown_alts[:3], source="no-usar")
        elif c.action == "lock" and before:  # pinning a suggested photo = the suggestion was right
            learn.log(result, i, "accept", new=before, shown=[a for a in shown_alts[:3] if a != before], source="pin")
    except Exception as e:
        print("feedback log failed:", e)
    return reply(result)


@app.get("/api/projects/{pid}/slots/{i}/burst")
def api_burst(pid: str, i: int):
    """The photos of the same moment as the shot's photo, in time order, with quality hints and the best marked."""
    p = load(pid)
    if not 0 <= i < len(p.get("slots", [])):
        raise HTTPException(404)
    s = p["slots"][i]
    if s.get("asset") and not s.get("burst"):  # older picks: look the burst up now and remember it
        b = suggest.burst_for(p, s["asset"])
        if b:
            update(pid, lambda q: q["slots"][i].update(burst=b) if q["slots"][i].get("asset") == s["asset"] else None)
            s["burst"] = b
    ids = [a for a in s.get("burst", []) if a not in set(p.get("excluded", [])) or a == s.get("asset")]
    have = scores.get(ids)
    out = []
    for a in ids:
        q, hints = suggest.burst_quality(have.get(a), p.get("people") or [])
        inf = immich._info.get(a) or {}
        out.append({"id": a, "date": inf.get("date"), "current": a == s.get("asset"), "q": q, "why": hints})
    best = s.get("burst_best")  # same criterion as the suggestion; the simple ranking only as a fallback
    scored = [x for x in out if x["q"] is not None]
    if best in ids:
        next(x for x in out if x["id"] == best)["best"] = True
    elif len(scored) > 1:
        max(scored, key=lambda x: x["q"])["best"] = True
    return _why(out)


@app.post("/api/projects/{pid}/unexclude")
def api_unexclude(pid: str, asset: str = Form(...)):
    return reply(update(pid, lambda p: p["excluded"].remove(asset) if asset in p["excluded"] else None,
                        undo="allow a photo again"))


@app.get("/api/projects/{pid}/plan")
def api_plan(pid: str):
    if _running.get(pid) in JOB_BLOCKS_EDITS:  # the shots are being rewritten: the stored plan until it ends
        p = load(pid)
        return _plan_out(p.get("plan")) or {"shots": [], "boundaries": []}
    with lock(pid):
        return _plan_out(ensure_plan(pid)["plan"])


class TransitionChange(BaseModel):
    kind: str | None = None  # None = back to automatic


@app.post("/api/projects/{pid}/transitions/{after_slot}")
def api_transition(pid: str, after_slot: int, c: TransitionChange):
    if c.kind is not None and c.kind not in plan.KINDS:
        raise HTTPException(400, tr("Invalid transition"))

    def f(p):
        if not 0 <= after_slot < len(p.get("slots") or []):
            raise HTTPException(404, tr("That shot doesn't exist"))
        o = p.setdefault("transition_overrides", {})
        if c.kind is None:
            o.pop(str(after_slot), None)
        else:
            o[str(after_slot)] = c.kind
    update(pid, f, undo=f"change the transition after shot {after_slot + 1}")
    with lock(pid):
        return plan_reply(pid)


class SlotOptions(BaseModel):
    people: list[str] | None = None  # None = the project's people
    days: int | None = None          # window around the current photo; None = any date
    all: bool = False                # every photo of the filters, not only the best ones


@app.post("/api/projects/{pid}/slots/{i}/options")
def api_slot_options(pid: str, i: int, o: SlotOptions):
    p = load(pid)
    if not 0 <= i < len(p.get("slots", [])):
        raise HTTPException(404)
    return _why(suggest.options_for_slot(p, i, o.people, o.days, everything=o.all))


class MoveChange(BaseModel):
    kind: str | None = None  # None = automatic


@app.post("/api/projects/{pid}/shots/{slot}")
def api_move(pid: str, slot: int, c: MoveChange):
    """The camera move / layout of the shot starting at this slot (None = automatic). Returns the new plan."""
    if c.kind is not None and c.kind not in plan.MOVES:
        raise HTTPException(400, tr("Invalid movement"))

    def f(p):
        if not 0 <= slot < len(p.get("slots") or []):
            raise HTTPException(404, tr("That shot doesn't exist"))
        o = p.setdefault("shot_overrides", {})
        if c.kind is None:
            o.pop(str(slot), None)
        else:
            o[str(slot)] = c.kind
    update(pid, f, undo=f"change the framing of shot {slot + 1}")
    with lock(pid):
        return plan_reply(pid)


SNIPS_KEEP = 3600  # snippet previews are throwaway: removed after an hour


@app.post("/api/projects/{pid}/slots/{i}/snippet")
def api_snippet(pid: str, i: int):
    """~6 s of video around one shot (its look, the transitions in and out, the music), 540p, made here."""
    with lock(pid):
        p = ensure_plan(pid)
    shots = (p.get("plan") or {}).get("shots") or []
    sh = next((s for s in shots if i in s["slots"]), None)
    if not sh:
        raise HTTPException(404, tr("That shot has no photo"))
    dur = p["song"]["duration"]
    a, b = max(0.0, sh["start"] - 1.5), min(dur, sh["end"] + 1.5)
    if b - a < 6:  # short shots: show a bit more around them
        pad = (6 - (b - a)) / 2
        a, b = max(0.0, a - pad), min(dur, b + pad)
    d = PROJECTS / pid / "snips"
    d.mkdir(exist_ok=True)
    for old in d.glob("*.mp4"):
        if time.time() - old.stat().st_mtime > SNIPS_KEEP:
            old.unlink(missing_ok=True)
    missing = [s["asset"] for s in p["slots"] if s.get("asset") and "faces" not in p.get("assets", {}).get(s["asset"], {})]
    if missing:
        p.setdefault("assets", {}).update(immich.asset_meta(missing, p.get("people")))
    name = f"snip-{i}-{int(time.time())}.mp4"
    render.render({**p, "subs": subtitle_lines(p)}, p["assets"], PROJECTS / pid / p["song"]["file"], d / name,
                  (960, 540), None, use_original=False, window=(a, b))
    return {"file": name, "from": round(a, 2), "to": round(b, 2)}


@app.get("/api/projects/{pid}/slots/{i}/partners")
def api_partners(pid: str, i: int):
    """Candidates for the second photo of a shot (its burst, then the rest of that day)."""
    p = load(pid)
    if not 0 <= i < len(p.get("slots", [])):
        raise HTTPException(404)
    return _why(plan.partner_candidates(p, i))


class PairChange(BaseModel):
    asset: str | None = None  # None = back to the automatic choice


@app.post("/api/projects/{pid}/slots/{i}/pair")
def api_pair(pid: str, i: int, c: PairChange):
    """Choose the second photo of a shot (diptych / two prints); returns the new plan."""
    if c.asset and not immich.UUID_RE.match(c.asset):
        raise HTTPException(400)

    def f(p):
        if not 0 <= i < len(p.get("slots", [])):
            raise HTTPException(404)
        po = p.setdefault("pair_overrides", {})
        if c.asset:
            po[str(i)] = c.asset
            so = p.setdefault("shot_overrides", {})
            if so.get(str(i)) not in ("diptych_other", "polaroid_pair"):
                so[str(i)] = "diptych_other"  # picking a second photo means: show it
        else:
            po.pop(str(i), None)
    update(pid, f, undo=f"change the second photo of shot {i + 1}")
    with lock(pid):
        return plan_reply(pid)


class MoveAmount(BaseModel):
    factor: float | None = None  # 0..1.5 x the automatic camera move; None = automatic


@app.post("/api/projects/{pid}/shots/{slot}/move")
def api_move_amount(pid: str, slot: int, c: MoveAmount):
    """How much the camera moves in a shot (still capped so the photo never pixelates). Returns the plan."""
    if c.factor is not None and not 0 <= c.factor <= 1.5:
        raise HTTPException(400)

    def f(p):
        if not 0 <= slot < len(p.get("slots") or []):
            raise HTTPException(404, tr("That shot doesn't exist"))
        m = p.setdefault("move", {})
        if c.factor is None:  # 100 % is a choice too: automatic may stop below it (pixelation limit)
            m.pop(str(slot), None)
        else:
            m[str(slot)] = round(c.factor, 2)
    update(pid, f, undo=f"change the movement of shot {slot + 1}", key=f"move:{slot}")
    with lock(pid):
        return plan_reply(pid)


class CaptionChange(BaseModel):
    asset: str
    text: str | None = None  # None = back to the automatic text; "" = no text


@app.post("/api/projects/{pid}/captions")
def api_caption(pid: str, c: CaptionChange):
    """The handwritten text on the bottom edge of a print; returns the new plan."""
    if not immich.UUID_RE.match(c.asset):
        raise HTTPException(400)

    def f(p):
        caps = p.setdefault("captions", {})
        if c.text is None:
            caps.pop(c.asset, None)
        else:
            caps[c.asset] = c.text.strip()[:40]
    update(pid, f, undo="change the photo's caption", key=f"caption:{c.asset}")
    with lock(pid):
        return plan_reply(pid)


class SubToggle(BaseModel):
    on: bool


@app.post("/api/projects/{pid}/slots/{i}/subs")
def api_slot_subs(pid: str, i: int, t: SubToggle):
    """Show (or not) the subtitles of the lines this shot covers ("only the chosen ones" mode)."""
    def f(p):
        if not 0 <= i < len(p.get("slots", [])):
            raise HTTPException(404)
        for k in slot_lines(p, i):
            p["lines"][k]["sub"] = t.on
    return reply(update(pid, f, undo=f"{'add' if t.on else 'remove'} the subtitle of shot {i + 1}"))


@app.post("/api/projects/{pid}/lines/{k}/sub")
def api_line_sub(pid: str, k: int, t: SubToggle):
    """Show (or not) one lyric line as a subtitle ("only the chosen ones" mode), from the lyrics view."""
    def f(p):
        if not 0 <= k < len(p.get("lines") or []):
            raise HTTPException(404)
        p["lines"][k]["sub"] = t.on
    return reply(update(pid, f, undo=f"{'add' if t.on else 'remove'} the subtitle of a line"))


class RankIds(BaseModel):
    ids: list[str]


@app.post("/api/projects/{pid}/slots/{i}/rank")
def api_slot_rank(pid: str, i: int, r: RankIds):
    """Details for sorting/filtering an explicit list of photos in the swap dialog (e.g. the suggested ones)."""
    p = load(pid)
    if not 0 <= i < len(p.get("slots", [])):
        raise HTTPException(404)
    return _why(suggest.rank_for_slot(p, i, [a for a in r.ids if immich.UUID_RE.match(a)][:80]))


@app.get("/api/projects/{pid}/assets/{aid}/analysis")
def api_analysis(pid: str, aid: str, slot: int | None = None):
    if not immich.UUID_RE.match(aid):
        raise HTTPException(404)
    return insight.analyze(aid, load(pid), slot)


@app.get("/api/projects/{pid}/search")
def api_search(pid: str, q: str, only_people: bool = True, only_dates: bool = False,
               people: list[str] | None = Query(None), slot: int | None = None):
    p = load(pid)
    ids = immich.search(q, (people or p.get("people")) if only_people else None,
                        p.get("date_from") if only_dates else None, p.get("date_to") if only_dates else None,
                        limit=60, exclude=p.get("excluded", []))
    if slot is not None and 0 <= slot < len(p.get("slots", [])):
        return _why(suggest.rank_for_slot(p, slot, ids))  # with fit, quality, dates... for sorting and filtering
    return [{"id": a, "date": immich._info.get(a, {}).get("date")} for a in ids]


CLIPS = DATA / "cache" / "clips"
_clip_locks = {}


def clip_preview(aid):
    """Browser-safe copy of a video asset (H.264 720p, no sound), made once and cached.
    Phone videos are often HEVC, which most browsers cannot play."""
    out = CLIPS / f"{aid}.mp4"
    if out.exists():
        return out
    with _glock:
        lk = _clip_locks.setdefault(aid, threading.Lock())
    with lk:
        if out.exists():
            return out
        CLIPS.mkdir(parents=True, exist_ok=True)
        src = CLIPS / f"{aid}.src"
        up = immich.video_stream(aid, None)
        try:
            if up.status_code != 200:
                return None
            with open(src, "wb") as f:
                for chunk in up.iter_bytes(1 << 20):
                    f.write(chunk)
        finally:
            up.close()
        tmp = CLIPS / f"{aid}.tmp.mp4"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an", "-vf", "scale=-2:'min(720,ih)'",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
        src.unlink(missing_ok=True)
        if r.returncode != 0:
            print("clip preview failed:", r.stderr[-300:])
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(out)
        return out


def warm_clips(p):
    """Prepare the previews of the video clips a project uses (in the background)."""
    vids = [s["asset"] for s in p.get("slots", []) if s.get("asset") and (p.get("assets", {}).get(s["asset"]) or {}).get("video")]
    if vids:
        threading.Thread(target=lambda: [clip_preview(a) for a in vids], daemon=True).start()


@app.get("/api/assets/{aid}/{kind}")
def api_asset(aid: str, kind: str, request: Request, authorization: str = Header("")):
    if kind == "video" and not (remote.TOKEN and hmac.compare_digest(authorization, f"Bearer {remote.TOKEN}")):
        # the browser gets the light H.264 preview (the worker, with its token, the original below)
        if not immich.UUID_RE.match(aid):
            raise HTTPException(404)
        f = clip_preview(aid)
        if not f:
            raise HTTPException(404, tr("Couldn't prepare the video"))
        return FileResponse(f, media_type="video/mp4", headers={"Cache-Control": "private, max-age=86400"})
    if kind == "video":  # original MP4 of a video asset, with Range support (render worker)
        if not immich.UUID_RE.match(aid):
            raise HTTPException(404)
        up = immich.video_stream(aid, request.headers.get("range"))
        if up.status_code not in (200, 206):
            up.close()
            raise HTTPException(404)
        headers = {k: v for k, v in up.headers.items()
                   if k.lower() in ("content-range", "accept-ranges", "content-length", "content-type")}

        def body():
            try:
                yield from up.iter_bytes(1 << 20)
            finally:
                up.close()
        return StreamingResponse(body(), status_code=up.status_code, headers=headers,
                                 media_type=up.headers.get("content-type", "video/mp4"))
    if kind == "original":  # worker only
        if not remote.TOKEN or not hmac.compare_digest(authorization, f"Bearer {remote.TOKEN}"):
            raise HTTPException(401)
        if ((immich._info_one(aid) if immich.UUID_RE.match(aid) else None) or {}).get("type") == "VIDEO":
            raise HTTPException(404)  # a whole video read into memory for nothing (photos only here)
    elif kind not in ("thumbnail", "preview"):
        raise HTTPException(404)
    got = immich.fetch(aid, kind)
    if not got:
        raise HTTPException(404)
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/projects/{pid}/files/{name}")
def api_file(pid: str, name: str):
    d = pdir(pid)
    if not re.fullmatch(r"(song\.\w+|[\w.-]+\.mp4|[\w.-]+-editable\.zip)", name):
        raise HTTPException(404)
    sub = "exports" if name.endswith(".zip") else "snips" if name.startswith("snip-") else "renders"
    f = d / name if name.startswith("song.") else d / sub / name
    if not f.exists():
        raise HTTPException(404)
    # the song keeps its name when replaced: never let the browser reuse the old one
    return FileResponse(f, headers={"Cache-Control": "no-cache"} if name.startswith("song.") else None)


@app.delete("/api/projects/{pid}/files/{name}")
def api_delete_file(pid: str, name: str):
    """Delete a rendered video or an editable export of the project."""
    d = pdir(pid)
    if not re.fullmatch(r"([\w.-]+\.mp4|[\w.-]+-editable\.zip)", name) or name.startswith("snip-"):
        raise HTTPException(404)
    key, sub = ("exports", "exports") if name.endswith(".zip") else ("renders", "renders")
    (d / sub / name).unlink(missing_ok=True)
    return reply(update(pid, lambda p: p.update({key: [r for r in p.get(key, []) if r.get("file") != name]})))


# The interface (React, built from frontend/ into web/): every page of the single-page app gets index.html and
# its router takes it from there. /v2/... was its address while it was being built; /clasica/ was the first
# interface, retired on 2026-11-21 (old bookmarks land on the home page).
WEB = Path(config.env("WEB", ROOT / "web"))
class ImmutableFiles(StaticFiles):
    """The interface's build files carry a content hash in their names: cache them for good."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return r


if (WEB / "assets").is_dir():
    app.mount("/assets", ImmutableFiles(directory=WEB / "assets"), name="web-assets")


@app.get("/clasica", include_in_schema=False)
@app.get("/clasica/{rest:path}", include_in_schema=False)
def old_classic(rest: str = ""):
    return RedirectResponse("/", status_code=301)


@app.get("/v2", include_in_schema=False)
@app.get("/v2/{path:path}", include_in_schema=False)
def old_v2(path: str = ""):
    return RedirectResponse(f"/{path}", status_code=301)


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(WEB / "favicon.svg", media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


@app.get("/", include_in_schema=False)
@app.get("/learning", include_in_schema=False)
@app.get("/aprendizaje", include_in_schema=False)  # its first address (the page redirects)
@app.get("/p/{path:path}", include_in_schema=False)
def web_index(path: str = ""):
    f = WEB / "index.html"
    if not f.exists():
        raise HTTPException(404, tr("The interface is not built (cd frontend && npm run build)"))
    return FileResponse(f, media_type="text/html", headers={"Cache-Control": "no-cache"})
