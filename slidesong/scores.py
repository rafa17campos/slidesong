"""Persistent per-photo quality scores (computed on the GPU worker by its scorer, stored here for good).

Scores are keyed by Immich asset id and reused by every project. Missing ones are computed on demand when a
project needs them and the worker is online. Each record is kept with the identity of the scorer that made it
("name@version", docs/analysers.md): only records of the active scorer count, so changing the scorer means
scoring again, never mixing scales.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
from . import config

DATA = config.DATA
DB = DATA / "scores.sqlite"
# the scorer shipped in scorer/ (its analyser.json); the active one is whatever the worker last announced
REFERENCE = {"name": "aesthetic-v2.5", "version": 3, "face_focus": {"blurry": 1.6, "soft": 1.8}}
UNNAMED = {"name": "aesthetic-v2.5", "version": 2}
VERSION = REFERENCE["version"]
ACTIVE = DATA / "scorer.json"

_lock = threading.Lock()
_active = {"mtime": None, "info": REFERENCE}


def active() -> dict:
    """The active scorer: {name, version, face_focus}."""
    try:
        m = ACTIVE.stat().st_mtime_ns
    except OSError:
        return REFERENCE
    if _active["mtime"] != m:
        try:
            info = json.loads(ACTIVE.read_text())
            _active.update(mtime=m, info=info if info.get("name") and info.get("version") is not None else REFERENCE)
        except (OSError, ValueError):
            _active.update(mtime=m, info=REFERENCE)
    return _active["info"]


def scorer_id(info=None) -> str:
    info = info or active()
    return f"{info.get('name')}@{info.get('version')}"


def use_scorer(info):
    """The worker announced its scorer (GET /health → scorer_info): make it the active one if it changed."""
    if not isinstance(info, dict) or not info.get("name") or info.get("version") is None:
        return
    keep = {k: info[k] for k in ("name", "version", "face_focus") if k in info}
    if keep != active():
        ACTIVE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE.write_text(json.dumps(keep))
        _active.update(mtime=ACTIVE.stat().st_mtime_ns, info=keep)


def _conn():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("create table if not exists scores (id text primary key, v integer, data text, updated text)")
    cols = {r[1] for r in c.execute("pragma table_info(scores)")}
    if "scorer" not in cols:  # before scorers had an identity: version 2 was the reference scorer
        c.execute("alter table scores add column scorer text")
        c.execute("update scores set scorer = ? where v = ?", (scorer_id(UNNAMED), UNNAMED["version"]))
    return c


def get(ids):
    """{asset_id: score dict} for the ids that have current scores."""
    out = {}
    ids = list(ids)
    with _lock, _conn() as c:
        for k in range(0, len(ids), 900):
            chunk = ids[k:k + 900]
            q = f"select id, data from scores where scorer = ? and id in ({','.join('?' * len(chunk))})"
            for aid, data in c.execute(q, [scorer_id(), *chunk]):
                out[aid] = json.loads(data)
    return out


def _carry_over(ids):
    """Version 3 of the reference scorer only changed how faces are measured, so its version 2 records of photos
    without faces are what it would give: keep them as version 3 instead of scoring those photos again."""
    if scorer_id() != scorer_id(REFERENCE) or not ids:
        return
    keep = []
    with _lock, _conn() as c:
        for k in range(0, len(ids), 900):
            chunk = ids[k:k + 900]
            q = f"select data from scores where scorer = ? and id in ({','.join('?' * len(chunk))})"
            for (data,) in c.execute(q, [scorer_id(UNNAMED), *chunk]):
                rec = json.loads(data)
                if not rec.get("faces"):
                    keep.append({**rec, "v": VERSION})
    if keep:
        put(keep, REFERENCE)


def missing(ids):
    ids = list(ids)
    have = get(ids)
    todo = [a for a in ids if a not in have]
    if todo:
        _carry_over(todo)
        have = get(todo)
        todo = [a for a in todo if a not in have]
    return todo


def _old_tags(ids):
    """RAM++ tags of any version of the records (re-scoring must not throw the tags away)."""
    out = {}
    with _lock, _conn() as c:
        for k in range(0, len(ids), 900):
            chunk = ids[k:k + 900]
            for aid, data in c.execute(f"select id, data from scores where id in ({','.join('?' * len(chunk))})", chunk):
                t = json.loads(data).get("tags")
                if t is not None:
                    out[aid] = t
    return out


def put(records, scorer=None):
    """Store records of the active scorer (or of `scorer`, {name, version}, when they come from elsewhere)."""
    info = scorer or active()
    now = datetime.now().isoformat(timespec="seconds")
    tags = _old_tags([r["id"] for r in records if r.get("id") and "tags" not in r])
    records = [{**r, "tags": tags[r["id"]]} if r.get("id") in tags and "tags" not in r else r for r in records]
    with _lock, _conn() as c:
        c.executemany("insert or replace into scores (id, v, data, updated, scorer) values (?, ?, ?, ?, ?)",
                      [(r["id"], info.get("version"), json.dumps(r, ensure_ascii=False), now, scorer_id(info))
                       for r in records if r.get("id")])


def untagged(ids):
    """Photos with quality scores but no RAM++ tags yet."""
    have = get(ids)
    return [a for a in ids if a in have and "tags" not in have[a]]


def add_tags(results):
    """Merge [{id, tags}] into the stored records."""
    have = get([r["id"] for r in results])
    put([{**have[r["id"]], "tags": r.get("tags", [])} for r in results if r.get("id") in have])


def count():
    with _lock, _conn() as c:
        return c.execute("select count(*) from scores where scorer = ?", (scorer_id(),)).fetchone()[0]


# ---------------- interpretation ----------------
FACE_MIN = 0.06  # faces narrower than this (relative to the photo width) are too small to judge
# face "focus": each scorer says below what it looks blurry or a bit soft (analyser.json, face_focus). The
# reference one was calibrated by eye on 32 faces: below 1.6 blurry (~27 % of faces), 1.6-1.8 soft (~13 %).


def _blur(focus):
    """1 = blurry, 0.5 = a bit soft, 0 = sharp (or no face big enough to judge); the worst face counts."""
    ff = active().get("face_focus") or {}
    if not focus or "blurry" not in ff:
        return 0.0
    m = min(focus)
    return 1.0 if m < ff["blurry"] else 0.5 if m < ff.get("soft", ff["blurry"]) else 0.0


def face_summary(rec, people):
    """Smile / eyes / sharpness of the given people's faces in one scored photo."""
    if not rec:
        return None
    sel = [f for f in rec.get("faces", []) if f.get("found") and (not people or f.get("name") in people)]
    if not sel:
        return {"n": 0}
    big = [f for f in sel if f["box"][2] - f["box"][0] >= FACE_MIN]
    return {
        "n": len(sel),
        "smile": float(np.mean([f.get("smile", 0) for f in sel])),
        "eyes_closed": any(f.get("eyes_open", 1) < 0.25 for f in big),
        "frontal": float(np.mean([1.0 if f.get("frontal") else 0.0 for f in sel])),
        "blurry": _blur([f["focus"] for f in sel if f.get("focus") is not None]),
    }
