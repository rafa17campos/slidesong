"""Immich access.

- Almost everything goes through the public API (read-only API key): people, searches, faces, thumbnails, originals.
- Optional: CLIP vectors from `smart_search` through a Postgres role that can ONLY read that table
  (IMMICH_VEC_DSN). Vectors are only requested for assets the API already returned (Immich permissions hold).
  If it is not configured or fails, the app works without vectors (simpler suggestions).
- Text embeddings come from Immich's ML service (to compare against the vectors).
"""
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import numpy as np
from . import config
from . import i18n

IMMICH_URL = os.environ.get("IMMICH_URL", "http://127.0.0.1:2283").rstrip("/")
API_KEY = os.environ.get("IMMICH_API_KEY", "")
VEC_DSN = os.environ.get("IMMICH_VEC_DSN", "")
ML_URLS = [u for u in os.environ.get("IMMICH_ML_URLS", "http://immich-machine-learning:3003").split(",") if u]
IMAGES_URL = config.env("IMAGES_URL", "").rstrip("/")
CLIP_MODEL = os.environ.get("IMMICH_CLIP_MODEL", "nllb-clip-large-siglip__mrl")

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_client = httpx.Client(base_url=IMMICH_URL + "/api", headers={"x-api-key": API_KEY}, timeout=60,
                       limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
_pool = ThreadPoolExecutor(max_workers=12)


def _get(path, **params):
    r = _client.get(path, params=params)
    r.raise_for_status()
    return r.json()


def _post(path, body):
    r = _client.post(path, json=body)
    r.raise_for_status()
    return r.json()


def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


# ---------- metadata cache (filled by searches) ----------
_info: dict[str, dict] = {}
_info_lock = threading.Lock()


def old_camera(aid):
    """Keep a known camera make when an item without exifInfo (e.g. from a search without exif) refreshes it."""
    return _info.get(aid, {}).get("camera", "?")


def _remember(item):
    with _info_lock:
        old_people = _info.get(item["id"], {}).get("people", set())
        _info[item["id"]] = {
            "people": set(old_people),
            "date": item.get("localDateTime"), "fav": bool(item.get("isFavorite")),
            "name": item.get("originalFileName"), "w": item.get("width"), "h": item.get("height"),
            "duplicateId": item.get("duplicateId"), "mime": item.get("originalMimeType"),
            "place": [x for x in ((item.get("exifInfo") or {}).get(k) for k in ("city", "state", "country")) if x],
            "latlon": ((item.get("exifInfo") or {}).get("latitude"), (item.get("exifInfo") or {}).get("longitude")),
            "camera": (item.get("exifInfo") or {}).get("make") if item.get("exifInfo") else old_camera(item["id"]),
            "type": item.get("type"), "duration": parse_duration(item.get("duration")),
        }


def parse_duration(d):
    """Immich video duration (milliseconds or 'H:MM:SS.ffffff') in seconds; 0 for photos."""
    if d in (None, "", 0):
        return 0.0
    if isinstance(d, (int, float)):
        return float(d) / 1000.0
    try:
        h, m, sec = str(d).split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)
    except ValueError:
        return 0.0


# ---------- people ----------
_people_cache = {"t": 0, "data": []}
_cand_cache: dict = {}  # (people, from, to) -> (time, result); the swap dialog reuses it


def people(limit=80):
    if time.time() - _people_cache["t"] > 600:
        out, page = [], 1
        while True:
            d = _get("/people", page=page, size=500, withHidden="false")
            out += [p for p in d.get("people", []) if p.get("name")]
            if not d.get("hasNextPage"):
                break
            page += 1
        _people_cache.update(t=time.time(), data=out)
    seen, res = set(), []
    for p in _people_cache["data"]:
        if p["name"] not in seen:
            seen.add(p["name"])
            res.append({"name": p["name"], "count": None})
    return res[:limit]


def person_ids(names):
    people()
    names = set(names or [])
    return [p["id"] for p in _people_cache["data"] if p["name"] in names]


# ---------- searches ----------
def _date_filters(date_from, date_to):
    f = {}
    if date_from:
        f["takenAfter"] = f"{date_from}T00:00:00.000Z"
    if date_to:
        f["takenBefore"] = f"{date_to}T23:59:59.999Z"
    return f


def _metadata_all(body):
    items, page = [], 1
    while page:
        d = _post("/search/metadata", {**body, "page": page, "size": 1000})["assets"]
        items += d["items"]
        page = int(d["nextPage"]) if d.get("nextPage") else None
    return items


