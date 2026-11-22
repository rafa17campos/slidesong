"""What the ML "sees" in a photo, in human terms (for the photo info panel).

- Faces: Immich's face boxes and person names.
- Place: Immich reverse geocoding plus nearby towns / province from the offline gazetteer.
- Scene tags: the photo's CLIP vector compared with a fixed vocabulary. Each term is calibrated against the
  project's own photos (z-score), so the tags are what makes this photo different, not what all photos share.
- Percentiles of quality and of affinity with the shot's lyric line within the project's photos.
"""
import threading

import numpy as np

from . import geo, immich, lexicon, suggest
from .i18n import tr

# (label shown in the UI, prompt for the multilingual CLIP text encoder)
VOCAB = [
    ("🏖️ beach", "a photo at the beach with sand and sea"), ("🏊 pool", "children in a swimming pool"),
    ("🌊 sea", "the sea and waves"), ("🏞️ lake or river", "a lake or a river"), ("⛰️ mountains", "mountains"),
    ("🌲 forest", "a forest with trees"), ("🌳 park", "a park with grass and trees"),
    ("🛝 playground", "a playground with slides and swings"), ("🎢 rides", "an amusement park ride"),
    ("🎠 fair", "a fair with lights and carousels at night"), ("🦁 zoo or animals", "animals at a zoo or farm"),
    ("🐶 dog", "a dog"), ("🐱 cat", "a cat"), ("🐴 horse", "a horse"),
    ("🎂 birthday", "a birthday party with a cake and candles"), ("🎁 presents", "opening presents"),
    ("🎄 christmas", "christmas tree and decorations"), ("🎃 halloween", "halloween costumes and pumpkins"),
    ("🎭 costume", "children in costumes"), ("🏫 school", "a school classroom"),
    ("🎒 first day of school", "a child with a school backpack"), ("📚 reading", "reading a book"),
    ("🎨 painting", "a child drawing or painting"), ("🧸 playing with toys", "playing with toys on the floor"),
    ("🧱 building blocks", "building blocks and lego"), ("📺 TV or screen", "watching a screen or tablet"),
    ("🍝 eating", "eating a meal at the table"), ("🍦 ice cream", "eating ice cream"),
    ("🍳 cooking", "cooking in the kitchen"), ("🛁 bath", "a child in the bath"), ("😴 sleeping", "a sleeping child"),
    ("👶 baby", "a baby"), ("🤗 hug", "people hugging"), ("😂 laughing", "children laughing"),
    ("😢 crying", "a crying child"), ("🤳 selfie", "a selfie"), ("👨‍👩‍👦 family", "a family portrait"),
    ("👵 grandparents", "grandparents with grandchildren"), ("🚗 car", "inside a car"), ("✈️ airplane", "on an airplane"),
    ("🚆 train", "on a train"), ("🚤 boat", "on a boat"), ("🚲 bike", "riding a bicycle"),
    ("🛴 scooter", "riding a scooter"), ("⚽ football", "playing football"), ("🏀 sports", "playing sports"),
    ("🏛️ city", "a city street with buildings"), ("⛪ monument", "a historic monument or church"),
    ("🏰 castle", "a castle"), ("🏠 at home", "inside a house living room"), ("🛏️ in bed", "on a bed"),
    ("🌅 sunset", "a sunset"), ("🌙 at night", "a photo at night"), ("☀️ sunny day", "a sunny day outdoors"),
    ("🌧️ rain", "rain and wet streets"), ("☔ puddles", "jumping in puddles"), ("❄️ snow", "snow"),
    ("🍂 autumn", "autumn leaves"), ("🌸 flowers", "flowers"), ("🎈 balloons", "balloons"),
    ("🎶 music", "playing music or dancing"), ("🏕️ camping", "a summer camp or camping tents"),
    ("🧗 adventure", "climbing or hiking outdoors"), ("🛒 shopping", "shopping in a store or market"),
    ("🍽️ restaurant", "a restaurant"), ("🎪 show", "a show or performance"),
    ("📄 screenshot or text", "a screenshot or a document with text"), ("🖼️ drawing or illustration", "a cartoon or illustration"),
]

