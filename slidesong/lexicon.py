"""What the lyrics name, per language: months, seasons, things visible in a photo, countries.

The song's language is detected from the lyrics (common words) or set by hand; Whisper, the lyrics model, the
local translator and the CLIP text encoder are told it. The word lists (one module per language in slidesong/languages/) are a fallback and a complement:
when the lyrics model (lyrics_llm.py) is available it reads any language and returns the month, season and the
things a photo would show for each line.

Words are compared normalized: lower case, no accents (see `norm`).
"""

import re
import unicodedata

from .languages import ALL

LANGUAGES = {code: (m.NAME, m.NLLB) for code, m in ALL.items()}  # code -> (name in English, NLLB code)
DEFAULT = "es"  # projects made before languages were detected


def nllb(lang: str | None) -> str:
    return LANGUAGES.get(lang or DEFAULT, LANGUAGES["en"])[1]


def name(lang: str | None) -> str:
    return LANGUAGES.get(lang or "", ("", ""))[0]


def norm(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def words(text: str, min_len: int = 3) -> set[str]:
    return set(re.findall(r"[a-zñßæøœ]{%d,}" % min_len, norm(text)))


def langs(lang: str | None) -> list[str]:
    """The word lists to use: the song's language, or every known one when it is not known."""
    return [lang] if lang in ALL else list(ALL)


# ---------------- detection ----------------
_COMMON_SETS = {code: set(m.COMMON_WORDS.split()) for code, m in ALL.items()}


def detect(text: str) -> str | None:
    """The language of some lyrics, or None when there is too little to tell."""
    toks = re.findall(r"[a-zñßæøœ]+", norm(text))
    if len(toks) < 8:
        return None
    score = {k: sum(1 for t in toks if t in s) for k, s in _COMMON_SETS.items()}
    ranked = sorted(score.values(), reverse=True) + [0]
    best = max(score, key=score.get)
    if ranked[0] < 4 or ranked[0] < ranked[1] * 1.3:
        return None
    return best


# ---------------- months and seasons ----------------
MONTH_WORDS = {code: {w: n + 1 for n, w in enumerate(m.MONTHS.split())} | dict(m.MONTH_ALIASES)
               for code, m in ALL.items()}
MONTH_NAMES = {code: m.MONTH_NAMES.split() for code, m in ALL.items()}  # as written: album captions
_AMBIGUOUS = {code: set(m.AMBIGUOUS_MONTHS) for code, m in ALL.items()}

SEASON_MONTHS = {"summer": (6, 7, 8), "autumn": (9, 10, 11), "winter": (12, 1, 2), "spring": (3, 4, 5),
                 "christmas": (12,)}  # northern hemisphere
SEASONS = {code: m.SEASONS for code, m in ALL.items()}
SEASON_CHIP = {"summer": "☀️ summer", "autumn": "🍂 autumn", "winter": "❄️ winter", "spring": "🌸 spring",
               "christmas": "🎄 christmas"}


def months_named(lyric: str, lang: str | None) -> list[int]:
    """Months a lyric line names, in order."""
    out = []
    raw = re.findall(r"[^\W\d_]+", lyric or "")
    for pos, w in enumerate(raw):
        n = norm(w)
        for lg in langs(lang):
            m = MONTH_WORDS[lg].get(n)
            if m and (n not in _AMBIGUOUS[lg] or (w[0].isupper() and pos > 0)):
                out.append(m)
                break
    return out


def season_named(lyric: str, lang: str | None) -> str | None:
    ws = words(lyric)
    for lg in langs(lang):
        for w in ws:
            if w in SEASONS[lg]:
                return SEASONS[lg][w]
    return None


# ---------------- things a line can name that show in a photo ----------------
# id: (English prompt for CLIP, label shown on the «why» chip, RAM++ tags)
CONCEPTS = {
    "leaves": ("autumn leaves on the ground", "leaves", ("leaf", "autumn", "fall foliage", "foliage")),
    "puddles": ("children jumping in puddles", "puddles", ("puddle", "rain", "wet")),
    "rain": ("rain, wet street, umbrella", "rain", ("rain", "umbrella", "wet", "puddle", "raincoat")),
    "snow": ("snow", "snow", ("snow", "snowman", "winter")),
    "beach": ("children at the beach", "beach", ("beach", "sand", "sea")),
    "pool": ("children in a swimming pool", "pool", ("swimming pool", "pool")),
    "sea": ("the sea and waves", "sea", ("sea", "ocean", "wave", "beach")),
    "birthday": ("birthday cake with candles", "birthday", ("birthday cake", "birthday", "candle", "cake")),
    "presents": ("opening presents", "presents", ("gift", "present")),
    "school": ("children at school", "school", ("school", "classroom", "school uniform", "kindergarten")),
    "backpack": ("a child with a school backpack", "backpack", ("backpack", "schoolbag")),
    "boots": ("a child wearing boots", "boots", ("boot", "rain boot")),
    "bike": ("a child riding a bicycle", "bike", ("bicycle", "bike")),
    "playground": ("a playground with swings and slides", "playground", ("playground", "slide", "swing")),
    "fair": ("an amusement park ride", "fair", ("amusement park", "carnival", "fair", "carousel", "ferris wheel")),
    "costume": ("children in costumes", "costume", ("costume",)),
    "airplane": ("an airplane", "airplane", ("airplane", "aircraft", "airport")),
    "train": ("a train", "train", ("train", "train station")),
    "boat": ("a boat", "boat", ("boat", "ship", "sailboat")),
    "car": ("children in a car", "car", ("car", "car seat")),
    "grandparents": ("grandparents with grandchildren", "grandparents", ("grandparent", "grandmother", "grandfather")),
    "dog": ("a dog", "dog", ("dog",)),
    "cat": ("a cat", "cat", ("cat",)),
    "horse": ("a horse or pony", "horse", ("horse", "pony")),
    "ice cream": ("eating ice cream", "ice cream", ("ice cream",)),
    "castle": ("a castle", "castle", ("castle",)),
    "mountain": ("mountains", "mountain", ("mountain",)),
    "forest": ("a forest with trees", "forest", ("forest", "tree", "woods")),
    "water": ("a lake or a river", "water", ("lake", "river", "water")),
    "camp": ("a summer camp", "camp", ("camp", "tent", "campsite")),
    "wind": ("a windy day, hair blowing in the wind", "wind", ("wind",)),
    "night": ("a photo at night", "night", ("night", "star", "moon")),
    "christmas": ("christmas", "christmas", ("christmas", "christmas tree")),
    "flowers": ("flowers", "flowers", ("flower",)),
    "laughter": ("children laughing", "laughter", ("laugh", "smile")),
}
TRIGGERS = {code: m.CONCEPTS for code, m in ALL.items()}


def concepts_named(lyric: str, lang: str | None) -> list[str]:
    """Concept ids a line names (by its words), in CONCEPTS order."""
    text = norm(lyric)
    ws = set(re.findall(r"[a-zñßæøœ]{2,}", text))
    found = []
    for cid in CONCEPTS:
        for lg in langs(lang):
            for p in TRIGGERS[lg].get(cid, ()):
                if " " in p:
                    hit = p in text
                elif p.endswith("="):
                    hit = p[:-1] in ws or p[:-1] + "s" in ws
                else:
                    hit = any(w == p if len(p) <= 3 else w.startswith(p) for w in ws)
                if hit:
                    found.append(cid)
                    break
            else:
                continue
            break
    return found


def concepts_from_tags(tags) -> list[str]:
    """Concept ids whose RAM++ tags include one of these (the lyrics model's tags for a line, any language)."""
    ts = {t.lower().strip() for t in tags or ()}
    return [cid for cid, (_, _, ram) in CONCEPTS.items() if ts & set(ram)]


# ---------------- places ----------------
COUNTRIES = {code: m.COUNTRIES for code, m in ALL.items()}


def country_words(country: str, lang: str | None) -> str:
    """How lyrics name a country Immich gives in English (the English name always counts too)."""
    return " ".join(COUNTRIES[lg].get(country.lower(), "") for lg in langs(lang))


PLACE_STOP = set().union(*(m.PLACE_STOP for m in ALL.values()))


# ---------------- Suno section tags ----------------
_SECTION_ORDER = ["prechorus", "chorus", "bridge", "intro", "outro", "interlude", "verse"]  # checked in this order


def section_kinds() -> list[tuple[str, tuple[str, ...]]]:
    """(kind, words that name it in any known language), in the order they must be checked."""
    return [(k, tuple(dict.fromkeys(w for m in ALL.values() for w in m.SECTIONS.get(k, ())))) for k in _SECTION_ORDER]