def candidates(people_names, date_from=None, date_to=None, videos=False):
    """Photos (and videos if asked) of any of the people within the date range.
    Returns ids, dates, favorites and vectors (or None)."""
    base = {"visibility": "timeline", "withExif": True, **_date_filters(date_from, date_to)}
    types = ["IMAGE", "VIDEO"] if videos else ["IMAGE"]
    pids = person_ids(people_names)
    if people_names and not pids:
        return [], [], np.zeros(0, bool), None
    key = (tuple(sorted(people_names or [])), date_from, date_to, videos)
    hit = _cand_cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    name_of = {p["id"]: p["name"] for p in _people_cache["data"]}
    groups = [[p] for p in pids] or [None]
    seen, members = {}, {}
    for g, typ in [(g, t) for g in groups for t in types]:
        for it in _metadata_all({**base, "type": typ, **({"personIds": g} if g else {})}):
            if it["id"] not in seen:
                seen[it["id"]] = it
                _remember(it)
            if g:
                members.setdefault(it["id"], set()).add(name_of.get(g[0]))
    for a, names in members.items():
        _info[a].setdefault("people", set()).update(names)
    ids = list(seen)
    dates = [parse_date(seen[a]["localDateTime"]) for a in ids]
    favs = np.array([bool(seen[a].get("isFavorite")) for a in ids])
    result = (ids, dates, favs, vectors(ids))
    # each entry holds the pool's CLIP vectors (tens of MB for big pools): keep only a few, fresh ones
    now = time.time()
    for k in [k for k, (t, _) in _cand_cache.items() if now - t >= 300]:
        _cand_cache.pop(k, None)
    while len(_cand_cache) >= 4:
        _cand_cache.pop(min(_cand_cache, key=lambda k: _cand_cache[k][0]), None)
    _cand_cache[key] = (now, result)
    return result


def albums():
    return [{"id": a["id"], "name": a["albumName"], "count": a.get("assetCount", 0)}
            for a in sorted(_get("/albums"), key=lambda a: a.get("albumName", "").lower())]


def album_assets(album_id):
    """Ids of the photos in an Immich album (their metadata is remembered for scoring)."""
    if not album_id or not UUID_RE.match(album_id):
        return []
    d = _get(f"/albums/{album_id}")
    out = []
    for it in d.get("assets", []):
        if it.get("type") == "IMAGE" and not it.get("isTrashed"):
            _remember(it)
            out.append(it["id"])
    return out


def assets_by_ids(asset_ids):
    """Same shape as candidates() for an explicit list of photos (album, pasted links)."""
    ids = [a for a in asset_ids if _info_one(a)]
    dates = [parse_date(_info[a]["date"]) for a in ids]
    favs = np.array([bool(_info[a]["fav"]) for a in ids])
    return ids, dates, favs, vectors(ids)


def search(text, people_names=None, date_from=None, date_to=None, limit=60, exclude=(), videos=False):
    base = {"query": text, "language": i18n.lang(), "visibility": "timeline", **({} if videos else {"type": "IMAGE"}),
            "size": limit, **_date_filters(date_from, date_to)}
    pids = person_ids(people_names) if people_names else []
    lists = []
    for g in ([[p] for p in pids] or [None]):
        items = _post("/search/smart", {**base, **({"personIds": g} if g else {})})["assets"]["items"]
        for it in items:
            _remember(it)
        lists.append([it["id"] for it in items])
    # interleave the results for each person (any of them)
    out, seen, ex = [], set(), set(exclude)
    for k in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if k < len(l) and l[k] not in seen and l[k] not in ex:
                seen.add(l[k])
                out.append(l[k])
    return out[:limit]


# ---------- faces and metadata ----------
_faces_cache: dict[str, list] = {}


def _faces_one(aid):
    if aid in _faces_cache:
        return _faces_cache[aid]
    try:
        fl = _get("/faces", id=aid)
    except httpx.HTTPError:
        return []  # Immich hiccup: no faces this time, but do not remember "none" (it would stick for good)
    out = []
    for f in fl:
        w, h = f.get("imageWidth"), f.get("imageHeight")
        if not w or not h:
            continue
        out.append({"box": [f["boundingBoxX1"] / w, f["boundingBoxY1"] / h, f["boundingBoxX2"] / w, f["boundingBoxY2"] / h],
                    "person": (f.get("person") or {}).get("name")})
    _faces_cache[aid] = out
    return out


def faces(asset_ids, people_names=None):
    sel = set(people_names or [])
    res = dict(zip(asset_ids, _pool.map(_faces_one, asset_ids)))
    return {a: [{"box": f["box"], "selected": f["person"] in sel} for f in fl] for a, fl in res.items()}


def _info_one(aid):
    if aid not in _info:
        try:
            _remember(_get(f"/assets/{aid}"))
        except httpx.HTTPError:
            return None
    return _info.get(aid)


