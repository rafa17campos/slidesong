"""Learn the suggestion weights from the user's corrections in the review.

Every correction becomes pairwise preferences inside one shot ("for this line, photo A over photo B"):
  - "Cambiar" to X: X over the photo it replaced (weight 1) and over the other options shown (weight 0.2 each).
  - "No usar" on X: the first options shown over X (weight 1/3 each).
  - Bootstrap: photos the user pinned in a project, over the first alternatives of that shot.
  - Pinned: pinning a suggested photo with 📌 makes it a clear agreement (over the first alternatives, 0.5 each).
  - Accepted: when a final video is rendered, shots the user left alone count as small agreements (their photo
    over the first alternatives, weight 0.1 each). Without them only the app's mistakes would be recorded and
    the defaults would always look wrong.
The weights are fitted with a pairwise logistic loss, starting from and pulled towards the hand-tuned defaults,
so a handful of corrections cannot send them far. New weights are only saved if, on corrections held out from
the fit, they agree with the user more often than the defaults (k-fold cross-validation).
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import immich, scores, suggest
from . import config

DATA = config.DATA
EVENTS = DATA / "feedback.jsonl"
STATUS = DATA / "learning.json"
MIN_PAIRS = 15     # below this, keep the defaults
MIN_EVENTS = 20    # ... and below this many real corrections too
FLOOR, CAP = 0.25, 3.0  # learned weights keep the default's sign and stay within 1/4 .. 3x of it
REG = 2.0          # pull towards the default weights (higher = more conservative)
MIN_GAIN = 0.05    # learned weights must agree at least 5 points more than the defaults on held-out pairs
                   # (2026-11-19: 36 corrections gave 47.5 % -> 51 %, noise; the weights it wanted undid the
                   # "named person" and "line tags" fixes)

_lock = threading.Lock()


# ---------------- logging ----------------
def _cue_snapshot(project, i):
    try:
        names = [p["name"] for p in immich.people(1000)]
    except Exception:  # Immich down: the correction is still worth keeping, with the project's people only
        names = list(project.get("people") or [])
    cue = suggest.slot_cues(project["slots"], names, project.get("people") or [], project.get("lines"),
                            suggest.lyrics_language(project))[i]
    return {**cue, "words": sorted(cue["words"])}


def _context(project):
    return {**{k: project.get(k) for k in ("people", "date_from", "date_to", "theme", "album_id", "videos", "language")},
            "lyrics_lang": suggest.lyrics_language(project)}


def log_accepted(project):
    """Final render: the shots the user did not correct count as small agreements, once per shot and photo
    (every final render used to log them all again, so the same agreement weighed many times)."""
    if project.get("teaches") is False:
        return
    evs = events()
    fam = project.get("lineage") or project["id"]  # a version and its original count as one project here
    dismissed = _dismissed()
    corrected = {(_fam(e), e["slot"]) for e in evs if e["action"] in ("set", "reject")}
    accepted = {(_fam(e), e["slot"], e.get("new")) for e in evs if e["action"] == "accept"}
    for i, s in enumerate(project.get("slots", [])):
        if (s.get("asset") and not s.get("locked") and (fam, i) not in corrected
                and (fam, i, s["asset"]) not in accepted and (fam, i, s["asset"]) not in dismissed):
            log(project, i, "accept", new=s["asset"], shown=[a for a in s.get("alts", [])[:3] if a != s["asset"]],
                source="final")


def log(project, i, action, new=None, old=None, shown=(), source=None):
    """Append one correction (with the context needed to rebuild the shot later)."""
    if project.get("teaches") is False:  # the user took this project out of the learning
        return
    ev = {"ts": now(), "project": project["id"], "lineage": project.get("lineage") or project["id"], "slot": i,
          "action": action, "new": new, "old": old, "shown": [a for a in shown if a][:12], "source": source,
          "cue": _cue_snapshot(project, i), "ctx": _context(project)}
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _fam(e):
    """The project family of an event: versions of one project share it (older events: just the project)."""
    return e.get("lineage") or e["project"]


def _dismissed():
    """(family, slot, photo) of corrections the user removed: pinned photos and final renders don't bring them back."""
    return {tuple(x) for x in suggest.tuning()["dismissed"]}