_lock = threading.Lock()
_vocab = None


def _vocab_matrix():
    global _vocab
    with _lock:
        if _vocab is None:
            _vocab = np.stack(list(immich._pool.map(lambda v: immich.text_embedding(v[1], "eng_Latn"), VOCAB)))
        return _vocab


def analyze(asset_id, project=None, slot=None):
    info = immich._get(f"/assets/{asset_id}")
    immich._remember(info)
    exif = info.get("exifInfo") or {}
    out = {
        "id": asset_id, "date": info.get("localDateTime"), "file": info.get("originalFileName"),
        "camera": " ".join(x for x in (exif.get("make"), exif.get("model")) if x) or None,
        "size": [info.get("width"), info.get("height")],
        "favorite": bool(info.get("isFavorite")),
        "place": [x for x in (exif.get("city"), exif.get("state"), exif.get("country")) if x],
        "latlon": [exif.get("latitude"), exif.get("longitude")] if exif.get("latitude") is not None else None,
    }
    # faces with names (boxes relative 0..1)
    faces = []
    for f in immich._get("/faces", id=asset_id):
        w, h = f.get("imageWidth"), f.get("imageHeight")
        if w and h:
            faces.append({"name": (f.get("person") or {}).get("name") or "",
                          "box": [f["boundingBoxX1"] / w, f["boundingBoxY1"] / h,
                                  f["boundingBoxX2"] / w, f["boundingBoxY2"] / h]})
    out["faces"] = faces
    near = geo.place_words([out["latlon"]])[0] if out["latlon"] else set()
    out["nearby"] = sorted(near - suggest.PLACE_STOP)[:30]

    from . import scores
    q = scores.get([asset_id]).get(asset_id)
    if q:
        out["ram_tags"] = q.get("tags")
        out["sensitive_tags"] = sorted(t for t in (q.get("tags") or []) if t in suggest.SENSITIVE)
        out["scores"] = {"aesthetic": q.get("aesthetic"),
                         "faces": [{"name": f.get("name"), "smile": f.get("smile"), "eyes_open": f.get("eyes_open"),
                                    "frontal": f.get("frontal"), "focus": f.get("focus")}
                                   for f in q.get("faces", []) if f.get("found")]}
    vec = immich.vectors([asset_id])
    if vec is None or not vec[0].any():
        out["vector"] = None
        return out
    v = vec[0]
    out["vector"] = True

    # reference set to calibrate against: the project's photos (cached), else this photo alone
    ref = None
    if project is not None:
        people = project.get("people") or []
        _, _, _, ref = immich.candidates(people, project.get("date_from"), project.get("date_to"))
    V = _vocab_matrix()
    sims = V @ v
    if ref is not None and len(ref) > 50:
        rs = ref @ V.T
        z = (sims - rs.mean(0)) / (rs.std(0) + 1e-9)
    else:
        z = (sims - sims.mean()) / (sims.std() + 1e-9)
    order = np.argsort(-z)
    out["tags"] = [{"label": tr(VOCAB[j][0]), "z": round(float(z[j]), 2)} for j in order[:12] if z[j] > 0.5]

    if ref is not None and len(ref) > 50:
        def pct(ref_scores, x):
            return int(round(100 * float((ref_scores < x).mean())))
        if slot is not None and project and 0 <= slot < len(project["slots"]):
            lyric = project["slots"][slot].get("lyric")
            if lyric:
                ai = suggest._line_ai(project["slots"][slot], project.get("lines"))
                text, lang = ((ai["visual"], "eng_Latn") if ai and ai.get("visual")
                              else (lyric, lexicon.nllb(suggest.lyrics_language(project))))
                le = immich.text_embedding(text, lang)
                out["lyric"] = lyric
                out["lyric_pct"] = pct(ref @ le, float(v @ le))
                if ai:
                    out["lyric_ai"] = {k: ai.get(k) for k in ("english", "visual", "tags", "source")}
        out["ref_count"] = len(ref)
    return out


def warm_up():
    """Embed the vocabulary in the background at startup so the first info panel opens quickly."""
    threading.Thread(target=lambda: _vocab_matrix(), daemon=True).start()