def asset_meta(asset_ids, people_names=None):
    asset_ids = [a for a in asset_ids if UUID_RE.match(a)]
    infos = dict(zip(asset_ids, _pool.map(_info_one, asset_ids)))
    fc = faces([a for a in asset_ids if infos.get(a)], people_names)
    out = {}
    for a, inf in infos.items():
        if inf:
            out[a] = {"id": a, "date": inf["date"], "fav": inf["fav"], "name": inf["name"],
                      "w": inf["w"], "h": inf["h"], "faces": fc.get(a, []),
                      "video": inf.get("type") == "VIDEO", "duration": inf.get("duration") or 0.0}
    return out


# ---------- files ----------
def fetch(asset_id: str, kind: str) -> tuple[bytes, str] | None:
    """kind: thumbnail | preview | original | video (playable MP4 of a video asset)"""
    if not UUID_RE.match(asset_id):
        return None
    if IMAGES_URL:  # GPU worker: go through the Slidesong app so the Immich API key never leaves its host
        r = httpx.get(f"{IMAGES_URL}/api/assets/{asset_id}/{kind}", timeout=120,
                      headers={"Authorization": f"Bearer {os.environ.get('WORKER_TOKEN', '')}"})
        return (r.content, r.headers.get("content-type", "")) if r.status_code == 200 else None
    path = {"original": f"/assets/{asset_id}/original", "video": f"/assets/{asset_id}/video/playback"}.get(
        kind, f"/assets/{asset_id}/thumbnail")
    r = _client.get(path, params=None if kind in ("original", "video") else {"size": kind}, timeout=300)
    if r.status_code != 200:
        return None
    return r.content, r.headers.get("content-type", "application/octet-stream")


def video_to_file(asset_id: str, dest) -> bool:
    """Download a video asset's playable MP4 to a local file (streamed, it can be large)."""
    if not UUID_RE.match(asset_id):
        return False
    if IMAGES_URL:
        url, headers, client = (f"{IMAGES_URL}/api/assets/{asset_id}/video",
                                {"Authorization": f"Bearer {os.environ.get('WORKER_TOKEN', '')}"}, httpx)
    else:
        url, headers, client = (f"/assets/{asset_id}/video/playback", {}, _client)
    with client.stream("GET", url, headers=headers, timeout=600) as r:
        if r.status_code not in (200, 206):
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return True


def video_stream(asset_id: str, range_header: str | None):
    """Proxy a video asset with Range support (for the browser's <video>). Returns an open httpx response."""
    req = _client.build_request("GET", f"/assets/{asset_id}/video/playback",
                                headers={"Range": range_header} if range_header else {}, timeout=300)
    return _client.send(req, stream=True)


# ---------- vectors (optional, read-only access to smart_search) ----------
def vectors(asset_ids):
    if not VEC_DSN or not asset_ids:
        return None
    try:
        import psycopg
        with psycopg.connect(VEC_DSN, connect_timeout=5) as c, c.cursor() as cur:
            cur.execute('select "assetId"::text, embedding::text from smart_search where "assetId" = any(%s::uuid[])',
                        (list(asset_ids),))
            got = {a: e for a, e in cur.fetchall()}
    except Exception as e:  # no vectors: the app keeps working
        print("vectors unavailable:", e)
        return None
    dim = len(parse_vec(next(iter(got.values())))) if got else 1152
    emb = np.zeros((len(asset_ids), dim), np.float32)
    for k, a in enumerate(asset_ids):
        if a in got:
            emb[k] = parse_vec(got[a])
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    return emb


def parse_vec(s: str) -> np.ndarray:
    return np.array(s.strip("[]").split(","), dtype=np.float32)


# ---------- ML: text embeddings ----------
_emb_cache: dict = {}
_emb_lock = threading.Lock()


def text_embedding(text: str, lang: str = "spa_Latn") -> np.ndarray:
    key = (text, lang)
    with _emb_lock:
        if key in _emb_cache:
            return _emb_cache[key]
    last = None
    for url in ML_URLS:
        try:
            r = httpx.post(url.rstrip("/") + "/predict", timeout=120, files={
                "entries": (None, json.dumps({"clip": {"textual": {"modelName": CLIP_MODEL, "options": {"language": lang}}}})),
                "text": (None, text)})
            r.raise_for_status()
            raw = r.json()["clip"]
            v = parse_vec(raw) if isinstance(raw, str) else np.asarray(raw, dtype=np.float32)
            v /= np.linalg.norm(v) + 1e-9
            with _emb_lock:
                _emb_cache[key] = v
            return v
        except Exception as e:
            last = e
    raise RuntimeError(f"Immich ML is not responding: {last}")
