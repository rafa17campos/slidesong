"""Optional: photo insights (RAM++ tags and quality scores) from another app that keeps them for the whole
library, so they are computed once (e.g. a photo library service that drives the same GPU worker).

Off unless SLIDESONG_INSIGHTS_URL and SLIDESONG_INSIGHTS_TOKEN are set. Slidesong stays independent: whatever it gets is kept in its own scores.sqlite,
the photos it lacks go the usual way (its own worker), and any failure (network, 4xx, 5xx, bad JSON, more than 2 s)
just means the usual way, with at most one warning a minute in the log.

Contract (the other app):
  POST {url}/api/gallery/insights/lookup  {"assetIds": [...]}  (it always queues the photos it lacks)
    -> {"items": {"<id>": {"record": {...worker record, with "tags"...}, "scorerVersion": 2, "scorerName"?: "...",
                           "updatedAt": "..."}},
        "missing": ["<id>", ...], "queued": n}
  GET  {url}/api/gallery/insights/status  -> {"workerOnline": bool, "queued": n, "processing": n}
"""
import time

import httpx

from . import config, scores

URL = (config.env("INSIGHTS_URL", "") or "").rstrip("/")
TOKEN = config.env("INSIGHTS_TOKEN", "") or ""
BATCH = 3000
TIMEOUT = 2.0  # it is asked before every suggestion: never wait long for it
_warned = [0.0]


def _warn(what):
    if time.time() - _warned[0] >= 60:
        _warned[0] = time.time()
        print(f"photo insights from {URL} unavailable ({what}); using this app's own analysis")


def configured() -> bool:
    return bool(URL and TOKEN)


def _h():
    return {"Authorization": f"Bearer {TOKEN}"}


def status() -> dict | None:
    """The other app's queue and worker, or None when it does not answer."""
    if not configured():
        return None
    try:
        r = httpx.get(f"{URL}/api/gallery/insights/status", headers=_h(), timeout=TIMEOUT)
        if r.status_code != 200:
            _warn(f"status {r.status_code}")
            return None
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        _warn(type(e).__name__)
        return None


def pull(asset_ids) -> int | None:
    """Copy what the other app has for these photos into scores.sqlite (records of the current scorer version, with
    their tags); the other app queues the rest. Returns how many it still lacks, or None when it does not
    answer."""
    if not configured():
        return None
    missing = 0
    have = scores.get(asset_ids)
    todo = [a for a in asset_ids if "tags" not in (have.get(a) or {})]
    for k in range(0, len(todo), BATCH):
        chunk = todo[k:k + BATCH]
        try:
            r = httpx.post(f"{URL}/api/gallery/insights/lookup", headers=_h(), timeout=TIMEOUT,
                           json={"assetIds": chunk})
            if r.status_code != 200:
                _warn(f"status {r.status_code}")
                return None
            body = r.json()
            items = body.get("items") or {}
            if not isinstance(items, dict):
                raise ValueError("items")
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            _warn(type(e).__name__)
            return None
        recs = [{**it["record"], "id": aid} for aid, it in items.items()
                if isinstance(it, dict) and isinstance(it.get("record"), dict)
                and it.get("scorerVersion") == scores.active().get("version")
                and it.get("scorerName", scores.active().get("name")) == scores.active().get("name")
                and "tags" in it["record"]]
        scores.put(recs)
        missing += len(chunk) - len(recs)
    return missing
