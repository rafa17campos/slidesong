"""Client for the GPU worker. If it does not answer, the app does the work locally."""
import json
import os
import time
from pathlib import Path

import httpx
from . import config

URL = config.env("WORKER_URL", "").rstrip("/")
TOKEN = os.environ.get("WORKER_TOKEN", "")
NAME = config.env("WORKER_NAME", "GPU computer")


class WorkerGone(Exception):
    pass


def _detail(r):
    """The worker's refusal, as its message (FastAPI's {"detail": ...}) or the start of the body."""
    try:
        d = r.json().get("detail")
        if isinstance(d, str):
            return d
    except Exception:
        pass
    return r.text[:200]


class Cancelled(Exception):
    """The user cancelled the job (raised from progress callbacks)."""


def health() -> dict | None:
    """The worker's /health (with `busy`), or None when it does not answer."""
    if not URL or not TOKEN:
        return None
    try:
        r = httpx.get(URL + "/health", timeout=1.5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def available() -> dict | None:
    """The worker if it is on and free right now (for background work, which can wait for later)."""
    h = health()
    return h if h and not h.get("busy") else None


def wait_free(progress=None, max_wait=900) -> dict | None:
    """For a job the user started: the worker if it is on, waiting while it is busy (usually with the background
    photo analysis, which works in short chunks) instead of quietly running it here, much slower.
    None if it is off (or still busy after `max_wait` s). The wait shows up in the job bar and can be cancelled."""
    t0 = time.time()
    while True:
        h = health()
        if not h:
            return None
        if not h.get("busy"):
            return h
        if time.time() - t0 > max_wait:
            return None
        if progress is not None:
            if hasattr(progress, "where"):
                progress.where(NAME, True, waiting=True)
            if hasattr(progress, "check"):
                progress.check()
        time.sleep(3)


def _h():
    return {"Authorization": f"Bearer {TOKEN}"}


def _wait(jid, progress, out_path=None):
    misses = 0
    while True:
        time.sleep(1.0)
        try:
            j = httpx.get(f"{URL}/jobs/{jid}", headers=_h(), timeout=10).json()
            misses = 0
        except Exception:
            misses += 1
            if misses > 20:
                raise WorkerGone(f"{NAME} stopped responding")
            continue
        if progress:
            try:
                progress(j.get("progress", 0))
            except Cancelled:  # stop the worker too, then give up
                try:
                    httpx.post(f"{URL}/jobs/{jid}/cancel", headers=_h(), timeout=10)
                except Exception:
                    pass
                raise
        if j["state"] == "cancelled":
            raise Cancelled()
        if j["state"] == "error":
            raise RuntimeError(f"{NAME}: {j['error']}")
        if j["state"] == "done":
            break
    try:
        with httpx.stream("GET", f"{URL}/jobs/{jid}/result", headers=_h(), timeout=600) as r:
            r.raise_for_status()
            if out_path:
                tmp = Path(str(out_path) + ".dl")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                tmp.replace(out_path)
                return out_path
            return json.loads(r.read())
    finally:
        try:
            httpx.delete(f"{URL}/jobs/{jid}", headers=_h(), timeout=10)
        except Exception:
            pass


def render(project, song_path, out_path, quality, progress=None):
    with open(song_path, "rb") as f:
        r = httpx.post(URL + "/render", headers=_h(), timeout=120,
                       data={"project": json.dumps(project, ensure_ascii=False, default=str), "quality": quality},
                       files={"song": (Path(song_path).name, f)})
    if r.status_code != 200:
        raise WorkerGone(f"{NAME} refused the job: {_detail(r)}")
    return _wait(r.json()["id"], progress, out_path)


def clips(project, out_path, progress=None):
    """Per-shot clips (zip with clips.json) rendered on the worker."""
    r = httpx.post(URL + "/clips", headers=_h(), timeout=120,
                   data={"project": json.dumps(project, ensure_ascii=False, default=str)})
    if r.status_code != 200:
        raise WorkerGone(f"{NAME} refused the job: {_detail(r)}")
    return _wait(r.json()["id"], progress, out_path)


def transcribe(song_path, lines, progress=None, language=None):
    with open(song_path, "rb") as f:
        r = httpx.post(URL + "/transcribe", headers=_h(), timeout=120,
                       data={"lines": json.dumps(lines, ensure_ascii=False), "language": language or ""},
                       files={"song": (Path(song_path).name, f)})
    if r.status_code != 200:
        raise WorkerGone(f"{NAME} refused the job: {_detail(r)}")
    return _wait(r.json()["id"], progress)


def score(items, progress=None):
    """Quality scores for [{id, faces}] on the worker. Returns a list of score records."""
    r = httpx.post(URL + "/score", headers=_h(), timeout=120,
                   data={"items": json.dumps(items, ensure_ascii=False)})
    if r.status_code != 200:
        raise WorkerGone(f"{NAME} refused the job: {_detail(r)}")
    return _wait(r.json()["id"], progress)



def tag(items, progress=None):
    """RAM++ tags for [{id}] on the worker. Returns [{id, tags}]."""
    r = httpx.post(URL + "/tag", headers=_h(), timeout=120, data={"items": json.dumps(items)})
    if r.status_code != 200:
        raise WorkerGone(f"{NAME} refused the job: {_detail(r)}")
    return _wait(r.json()["id"], progress)
