"""Offline place names for photo coordinates (GeoNames cities500 + admin codes, downloaded once).

For each photo we collect the names of towns within NEAR_KM plus its province (admin2) and region (admin1),
so lyrics that name a town (or a province) can match photos taken in nearby villages.
Nothing about the photos leaves the machine: the gazetteer is a public dump queried locally.
"""
import io
import os
import re
import threading
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from . import config

DATA = config.DATA / "geo"
BASE = "https://download.geonames.org/export/dump/"
NEAR_KM = 12.0
PREFIXES = re.compile(r"^(province of|provincia de|provincia di|province de|landkreis|kreis|regierungsbezirk)\s+", re.I)

_lock = threading.Lock()
_db = None


def _norm_words(text):
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return set(re.findall(r"[a-zñ]{4,}", t))


def _fetch(name):
    DATA.mkdir(parents=True, exist_ok=True)
    f = DATA / name
    if not f.exists():
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "slidesong/0.1"})
        tmp = f.with_suffix(f.suffix + ".part")
        tmp.write_bytes(urllib.request.urlopen(req, timeout=120).read())
        tmp.replace(f)
    return f


def _load():
    global _db
    with _lock:
        if _db is not None:
            return _db
        admin1 = {}
        for line in _fetch("admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
            c = line.split("\t")
            admin1[c[0]] = c[1]
        admin2 = {}
        for line in _fetch("admin2Codes.txt").read_text(encoding="utf-8").splitlines():
            c = line.split("\t")
            admin2[c[0]] = PREFIXES.sub("", c[1])
        lat, lon, names, a1, a2 = [], [], [], [], []
        with zipfile.ZipFile(_fetch("cities500.zip")) as z, z.open("cities500.txt") as fh:
            for line in io.TextIOWrapper(fh, encoding="utf-8"):
                c = line.rstrip("\n").split("\t")
                lat.append(float(c[4]))
                lon.append(float(c[5]))
                names.append(c[1])
                a1.append(admin1.get(f"{c[8]}.{c[10]}", ""))
                a2.append(admin2.get(f"{c[8]}.{c[10]}.{c[11]}", ""))
        order = np.argsort(lat)
        _db = {"lat": np.radians(np.array(lat))[order], "lon": np.radians(np.array(lon))[order],
               "names": [names[i] for i in order], "a1": [a1[i] for i in order], "a2": [a2[i] for i in order]}
        return _db


def place_words(coords):
    """coords: list of (lat, lon) or None. Returns one set of normalized words per photo."""
    out = [set() for _ in coords]
    if not any(coords):
        return out
    db = _load()
    win = np.radians(0.5)  # latitude window (~55 km) to avoid scanning the whole gazetteer
    cache = {}
    for k, c in enumerate(coords):
        if not c or c[0] is None or c[1] is None:
            continue
        key = (round(c[0], 3), round(c[1], 3))
        if key not in cache:
            la, lo = np.radians(c[0]), np.radians(c[1])
            i0, i1 = np.searchsorted(db["lat"], [la - win, la + win])
            if i1 <= i0:
                cache[key] = set()
            else:
                # equirectangular distance is plenty at this scale
                d = 6371.0 * np.hypot(db["lat"][i0:i1] - la, (db["lon"][i0:i1] - lo) * np.cos(la))
                nearest = i0 + int(np.argmin(d))
                words = _norm_words(db["a2"][nearest]) | _norm_words(db["a1"][nearest])
                for j in i0 + np.flatnonzero(d < NEAR_KM):
                    words |= _norm_words(db["names"][j])
                cache[key] = words
        out[k] = cache[key]
    return out
