"""Undo / redo of the user's edits.

Before an edit, the editable part of the project (settings, shots, exclusions, per-shot choices, captions,
subtitle marks) is saved as a snapshot with a label the page shows ("Deshacer: cambiar la foto del plano 4").
Undo puts the last snapshot back and keeps the current state for redo. Edits in a row on the same control
(a slider being dragged, a title being typed) collapse into one step. A new song or a new analysis clears the
history: older shots no longer fit the song's timing.

Stored next to the project as history.json (at most MAX steps).
"""
import copy
import json
import time
from pathlib import Path

MAX = 50
MERGE_S = 8.0  # edits on the same control closer than this become one undo step

SETTINGS = ("title", "title_overlay", "people", "date_from", "date_to", "theme", "pace", "lyrics", "album_id",
            "order", "videos", "flex_days", "learned", "shirtless", "subtitles", "motion", "avoid", "tuning", "lyrics_lang")
STATE = SETTINGS + ("slots", "excluded", "shot_overrides", "pair_overrides", "transition_overrides", "move",
                    "captions")
_MISSING = "__missing__"


def snapshot(p: dict) -> dict:
    s = {k: copy.deepcopy(p.get(k, _MISSING)) for k in STATE}
    s["line_subs"] = [l.get("sub") for l in p.get("lines") or []]  # the 💬 marks live on the lyric lines
    return s


def restore(p: dict, s: dict):
    for k in STATE:
        v = s.get(k, _MISSING)
        if v == _MISSING:
            p.pop(k, None)
        else:
            p[k] = copy.deepcopy(v)
    subs = s.get("line_subs") or []
    for line, sub in zip(p.get("lines") or [], subs):
        if sub is None:
            line.pop("sub", None)
        else:
            line["sub"] = sub


def _file(d: Path) -> Path:
    return d / "history.json"


def read(d: Path) -> dict:
    try:
        return json.loads(_file(d).read_text())
    except (OSError, ValueError):
        return {"undo": [], "redo": []}


def write(d: Path, h: dict):
    tmp = d / "history.json.tmp"
    tmp.write_text(json.dumps(h, ensure_ascii=False, default=str))
    tmp.replace(_file(d))


def push(d: Path, label: str, before: dict, key: str | None = None, feedback: int | None = None):
    """Record the state before an edit. `key` names the control, to merge a run of edits on it."""
    h = read(d)
    now = time.time()
    last = h["undo"][-1] if h["undo"] else None
    if not (key and last and last.get("key") == key and now - last.get("ts", 0) < MERGE_S):
        h["undo"].append({"label": label, "key": key, "ts": now, "state": before, "feedback": feedback})
        h["undo"] = h["undo"][-MAX:]
    else:
        last["ts"] = now  # same control, still moving: keep the state from before the first edit
    h["redo"] = []
    write(d, h)


def summary(d: Path) -> dict:
    h = read(d)
    return {"undo": h["undo"][-1]["label"] if h["undo"] else None,
            "redo": h["redo"][-1]["label"] if h["redo"] else None}


def step(d: Path, p: dict, direction: str):
    """Undo or redo one step on the project dict (in place). Returns the step's entry, or None."""
    h = read(d)
    src, dst = (h["undo"], h["redo"]) if direction == "undo" else (h["redo"], h["undo"])
    if not src:
        return None
    entry = src.pop()
    dst.append({**entry, "state": snapshot(p), "ts": 0})  # ts 0: never merged with the next edit
    restore(p, entry["state"])
    write(d, h)
    return entry


def clear(d: Path):
    _file(d).unlink(missing_ok=True)