def remove(ts, project):
    """Remove one event (the «Learning» page); returns it, or None if it is not there."""
    with _lock:
        evs = events()
        gone = next((e for e in evs if e.get("ts") == ts and e.get("project") == project), None)
        if not gone:
            return None
        tmp = EVENTS.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in evs if e is not gone),
                       encoding="utf-8")
        tmp.replace(EVENTS)
    if gone.get("new"):
        t = suggest.tuning()
        key = [_fam(gone), gone["slot"], gone["new"]]
        if key not in t["dismissed"]:
            t["dismissed"].append(key)
            suggest.save_tuning(t)
    return gone


def reset(projects, only=None):
    """Start from scratch: forget every event (only=None) or one project's. The log as it was is kept aside
    (feedback.jsonl.reset-<time>), and the photos pinned now are marked as removed, so the next fit does not
    import them again as corrections. A whole reset also drops the learned weights. Returns how many events
    were forgotten."""
    with _lock:
        evs = events()
        keep = [e for e in evs if only is not None and e.get("project") != only]
        if len(keep) != len(evs):
            EVENTS.with_name(f"feedback.jsonl.reset-{datetime.now():%Y%m%d-%H%M%S}").write_bytes(EVENTS.read_bytes())
            tmp = EVENTS.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), encoding="utf-8")
            tmp.replace(EVENTS)
    t = suggest.tuning()
    keys = {tuple(x) for x in t["dismissed"]}
    for p in projects:
        if only is not None and p["id"] != only:
            continue
        fam = p.get("lineage") or p["id"]
        keys |= {(fam, i, s["asset"]) for i, s in enumerate(p.get("slots") or []) if s.get("locked") and s.get("asset")}
    t["dismissed"] = [list(k) for k in sorted(keys)]
    suggest.save_tuning(t)
    if only is None:
        suggest.WEIGHTS_FILE.unlink(missing_ok=True)
        STATUS.unlink(missing_ok=True)
    return len(evs) - len(keep)


def now():
    """Event time, fine enough to order the events of one edit after the undo snapshot taken just before it."""
    return datetime.now().isoformat(timespec="microseconds")


def events():
    """The logged events; a damaged line (a crash or a full disk mid-write) is skipped, not fatal."""
    if not EVENTS.exists():
        return []
    out = []
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def forget(project_id, since):
    """Undo: drop this project's corrections logged since the undone edit (`since` is the time taken just
    before it; an int is a position in the log, from older undo histories)."""
    with _lock:
        evs = events()
        if isinstance(since, int):
            keep = [e for n, e in enumerate(evs) if n < since or e.get("project") != project_id]
        else:
            keep = [e for e in evs if e.get("project") != project_id or str(e.get("ts", "")) < since]
        if len(keep) != len(evs):
            tmp = EVENTS.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), encoding="utf-8")
            tmp.replace(EVENTS)
        return len(evs) - len(keep)


def bootstrap(projects):
    """Pinned photos of existing projects become corrections (once per project/shot/photo). A photo the user
    put by hand is pinned too and was already logged when it was put: it is not logged again."""
    seen = {(_fam(e), e["slot"], e.get("new")) for e in events() if e["action"] == "set"} | _dismissed()
    added = 0
    for p in projects:
        if p.get("teaches") is False:
            continue
        fam = p.get("lineage") or p["id"]
        for i, s in enumerate(p.get("slots", [])):
            if s.get("locked") and s.get("asset") and (fam, i, s["asset"]) not in seen:
                seen.add((fam, i, s["asset"]))
                alts = [a for a in s.get("alts", []) if a != s["asset"]]
                if alts:
                    log(p, i, "set", new=s["asset"], old=alts[0], shown=alts[1:6], source="pinned")
                    added += 1
    return added


# ---------------- pairs and features ----------------
def pairs_from(evs):
    out = []  # (event, winner, loser, weight)
    for e in evs:
        if e["action"] == "accept" and e.get("new"):
            wt = 0.5 if e.get("source") == "pin" else 0.1  # pinned on purpose > merely left alone
            out += [(e, e["new"], a, wt) for a in e.get("shown", [])[:3] if a != e["new"]]
            continue
        if e["action"] == "set" and e.get("new"):
            if e.get("old") and e["old"] != e["new"]:
                out.append((e, e["new"], e["old"], 1.0))
            out += [(e, e["new"], a, 0.2) for a in e.get("shown", [])[:5] if a not in (e["new"], e.get("old"))]
        elif e["action"] == "reject" and e.get("old"):
            out += [(e, a, e["old"], 1 / 3) for a in e.get("shown", [])[:3] if a != e["old"]]
    return out


def _cue_back(c):
    """A cue as stored in feedback.jsonl back to the shape suggest uses (JSON turned sets/tuples into lists)."""
    return {**c, "words": set(c.get("words") or ()), "concepts": [tuple(x) for x in c.get("concepts") or ()]}


def featurize(pairs, progress=None):
    """Feature differences (winner - loser) for every pair, computed in the context of its project/shot."""
    groups = {}
    for pr in pairs:
        key = json.dumps(pr[0]["ctx"], sort_keys=True)
        groups.setdefault(key, []).append(pr)
    X, w, groups_out = [], [], []
    for n, (key, prs) in enumerate(groups.items()):
        ctx = json.loads(key)
        people = ctx.get("people") or []
        videos = (ctx.get("videos") or "some") != "off"
        ids, dates, favs, emb = immich.candidates(people, ctx.get("date_from"), ctx.get("date_to"), videos=videos)
        involved = {x for _, a, b, _ in prs for x in (a, b)}
        extra = sorted(involved - set(ids))
        ids, dates, favs, emb = suggest._merge((ids, dates, favs, emb), immich.assets_by_ids(extra))
        if not ids or emb is None:
            continue
        pool = suggest.Pool(ids, dates, favs, emb, people, ctx.get("theme"),
                            immich.album_assets(ctx.get("album_id")) if ctx.get("album_id") else (),
                            ctx.get("videos") or "some", weights=suggest.DEFAULT_WEIGHTS,
                            lang=ctx.get("lyrics_lang"), text_lang=ctx.get("language"))
        idx = {a: k for k, a in enumerate(ids)}
        used = sorted(idx[x] for x in involved if x in idx)
        pool.load_faces(used)
        pool.apply_scores(scores.get(ids))
        everyone = np.arange(len(ids))
        cache = {}
        for e, a, b, wt in prs:
            if a not in idx or b not in idx:
                continue
            # all copies of one preference (same shot, same winner) stay in the same fold
            ev_id = f'{_fam(e)}|{e["slot"]}|{a}' 
            cue = _cue_back(e["cue"])
            ck = json.dumps(e["cue"], sort_keys=True, default=list)
            if ck not in cache:  # signals are relative to the whole pool (z-scores), so score everyone once per cue
                cache[ck] = pool.features(cue, everyone)
            F, _, hard = cache[ck]
            if hard[idx[a]] or hard[idx[b]]:
                continue
            X.append(F[idx[a]] - F[idx[b]])
            w.append(wt)
            groups_out.append(ev_id)
        if progress:
            progress((n + 1) / len(groups))
    return np.array(X), np.array(w), np.array(groups_out)


# ---------------- fitting ----------------
def _w0():
    return np.array([suggest.DEFAULT_WEIGHTS[k] for k in suggest.FEATURES])


def fit(X, wt, steps=3000, lr=0.05):
    """Pairwise logistic regression pulled towards the default weights."""
    w0 = _w0()
    scale = np.maximum(np.abs(w0), 0.5)  # relative pull: big default weights may move more
    w = w0.copy()
    for _ in range(steps):
        m = X @ w
        p = 1 / (1 + np.exp(np.clip(m, -30, 30)))  # = sigmoid(-m)
        grad = -(X * (wt * p)[:, None]).sum(0) / wt.sum() + REG * (w - w0) / scale ** 2 / len(wt) ** 0.5
        w -= lr * grad
        w = _bounded(w, w0)
    return w


def _bounded(w, w0):
    """Same sign as the default and within FLOOR..CAP times its size (zero defaults stay put)."""
    lo = np.where(w0 >= 0, FLOOR * w0, CAP * w0)
    hi = np.where(w0 >= 0, CAP * w0, FLOOR * w0)
    return np.clip(w, lo, hi)


def agreement(X, wt, w):
    """Weighted share of pairs where the weights prefer the user's choice."""
    return float((wt * (X @ w > 0)).sum() / wt.sum()) if len(wt) else 0.0


def cross_val(X, wt, groups, k=5, seed=0):
    """k-fold by correction (all pairs of one correction stay in the same fold), so the score is honest."""
    rng = np.random.default_rng(seed)
    uniq = rng.permutation(np.unique(groups))
    a0, a1 = [], []
    for part in np.array_split(uniq, min(k, len(uniq))):
        f = np.flatnonzero(np.isin(groups, part))
        train = np.setdiff1d(np.arange(len(wt)), f)
        if not len(train) or not len(f):
            continue
        w = fit(X[train], wt[train])
        a0.append(agreement(X[f], wt[f], _w0()))
        a1.append(agreement(X[f], wt[f], w))
    return float(np.mean(a0)), float(np.mean(a1))


def learn(projects=(), progress=None):
    """Bootstrap from pinned photos, fit and save the weights if they generalise better. Returns the status."""
    t = time.time()
    if projects:
        bootstrap(projects)
    evs = events()
    prs = pairs_from(evs)
    status = {"updated": datetime.now().isoformat(timespec="seconds"), "events": len(evs), "pairs": len(prs),
              "applied": False}
    corrections = sum(1 for e in evs if e["action"] in ("set", "reject"))
    status["corrections"] = corrections
    if len(prs) >= MIN_PAIRS and corrections >= MIN_EVENTS:
        X, wt, groups = featurize(prs, progress)
        status["pairs"] = int(len(wt))
        if len(wt) >= MIN_PAIRS:
            acc0, acc1 = cross_val(X, wt, groups)
            status.update(acc_default=round(acc0, 3), acc_learned=round(acc1, 3))
            # what it would use, kept even when not applied (the «Learning» page shows it)
            learned = {k: round(float(v), 4) for k, v in zip(suggest.FEATURES, fit(X, wt))}
            status["weights"] = learned
            if acc1 >= acc0 + MIN_GAIN:
                suggest.WEIGHTS_FILE.write_text(json.dumps({"weights": learned, "status": status}, indent=1))
                status["applied"] = True
            elif suggest.WEIGHTS_FILE.exists():
                suggest.WEIGHTS_FILE.unlink()  # learned weights no longer beat the defaults
    status["seconds"] = round(time.time() - t, 1)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1))
    return status


def corrections():
    return sum(1 for e in events() if e["action"] in ("set", "reject"))


def dedupe():
    """One-off cleanup of a log written before log_accepted/bootstrap stopped repeating themselves: keeps the
    first final-render agreement per project/shot/photo and drops pinned-photo imports that repeat a set."""
    with _lock:
        evs = events()
        sets, accepted, keep = set(), set(), []
        for e in evs:
            k = (e.get("project"), e.get("slot"), e.get("new"))
            if e["action"] == "accept" and e.get("source") == "final":
                if k in accepted:
                    continue
                accepted.add(k)
            elif e["action"] == "set":
                if e.get("source") in ("pinned", "fijada") and k in sets:  # "fijada": older logs
                    continue
                sets.add(k)
            keep.append(e)
        if len(keep) != len(evs):
            tmp = EVENTS.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), encoding="utf-8")
            tmp.replace(EVENTS)
        return len(evs) - len(keep)


def status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {"events": len(events()), "pairs": 0, "applied": False}
