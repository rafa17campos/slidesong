"""Photo suggestions per shot.

The song is treated as a story told in chronological order: shots are aligned to the photo timeline with a
monotonic dynamic programme (shot i always gets a later photo than shot i-1) that maximises
    quality + affinity with the lyric line (CLIP) + month/place cues from the lyrics + a weak pacing prior.
That way "En agosto fuimos de acampada" can pull the timeline to August even if June has thousands of photos.

Bursts of near-identical photos are collapsed to their best shot before aligning.
Without vectors (no smart_search access) only quality, cues and the prior are used.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import geo, immich, lexicon, scores
from . import config
from .i18n import MONTHS_EN

JUNK = ("a screenshot, a meme, a cartoon, a document or a picture with text", "eng_Latn")

W_LYRIC = 1.0     # CLIP affinity with the lyric line (z-score)
W_MONTH = 4.0     # line names the photo's month
W_MONTH_CARRY = 1.5  # the next lines keep a fading pull towards the last month named
CARRY_LINES = 6
W_PLACE = 8.0     # line names the photo's town, a nearby town, province, region or country
W_PERSON = 6.0    # line names someone (an Immich person) who is in the photo
W_STRANGER = 8.0  # photo only has people named elsewhere in the song, not the project's people
W_ALBUM = 3.0     # photo is in the project's Immich album (the user's hand-picked tray)
SAME_DAY = 1.8    # consecutive shots from the same day
FLEX_DAYS = 7     # "flexible" order: each shot may swap its photo for one up to a week earlier or later
ALT_DAYS = 10     # "flexible" order: alternatives come from ±10 days around the chosen photo
FLEX_GAIN = 1.0   # "flexible" order: only swap when the other photo is clearly better
W_NOT_PHOTO = 0.0  # PNG without camera EXIF (screenshot / illustration): allowed, only tagged so the user notices
W_PRIOR = 3.0     # pacing prior: penalty per unit of calendar deviation (0..1)
TAG_COMMON = 0.15  # a tag found in more than this share of the project's photos says nothing (boy, child...)
# RAM++ tags that mean "little clothing" -> the warning shown. RAM++ says "swimwear" for kids in swim trunks
# far more often than "shirtless" (149 such photos had only "swimwear"), so all of them count.
SENSITIVE = {"shirtless": "shirtless", "swimwear": "in swimwear", "bikini": "in swimwear", "swim": "in swimwear",
             "sunbathe": "in swimwear", "diaper": "in a diaper", "bath": "in the bath", "belly": "belly showing"}


def sensitive(tags):
    """Warning text for a photo's RAM++ tags, or None."""
    hits = [SENSITIVE[t] for t in SENSITIVE if t in (tags or ())]
    return " / ".join(dict.fromkeys(hits)) or None


SHIRTLESS_PENALTY = {"show": 0.0, "avoid": -4.0, "never": -50.0}  # per project: just flag / avoid / never propose
FACE_LIMIT = 5000  # max photos whose faces get looked up (one API call each)

# months, seasons, things a line names, countries: per language in lexicon.py
W_SEASON = 1.5    # line names a season: photos from its months
W_CONCEPT = 1.5
W_TAG = 2.5       # the photo's RAM++ tags include something the line names
# project setting "videos": bonus for a video clip and the largest share of shots that may be videos
VIDEO_MODES = {"off": (0.0, 0.0), "some": (0.5, 0.15), "many": (1.2, 0.35)}
VIDEO_MARGIN = 1.0  # a clip must be at least this many seconds longer than its shot


W_AVOID = 2.0     # «Avoid»: penalty per standard deviation of likeness above AVOID_FROM
AVOID_FROM = 1.0  # most photos are a little like anything: only the clearly alike are pushed down


def avoid_terms(text):
    """«beach, pool; snow» -> ["playa", "piscina", "nieve"] (at most 8)."""
    return [t.strip() for t in re.split(r"[,;\n]", text or "") if t.strip()][:8]


def _z(x):
    return (x - x.mean()) / (x.std() + 1e-9) if len(x) else x


def _norm_words(text):
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return set(re.findall(r"[a-zñ]{4,}", t))


PLACE_STOP = lexicon.PLACE_STOP


def lyrics_language(project) -> str | None:
    """The language the song is sung in: chosen by hand, else detected from the lyrics (None: not known)."""
    chosen = project.get("lyrics_lang")
    if chosen and chosen != "auto":
        return chosen
    return lexicon.detect(project.get("lyrics") or "\n".join(l.get("text", "") for l in project.get("lines") or []))


def _season(s):
    """A cue's season id ("summer"…); older cues kept the Spanish word ("verano")."""
    return s if s in lexicon.SEASON_MONTHS else lexicon.SEASONS["es"].get(s or "")


def _place_words(place, lang=None):
    words = set()
    for part in place or []:
        words |= _norm_words(part)
        words |= _norm_words(lexicon.country_words(part, lang))
    return words - PLACE_STOP


def _face_bonus(fl, n_people):
    sel = [f["box"] for f in fl if f["selected"]] or [f["box"] for f in fl]
    if not sel:
        return -0.5
    area = max((b[2] - b[0]) * (b[3] - b[1]) for b in sel)
    bonus = float(np.clip(np.log10(area / 0.004), -1.5, 0.6))  # faces under 0.4 % of the image are penalized
    nsel = sum(1 for f in fl if f["selected"])
    return bonus + 0.25 * max(0, min(nsel, n_people) - 1)


def _collapse_bursts(order, dates, emb, base, groups=None):
    """Group time-sorted photos into moments (bursts) and keep the best-scoring one of each.
    If `groups` is a dict, it receives {representative: [members in time order]}."""
    reps, group = [], [order[0]]

    def close_group(g):
        rep = max(g, key=lambda j: base[j])
        reps.append(rep)
        if groups is not None:
            groups[rep] = list(g)
    for k in order[1:]:
        prev = group[-1]
        close = (dates[k] - dates[prev]).total_seconds() < 120
        similar = emb is None or float(emb[k] @ emb[prev]) > 0.80
        if close and similar:
            group.append(k)
        else:
            close_group(group)
            group = [k]
    close_group(group)
    return np.array(reps, dtype=int)


def _refine_flexible(score, path, locked, day, tol_days):
    """Start from the strict timeline (good pacing and variety) and let each shot swap its photo for a better
    one taken up to tol_days before or after, without repeating photos or the neighbours' days."""
    M, N = score.shape
    path = list(path)
    used = set(path)
    day_uses = {}
    for j in path:
        day_uses[day[j]] = day_uses.get(day[j], 0) + 1
    for i in range(M):
        if i in locked:
            continue
        cur = path[i]
        lo, hi = np.searchsorted(day, [day[cur] - tol_days, day[cur] + tol_days + 1])
        cand = np.arange(lo, hi)
        if not len(cand):
            continue
        neigh = {day[path[j]] for j in (i - 1, i + 1) if 0 <= j < M}
        uses = np.array([day_uses.get(d, 0) - (1 if d == day[cur] else 0) for d in day[cand]], dtype=float)
        sc = score[i, cand] - 0.4 * uses - 10.0 * np.isin(day[cand], list(neigh))
        sc[[k for k, c in enumerate(cand) if c in used and c != cur]] = -1e9
        best = int(cand[int(np.argmax(sc))])
        cur_sc = sc[int(np.where(cand == cur)[0][0])] if cur in cand else -1e9
        if best != cur and sc[int(np.where(cand == best)[0][0])] - cur_sc >= FLEX_GAIN:
            used.discard(cur)
            used.add(best)
            day_uses[day[cur]] -= 1
            day_uses[day[best]] = day_uses.get(day[best], 0) + 1
            path[i] = best
    return path


def _align_free(score, locked, day):
    """No chronology: each shot takes its best photo, without reusing photos and spreading days."""
    M, N = score.shape
    used, day_uses, path = set(), {}, [0] * M
    order = sorted(range(M), key=lambda i: -score[i].max())  # most demanding shots pick first
    for i in order:
        if i in locked:
            path[i] = locked[i]
        else:
            penal = np.array([day_uses.get(d, 0) for d in day], dtype=float) * SAME_DAY
            sc = score[i] - penal
            sc[list(used)] = -1e9
            path[i] = int(np.argmax(sc))
        used.add(path[i])
        day_uses[day[path[i]]] = day_uses.get(day[path[i]], 0) + 1
    return path


def _align(score, locked, day):
    """Monotonic alignment. score: (M slots, N photos sorted by date); day: (N,) day number of each photo.
    Shot i must take a later photo than shot i-1; taking another photo of the same day costs SAME_DAY."""
    M, N = score.shape
    if N < M:
        raise RuntimeError(f"There are fewer photos ({N}) than shots ({M}); widen the dates or people")
    NEG = -1e9
    idx = np.arange(N)
    # first index of each photo's day (photos are sorted, so days are contiguous blocks)
    new_day = np.concatenate([[True], day[1:] != day[:-1]])
    day_start = np.maximum.accumulate(np.where(new_day, idx, 0))
    dp = np.full((M, N), NEG)
    back = np.zeros((M, N), dtype=int)
    for i in range(M):
        row = score[i].copy()
        if i in locked:
            keep = row[locked[i]]
            row[:] = NEG
            row[locked[i]] = keep
        if i == 0:
            dp[0] = row
            continue
        prev = dp[i - 1]
        # best over all earlier photos (prefix max) ...
        acc = np.maximum.accumulate(prev)
        acc_pos = np.maximum.accumulate(np.where(prev >= acc, idx, 0))
        # ... and best within the same day, restarting the running max at each new day
        seg = prev.copy()
        seg_pos = idx.copy()
        for k in range(1, N):
            if not new_day[k] and seg[k - 1] > seg[k]:
                seg[k], seg_pos[k] = seg[k - 1], seg_pos[k - 1]
        # predecessor of k: an earlier day (no penalty) or an earlier photo of the same day (penalty)
        before_day = day_start - 1
        other = np.where(before_day >= 0, acc[np.maximum(before_day, 0)], NEG)
        other_pos = acc_pos[np.maximum(before_day, 0)]
        same = np.where(~new_day, np.concatenate([[NEG], seg[:-1]]) - SAME_DAY, NEG)
        same_pos = np.concatenate([[0], seg_pos[:-1]])
        use_same = same > other
        dp[i] = row + np.where(use_same, same, other)
        back[i] = np.where(use_same, same_pos, other_pos)
    path = [int(np.argmax(dp[-1]))]
    for i in range(M - 1, 0, -1):
        path.append(int(back[i][path[-1]]))
    return path[::-1]


def _expected_timeline(slots, first, last, lang=None):
    """Where on the calendar (0..1) each shot is expected to be.

    Months named in the lyrics are anchors (a line saying "Agosto" sits at the start of August); between
    anchors, and before the first / after the last one, time is interpolated linearly. Without months
    this is simply a straight line from the first to the last photo."""
    from datetime import datetime as dt
    M = len(slots)
    span = max(1.0, (last - first).total_seconds())
    pos = lambda d: min(1.0, max(0.0, (d - first).total_seconds() / span))
    anchors_t, anchors_q = [0.0], [0.0]
    cursor = first
    for i, s in enumerate(slots):
        named = lexicon.months_named(s.get("lyric"), lang)
        if not named:
            continue
        m = named[-1]
        # first occurrence of that month at or after the previous anchor
        year = cursor.year if m >= cursor.month else cursor.year + 1
        d = dt(year, m, 5, tzinfo=first.tzinfo)
        if d > last + (last - first) * 0.05:
            continue
        t, qv = (i + 0.5) / M, pos(d)
        if qv >= anchors_q[-1] and t > anchors_t[-1]:
            anchors_t.append(t)
            anchors_q.append(qv)
            cursor = d
    anchors_t.append(1.0)
    anchors_q.append(1.0)
    return np.interp((np.arange(M) + 0.5) / M, anchors_t, anchors_q)


def mentioned_people(lyric, names, project_people=()):
    """Immich people named in a lyric line. The project's own people count whenever they are written with a
    capital letter; other short names (< 5 letters, e.g. "Mar") only mid-line, so common words do not trigger."""
    out = []
    words = re.sub(r"[,.;:!¡?¿()\"']", " ", lyric or "").split()
    for name in names:
        first = name.split()[0]
        for pos, w in enumerate(words):
            if w.lower() != first.lower():
                continue
            if (w[0].isupper() and (name in project_people or pos > 0)) or len(first) >= 5:
                out.append(name)
                break
    return out


def _tag_norm(t):
    t = t.lower().strip()
    return t[:-1] if t.endswith("s") and not t.endswith("ss") else t


def _line_ai(slot, lines):
    """AI reading of the lyric line(s) a slot shows (by line index; older projects: same text, nearest in time)."""
    idx = [k for k in slot.get("line_idx") or [] if 0 <= k < len(lines or []) and (lines[k] or {}).get("ai")]
    if idx:
        ais = [lines[k]["ai"] for k in idx]
        if len(ais) == 1:
            return ais[0]
        return {"english": " ".join(a.get("english", "") for a in ais), "visual": "; ".join(a.get("visual", "") for a in ais),
                "tags": list(dict.fromkeys(t for a in ais for t in a.get("tags", [])))[:6], "source": ais[0].get("source")}
    best, best_d = None, 1e9
    for l in lines or []:
        if l.get("ai") and l.get("text") == slot.get("lyric"):
            d = abs((l.get("start") or 0) - slot.get("start", 0))
            if d < best_d:
                best, best_d = l["ai"], d
    return best


def slot_cues(slots, all_names, project_people=(), lines=None, lang=None):
    """Per-shot cues from the lyrics: months (named or carried), season, things named, people named. The words are
    read in the song's language (lexicon.py); the lyrics model's reading of each line (any language) fills in."""
    cues, carry_month, carry_left = [], None, 0
    for s in slots:
        lyric = s.get("lyric") or ""
        ai = _line_ai(s, lines) if lyric else None
        named = lexicon.months_named(lyric, lang)
        if not named and ai and isinstance(ai.get("month"), int) and 1 <= ai["month"] <= 12:
            named = [ai["month"]]
        month, month_w = None, 0.0
        if named:
            month, month_w = named[-1], W_MONTH
            carry_month, carry_left = named[-1], CARRY_LINES
        elif carry_month and carry_left > 0 and lyric:
            month, month_w = carry_month, W_MONTH_CARRY * carry_left / CARRY_LINES
            carry_left -= 1
        words = _norm_words(lyric)
        season = lexicon.season_named(lyric, lang)
        if not season and ai and ai.get("season") in lexicon.SEASON_MONTHS:
            season = ai["season"]
        ids = lexicon.concepts_named(lyric, lang)
        ids += [c for c in lexicon.concepts_from_tags((ai or {}).get("tags")) if c not in ids]
        concepts = [(lexicon.CONCEPTS[c][0], lexicon.CONCEPTS[c][1]) for c in ids]
        ram_tags = sorted({t for c in ids for t in lexicon.CONCEPTS[c][2]})
        if ai and ai.get("tags"):
            ram_tags = sorted(set(ram_tags) | {t for t in ai["tags"]})
        cues.append({"lyric": lyric, "lang": lang, "words": words, "month": month, "month_w": month_w, "season": season,
                     "en": (ai or {}).get("english") or "", "visual": (ai or {}).get("visual") or "",
                     "dur": float(s.get("end", 0) - s.get("start", 0)), "concepts": concepts, "ram_tags": ram_tags,
                     "people": mentioned_people(lyric, all_names, project_people)})
    return cues


# ---------------- weights ----------------
# Every signal that scores a photo for a shot, with its default weight. The defaults are hand-tuned; corrections
# made in the review can adjust them (learn.py). Structural parts (timeline prior, same-day, video length) are not
# weights and are not learned.
DEFAULT_WEIGHTS = {
    # photo-level
    "fav": 1.0, "quality": 1.0, "theme": 0.8, "album": W_ALBUM, "not_photo": -W_NOT_PHOTO, "face": 1.0,
    "aesthetic": 0.5, "smile": 1.5, "frontal": 0.3, "eyes_closed": -1.5, "blurry": -1.0,
    # shot-level (depend on the lyric line)
    "lyric": W_LYRIC, "month": 1.0, "place": W_PLACE, "person": W_PERSON, "season": W_SEASON,
    "theme_clash": -0.8, "stranger": -W_STRANGER, "video": 1.0, "concept": W_CONCEPT, "tag": W_TAG,
}
FEATURES = list(DEFAULT_WEIGHTS)
WEIGHTS_FILE = config.DATA / "weights.json"
_w_cache = {"mtime": None, "w": dict(DEFAULT_WEIGHTS)}


def current_weights():
    """Default weights, overridden by the learned ones if learn.py saved any."""
    try:
        m = WEIGHTS_FILE.stat().st_mtime
    except OSError:
        return dict(DEFAULT_WEIGHTS)
    if _w_cache["mtime"] != m:
        try:
            learned = json.loads(WEIGHTS_FILE.read_text()).get("weights", {})
        except (OSError, ValueError):
            learned = {}
        _w_cache.update(mtime=m, w={**DEFAULT_WEIGHTS, **{k: float(v) for k, v in learned.items() if k in DEFAULT_WEIGHTS}})
    return dict(_w_cache["w"])


# How much each signal counts can also be set by hand, in five levels: for every project (data/tuning.json, the
# «Learning» page) and on top of that for one project (its "tuning"). They multiply the weight, so they keep its
# sign: «More» on a penalty (eyes closed) avoids it more.
LEVELS = {-2: 0.0, -1: 0.5, 0: 1.0, 1: 1.75, 2: 3.0}
TUNING_FILE = WEIGHTS_FILE.with_name("tuning.json")


def tuning() -> dict:
    """{"levels": {feature: level}, "dismissed": [[family, slot, asset], ...]} (corrections the user removed)."""
    try:
        t = json.loads(TUNING_FILE.read_text())
    except (OSError, ValueError):
        t = {}
    return {"levels": {k: v for k, v in (t.get("levels") or {}).items() if k in DEFAULT_WEIGHTS and v in LEVELS},
            "dismissed": t.get("dismissed") or []}


def save_tuning(t: dict):
    tmp = TUNING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(t, ensure_ascii=False, indent=1))
    tmp.replace(TUNING_FILE)


def project_weights(project):
    """Learned weights (unless the project asks for the hand-tuned defaults), times the levels set by hand for
    every project and for this one."""
    w = dict(DEFAULT_WEIGHTS) if project.get("learned") is False else current_weights()
    general = tuning()["levels"]
    own = project.get("tuning") or {}
    for k in w:
        w[k] *= LEVELS.get(general.get(k, 0), 1.0) * LEVELS.get(own.get(k, 0), 1.0)
    return w


class Pool:
    """Candidate photos with everything needed to score and explain them for any shot."""

    def __init__(self, ids, dates, favs, emb, project_people, theme, album=(), video_mode="some", weights=None,
                 avoid=None, lang=None, text_lang=None):
        self.ids, self.dates, self.favs, self.emb = ids, dates, favs, emb
        self.w = weights or current_weights()
        self.video_bonus = VIDEO_MODES.get(video_mode, VIDEO_MODES["some"])[0]
        self.album = np.array([a in set(album) for a in ids], dtype=bool)
        n = len(ids)
        # "quality": only CLIP's screenshot / meme / document detector. Its "good photo" impression was dropped:
        # on 2000 measured photos it did not agree with the aesthetic score (rho 0.03) and barely told sharp from
        # blurry faces (AUC 0.60). Image quality comes from the GPU scores (aesthetic, face focus, eyes).
        self.quality = np.zeros(n)
        self.theme_z = np.zeros(n)
        if emb is not None:
            self.quality = -1.5 * np.clip(_z(emb @ immich.text_embedding(*JUNK)) - 0.5, 0, None)
            if theme:
                self.theme_z = _z(emb @ immich.text_embedding(theme, lexicon.nllb(text_lang)))
        # «Avoid» (the project's: "playa, piscina"): photos that look like any of it go down, the more the closer
        self.avoid_terms = avoid_terms(avoid)
        self.avoid_z = np.zeros(n)
        self.avoid_hit = [""] * n
        if emb is not None and self.avoid_terms:
            zs = np.array([_z(emb @ immich.text_embedding(t, lexicon.nllb(text_lang))) for t in self.avoid_terms])
            best = zs.argmax(0)
            self.avoid_z = zs.max(0)
            self.avoid_hit = [self.avoid_terms[b] for b in best]
        self.theme = theme
        self.theme_season = (lexicon.season_named(theme, text_lang) or lexicon.season_named(theme, lang)) if theme else None
        infos = [immich._info.get(a, {}) for a in ids]
        self.is_video = np.array([i.get("type") == "VIDEO" for i in infos])
        self.vdur = np.array([i.get("duration") or 0.0 for i in infos])
        # PNG files with no camera in the EXIF are screenshots / illustrations (WhatsApp JPGs are fine)
        self.not_photo = np.array([(i.get("mime") or "").endswith("png") and not i.get("camera") for i in infos])
        self.months = np.array([d.month for d in dates])
        self.people = [i.get("people", set()) for i in infos]
        pp = set(project_people or [])
        self.stranger = np.array([bool(pp) and bool(p) and not (p & pp) for p in self.people])
        near = geo.place_words([i.get("latlon") for i in infos])
        self.places = [_place_words(i.get("place"), lang) | (nw - PLACE_STOP) for i, nw in zip(infos, near)]
        self.face = np.zeros(n)
        self.together = np.zeros(n, dtype=int)
        self.project_people = list(project_people or [])
        # GPU quality signals (filled by apply_scores)
        self.has_q = np.zeros(n, bool)
        self.aes_z = np.zeros(n)
        self.fsum = [None] * n
        self.smile = np.zeros(n)
        self.frontal = np.zeros(n)
        self.eyes_closed = np.zeros(n)
        self.blurry = np.zeros(n)
        self.shirtless_mode = "show"
        self.tag_df = {}                           # share of the tagged photos that have each (normalised) tag
        self.tags = [set() for _ in range(n)]      # RAM++ tags (English), when the worker computed them
        self._update_base()

    def photo_features(self):
        """Photo-level signals (name -> array over the pool), face size excluded (added per shot)."""
        return {"fav": self.favs.astype(float), "quality": self.quality, "theme": self.theme_z,
                "album": self.album.astype(float), "not_photo": self.not_photo.astype(float),
                "aesthetic": self.aes_z, "smile": self.smile, "frontal": self.frontal,
                "eyes_closed": self.eyes_closed, "blurry": self.blurry}

    def _update_base(self):
        self.base = sum(self.w[k] * v for k, v in self.photo_features().items()) \
            - W_AVOID * np.clip(self.avoid_z - AVOID_FROM, 0, None)

    def apply_scores(self, qs):
        """Fold the GPU quality scores (scores.py) into the photo signals; qs = {asset_id: record}."""
        aes = np.array([(qs.get(a) or {}).get("aesthetic", np.nan) for a in self.ids], dtype=float)
        ok = ~np.isnan(aes)
        if ok.sum() > 10:
            self.aes_z[ok] = (aes[ok] - aes[ok].mean()) / (aes[ok].std() + 1e-9)
        for k, a in enumerate(self.ids):
            rec = qs.get(a)
            if not rec:
                continue
            self.has_q[k] = True
            self.tags[k] = set(rec.get("tags") or ())
            fs = scores.face_summary(rec, set(self.project_people))
            self.fsum[k] = fs
            if fs and fs.get("n"):
                self.smile[k], self.frontal[k] = fs["smile"], fs["frontal"]
                self.eyes_closed[k], self.blurry[k] = float(fs["eyes_closed"]), float(fs["blurry"])
        tagged = [t for t in self.tags if t]
        df = {}
        for ts in tagged:
            for t in {_tag_norm(x) for x in ts}:
                df[t] = df.get(t, 0) + 1
        self.tag_df = {t: c / len(tagged) for t, c in df.items()} if len(tagged) >= 50 else {}
        self._update_base()

    def wanted_tags(self, cue):
        """Normalised tags the shot asks for, minus those most photos have anyway."""
        want = {_tag_norm(t) for t in cue.get("ram_tags") or ()} | {_tag_norm(t.split()[-1]) for t in cue.get("ram_tags") or ()}
        return {t for t in want if self.tag_df.get(t, 0) <= TAG_COMMON}

    def load_faces(self, subset):
        fc = immich.faces([self.ids[k] for k in subset], self.project_people)
        for k in subset:
            fl = fc.get(self.ids[k], [])
            self.face[k] = _face_bonus(fl, len(self.project_people))
            self.together[k] = sum(1 for f in fl if f["selected"])

    def features(self, cue, subset):
        """All signals for the photos in `subset` (indices) and a shot with these cues: (matrix, lyric z, hard).
        matrix columns follow FEATURES; `hard` holds non-learned penalties (clips too short for the shot)."""
        subset = np.asarray(subset, dtype=int)
        m = len(subset)
        cols = {k: v[subset] for k, v in self.photo_features().items()}
        cols["face"] = self.face[subset]
        lz = np.zeros(m)
        if self.emb is not None and cue["lyric"]:
            # the Spanish line, its English translation and (most) the description of the photo it suggests;
            # capped so one very strong visual match cannot outweigh explicit month/place cues
            parts = [(cue["lyric"], lexicon.nllb(cue.get("lang")), 1.0)]
            if cue.get("en"):
                parts.append((cue["en"], "eng_Latn", 1.0))
            if cue.get("visual") and cue.get("visual") != cue.get("en"):
                parts.append((cue["visual"], "eng_Latn", 2.0))
            tot = sum(w for _, _, w in parts)
            mix = sum(w * _z(self.emb[subset] @ immich.text_embedding(t, lang)) for t, lang, w in parts) / tot
            lz = np.clip(_z(mix), -2.0, 2.5)
        cols["lyric"] = lz
        # things the line names ("hojas", "charcos"…): best match among them, z-scored like the lyric
        cols["concept"] = np.zeros(m)
        if self.emb is not None and cue.get("concepts"):
            zs = [np.clip(_z(self.emb[subset] @ immich.text_embedding(p, "eng_Latn")), -1.0, 3.0)
                  for p, _ in cue["concepts"]]
            best = np.max(zs, axis=0)
            cols["concept"] = best
            arg = np.argmax(zs, axis=0)
            hits = self.__dict__.setdefault("_concept_hits", {}).setdefault(tuple(cue["concepts"]), {})
            hits.update({int(k): (cue["concepts"][int(a)][1], float(b)) for k, a, b in zip(subset, arg, best)})
        cols["month"] = (cue["month_w"] * (self.months[subset] == cue["month"])) if cue["month"] else np.zeros(m)
        season = _season(cue.get("season"))
        if season:
            cols["season"] = np.isin(self.months[subset], lexicon.SEASON_MONTHS[season]).astype(float)
            # the line's own season beats the project theme
            cols["theme_clash"] = self.theme_z[subset] if self._theme_clashes(cue) else np.zeros(m)
        else:
            cols["season"] = cols["theme_clash"] = np.zeros(m)
        want = self.wanted_tags(cue)
        cols["tag"] = (np.array([float(bool(want & {_tag_norm(t) for t in self.tags[k]})) for k in subset])
                       if want else np.zeros(m))
        cols["place"] = (np.array([bool(cue["words"] & self.places[k]) for k in subset], dtype=float)
                         if cue["words"] else np.zeros(m))
        named = set(cue["people"])
        # everybody the line names should be in the photo: full signal only when all of them are
        cols["person"] = (np.array([len(named & self.people[k]) / len(named) for k in subset])
                          if named else np.zeros(m))
        cols["stranger"] = np.array([float(self.stranger[k] and not (named & self.people[k]) and not self.album[k])
                                     for k in subset])
        vid = self.is_video[subset]
        fits = self.vdur[subset] >= cue.get("dur", 0) + VIDEO_MARGIN
        cols["video"] = np.where(vid & fits, self.video_bonus, 0.0)
        hard = np.where(vid & ~fits, -50.0, 0.0)  # clips only where they are long enough for the shot
        pen = SHIRTLESS_PENALTY.get(self.shirtless_mode, 0.0)
        if pen:  # the user's choice for this project, not something learned
            hard = hard + pen * np.array([float(bool(sensitive(self.tags[k]))) for k in subset])
        return np.column_stack([cols[k] for k in FEATURES]), lz, hard

    def row(self, cue, subset):
        """Score of each photo in `subset` (indices) for a shot with these cues; also returns the lyric z."""
        X, lz, hard = self.features(cue, subset)
        return X @ np.array([self.w[k] for k in FEATURES]) + hard, lz

    def _theme_clashes(self, cue):
        """The line names a season and the project theme is about something else (e.g. 'verano' vs 'otoño')."""
        s = _season(cue.get("season"))
        if not s or not self.theme:
            return False
        return self.theme_season is None or s != self.theme_season

    def why(self, k, cue, lz):
        tags = []
        hit = cue["words"] & self.places[k]
        if hit:
            shown = [w.strip(",.;:!¡?¿") for w in cue["lyric"].split() if _norm_words(w) & hit]
            tags.append("📍 " + ", ".join(dict.fromkeys(shown)))
        for name in cue["people"]:
            if name in self.people[k]:
                tags.append("👤 " + name)
        if cue["month"] and self.months[k] == cue["month"]:
            tags.append("📅 " + MONTHS_EN[cue["month"] - 1])
        want = self.wanted_tags(cue)
        seen = {t for t in self.tags[k] if _tag_norm(t) in want}
        hit = getattr(self, "_concept_hits", {}).get(tuple(cue.get("concepts") or ()), {}).get(int(k))
        if seen:  # one spelling per tag (car seat / car seats, Seat / seat)
            tags.append("🔎 " + ", ".join(sorted({_tag_norm(t): t.lower() for t in sorted(seen)}.values())))
        elif hit and hit[1] >= 1.2:
            tags.append("🔎 " + hit[0])
        if lz >= 1.5:
            tags.append("🎵 fits the lyrics")
        elif lz >= 0.8:
            tags.append("🎵 somewhat fits the lyrics")
        season = _season(cue.get("season"))
        if season and self.months[k] in lexicon.SEASON_MONTHS[season]:
            tags.append(lexicon.SEASON_CHIP[season])
        if self.theme and self.theme_z[k] >= 1.8 and not self._theme_clashes(cue):
            tags.append("🏷️ " + self.theme)
        if self.avoid_z[k] >= AVOID_FROM + 1:
            tags.append(f"🚫 looks like {self.avoid_hit[k]}")
        if self.album[k]:
            tags.append("🗂️ from the album")
        if self.favs[k]:
            tags.append("⭐ favorite")
        fs = self.fsum[k] if getattr(self, "fsum", None) else None
        if fs and fs.get("n") and fs["smile"] >= 0.6:
            tags.append("😁 smiling")
        if getattr(self, "aes_z", None) is not None and self.aes_z[k] >= 1.2:
            tags.append("🎨 good-looking")
        if self.together[k] >= 2:
            tags.append("👫 together")
        if self.not_photo[k]:
            tags.append("🖼️ illustration")
        if self.is_video[k]:
            tags.insert(0, f"🎬 video ({self.vdur[k]:.0f} s)")
        if not tags:
            tags.append("🕒 by date")
        if self.face[k] < -0.4:
            tags.append("🔍 small faces")
        if fs and fs.get("eyes_closed"):
            tags.append("😑 eyes closed")
        if fs and fs.get("blurry", 0) >= 1:
            tags.append("💨 blurry face")
        elif fs and fs.get("blurry", 0) > 0:
            tags.append("〰️ slightly soft face")
        warn = sensitive(self.tags[k])
        if warn:
            tags.insert(0, "⚠️ " + warn)
        return tags


def _all_names():
    return [p["name"] for p in immich.people(1000)]


def suggest(project, progress=None, score_missing=None):
    """Fill project['slots'][i]['asset'], ['alts'] and ['why'], keeping locked shots as they are."""
    people = project.get("people") or []
    slots = project["slots"]
    lang = lyrics_language(project)
    cues = slot_cues(slots, _all_names(), people, project.get("lines"), lang)
    # people named in the lyrics join the pool, but only score well on the lines that name them
    extra = sorted({n for c in cues for n in c["people"]} - set(people)) if people else []
    video_mode = project.get("videos") or "some"
    ids, dates, favs, emb = immich.candidates(people + extra, project.get("date_from"), project.get("date_to"),
                                              videos=video_mode != "off")
    album = immich.album_assets(project.get("album_id"))
    ids, dates, favs, emb = _merge((ids, dates, favs, emb), immich.assets_by_ids([a for a in album if a not in set(ids)]))
    if not ids:
        raise RuntimeError("No photos with those filters")
    project["vectors"] = emb is not None
    excluded = set(project.get("excluded", []))
    if progress:
        progress(0.2)
    pool = Pool(ids, dates, favs, emb, people, project.get("theme"), album, video_mode,
                weights=project_weights(project), avoid=project.get("avoid"),
                lang=lyrics_language(project), text_lang=project.get("language"))
    pool.shirtless_mode = project.get("shirtless") or "show"

    locked_ids = {s["asset"] for s in slots if s.get("locked") and s.get("asset")}
    keep = [k for k, a in enumerate(ids) if a not in excluded or a in locked_ids]
    order = sorted(keep, key=lambda k: dates[k])
    # the GPU scores (face focus, eyes, smile, aesthetic) must be in before picking the best photo of each burst
    pool.apply_scores(scores.get([ids[k] for k in keep]))
    groups = {}
    reps = _collapse_bursts(order, dates, emb, pool.base, groups)
    burst_of = {m: g for g in groups.values() if len(g) > 1 for m in g}
    rep_in = {m: r for r, g in groups.items() for m in g}
    idx_of = {a: k for k, a in enumerate(ids)}
    extra_reps = [idx_of[a] for a in locked_ids if a in idx_of and idx_of[a] not in set(reps)]
    if extra_reps:  # locked photos must stay selectable even if they lost their burst
        reps = np.array(sorted(list(reps) + extra_reps, key=lambda k: dates[k]), dtype=int)
    N = len(reps)
    if progress:
        progress(0.3)

    top = reps[np.argsort(-pool.base[reps])[:FACE_LIMIT]]
    pool.load_faces(top)
    # GPU quality scores: cached ones always; missing ones computed now if a worker is available
    if score_missing:
        score_missing([ids[k] for k in top], lambda x: progress and progress(0.32 + 0.16 * x))
    pool.apply_scores(scores.get([ids[k] for k in keep]))
    not_top = ~np.isin(reps, top)
    if progress:
        progress(0.5)

    M = len(slots)
    ts = np.array([dates[k].timestamp() for k in reps])
    q = (ts - ts[0]) / max(1.0, ts[-1] - ts[0])
    expected = _expected_timeline(slots, dates[reps[0]], dates[reps[-1]], lang)
    score = np.zeros((M, N))
    lyric_z = np.zeros((M, N))
    for i in range(M):
        row, lz = pool.row(cues[i], reps)
        score[i] = row - 1.0 * not_top - W_PRIOR * np.abs(q - expected[i])
        lyric_z[i] = lz
    if progress:
        progress(0.7)

    rep_pos = {int(k): j for j, k in enumerate(reps)}
    locked = {i: rep_pos[idx_of[s["asset"]]] for i, s in enumerate(slots)
              if s.get("locked") and s.get("asset") in idx_of and idx_of[s["asset"]] in rep_pos}
    day = np.array([dates[k].toordinal() for k in reps])
    order_mode = project.get("order") or "flex"
    if order_mode == "strict":
        path = _align(score, locked, day)
    elif order_mode == "free":
        path = _align_free(score - (-W_PRIOR * np.abs(q[None, :] - expected[:, None])), locked, day)
    else:
        flex_days = int(project.get("flex_days") or FLEX_DAYS)
        path = _refine_flexible(score, _align(score, locked, day), locked, day, flex_days)

    # no more video shots than the project allows: swap the extra ones (weakest first) for the best photo nearby
    cap = int(np.floor(M * VIDEO_MODES.get(video_mode, VIDEO_MODES["some"])[1]))
    vid_slots = [i for i in range(M) if pool.is_video[reps[path[i]]] and i not in locked]
    if len(vid_slots) > cap:
        used = set(path)
        for i in sorted(vid_slots, key=lambda i: score[i, path[i]])[: len(vid_slots) - cap]:
            lo, hi = np.searchsorted(day, [day[path[i]] - ALT_DAYS, day[path[i]] + ALT_DAYS + 1])
            cand = [j for j in range(lo, hi) if not pool.is_video[reps[j]] and j not in used]
            if cand:
                best = max(cand, key=lambda j: score[i, j])
                used.discard(path[i]); used.add(best); path[i] = best

    for i, s in enumerate(slots):
        # alternatives: strict = between the neighbours' photos; flexible = ±ALT_DAYS around this photo;
        # free = the best ones for this line from any date
        if order_mode == "strict":
            lo = path[i - 1] + 1 if i > 0 else 0
            hi = path[i + 1] if i + 1 < M else N
            window = np.arange(min(lo, max(0, path[i] - 10)), max(hi, min(N, path[i] + 11)))
        elif order_mode == "free":
            window = np.arange(N)
        else:
            alt_days = max(ALT_DAYS, int(project.get("flex_days") or FLEX_DAYS))
            lo, hi = np.searchsorted(day, [day[path[i]] - alt_days, day[path[i]] + alt_days + 1])
            window = np.arange(lo, max(hi, lo + 1))
        ranked = window[np.argsort(-score[i, window])]
        if emb is not None and not s.get("locked"):
            # never repeat (almost) the same image: swap for the best non-duplicate in the window
            chosen = [reps[path[j]] for j in range(i)]
            def dup(j):
                return chosen and float((emb[chosen] @ emb[reps[j]]).max()) > 0.92
            if dup(path[i]):
                for j in ranked:
                    if not dup(j):
                        path[i] = int(j)
                        break
        alt_js = [j for j in ranked if j != path[i]][:15]
        s["alts"] = [ids[reps[j]] for j in alt_js]
        if not s.get("locked"):
            s["asset"] = ids[reps[path[i]]]
        s["why"] = {ids[reps[j]]: pool.why(reps[j], cues[i], lyric_z[i, j]) for j in [path[i]] + alt_js}
        s["named"] = cues[i]["people"]
        g = burst_of.get(idx_of.get(s.get("asset"), -1))
        if g:  # the other shots of the same moment, for a quick swap in the review
            s["burst"] = [ids[k] for k in g]
            s["burst_best"] = ids[rep_in[g[0]]]  # the one the suggestion's own scoring prefers
        elif s.get("locked") and s.get("asset"):  # a pinned photo outside the pool: look its burst up
            s["burst"] = burst_for(project, s["asset"]) or None
            s.pop("burst_best", None)
            if not s["burst"]:
                s.pop("burst")
        else:
            s.pop("burst", None)
            s.pop("burst_best", None)
    if progress:
        progress(0.9)
    return project


def _merge(a, b):
    """Concatenate two (ids, dates, favs, emb) tuples."""
    if not b[0]:
        return a
    if not a[0]:
        return b
    emb = None if a[3] is None or b[3] is None else np.vstack([a[3], b[3]])
    return a[0] + b[0], a[1] + b[1], np.concatenate([a[2], b[2]]), emb


def burst_for(project, asset_id):
    """The burst (same moment) of any photo, with the same rule as the suggestion (consecutive photos less than
    2 minutes apart and alike): its time-ordered ids, or [] when the photo is alone. Used for photos the user
    picks by hand, which used to lose the 🎞️ burst picker."""
    inf = immich._info_one(asset_id) or {}
    d = immich.parse_date(inf.get("date"))
    if not d:
        return []
    day = d.date().isoformat()
    got = immich.candidates(project.get("people") or [], day, day)
    if asset_id not in got[0]:  # e.g. a photo where Immich did not recognise anyone
        got = _merge(got, immich.assets_by_ids([asset_id]))
    ids, dates, _, emb = got
    if not ids or asset_id not in ids:
        return []
    order = sorted(range(len(ids)), key=lambda k: dates[k])
    pos = order.index(ids.index(asset_id))

    def linked(a, b):
        close = abs((dates[b] - dates[a]).total_seconds()) < 120
        return close and (emb is None or float(emb[a] @ emb[b]) > 0.80)
    lo = pos
    while lo > 0 and linked(order[lo - 1], order[lo]):
        lo -= 1
    hi = pos
    while hi + 1 < len(order) and linked(order[hi], order[hi + 1]):
        hi += 1
    group = [ids[k] for k in order[lo:hi + 1]]
    return group if len(group) > 1 else []


def _slot_center(project, i):
    """Date a shot is about: its photo's date, else the neighbours' (for 'closest to the shot's date')."""
    slots = project["slots"]
    for j in [i] + [x for d in range(1, len(slots)) for x in (i - d, i + d)]:
        if 0 <= j < len(slots) and slots[j].get("asset"):
            a = slots[j]["asset"]
            got = immich.parse_date((project.get("assets", {}).get(a) or {}).get("date") or (immich._info.get(a) or {}).get("date"))
            if got:
                return got
    return None


def _pick_item(pool, k, cue, fit, lz, center, used, rec):
    """One photo of the swap dialog with everything the dialog sorts and filters by."""
    a = pool.ids[k]
    inf = immich._info.get(a) or {}
    q, _ = burst_quality(rec, pool.project_people) if rec else (None, [])
    w, h = inf.get("w") or 0, inf.get("h") or 0
    d = pool.dates[k]
    return {"id": a, "date": inf.get("date"), "video": bool(pool.is_video[k]), "why": pool.why(k, cue, lz),
            "fit": round(float(fit), 3), "quality": None if q is None else round(float(q), 3),
            "days": None if center is None or d is None else round(abs((d - center).total_seconds()) / 86400, 2),
            "portrait": bool(w and h and h > w * 1.05), "landscape": bool(w and h and w > h * 1.05),
            "sensitive": sensitive(pool.tags[k]), "fav": bool(pool.favs[k]), "used": a in used}


def rank_for_slot(project, i, asset_ids):
    """The same details as options_for_slot for an explicit list (suggested alternatives, search results),
    keeping the list's order in "rank"."""
    ids, dates, favs, emb = immich.assets_by_ids(list(dict.fromkeys(asset_ids)))
    if not ids:
        return []
    people = project.get("people") or []
    pool = Pool(ids, dates, favs, emb, people, project.get("theme"),
                immich.album_assets(project.get("album_id")) if project.get("album_id") else (),
                project.get("videos") or "some", weights=project_weights(project), avoid=project.get("avoid"),
                lang=lyrics_language(project), text_lang=project.get("language"))
    pool.shirtless_mode = project.get("shirtless") or "show"
    qs = scores.get(ids)
    pool.apply_scores(qs)
    allk = list(range(len(ids)))
    pool.load_faces(allk)
    cue = slot_cues(project["slots"], _all_names(), people, project.get("lines"), lyrics_language(project))[i]
    sc, lz = pool.row(cue, allk)
    center = _slot_center(project, i)
    used = {s.get("asset") for s in project["slots"]}
    order = {a: n for n, a in enumerate(asset_ids)}
    out = [{**_pick_item(pool, k, cue, sc[k], lz[k], center, used, qs.get(ids[k])), "rank": order.get(ids[k], 0)}
           for k in allk]
    return sorted(out, key=lambda x: x["rank"])


ALL_LIMIT = 3000  # "Ver todas": cap so a whole library does not land in the browser at once


def options_for_slot(project, i, people=None, days=None, limit=48, everything=False):
    """Ranked photos for one shot with a custom people filter and date window (days around the current
    photo; None = any date). Used by the swap dialog. Returns [{id, date, why, ...}].
    everything=True: every photo of the filters (bursts included, no top-N cut, no per-photo face lookups)."""
    slots = project["slots"]
    s = slots[i]
    people = list(people if people is not None else (project.get("people") or []))
    center = None
    cur = s.get("asset")
    if cur:
        center = immich.parse_date((project.get("assets", {}).get(cur) or {}).get("date")
                                   or (immich._info.get(cur) or {}).get("date"))
    if days is not None and days >= 0 and center is not None:
        from datetime import timedelta
        d_from = (center - timedelta(days=days)).date().isoformat()
        d_to = (center + timedelta(days=days)).date().isoformat()
    else:
        d_from, d_to = None, None
    cue = slot_cues(slots, _all_names(), people, project.get("lines"), lyrics_language(project))[i]
    album = immich.album_assets(project.get("album_id")) if project.get("album_id") else []
    if days == -1:  # the project's Immich album only
        ids, dates, favs, emb = immich.assets_by_ids(album)
    else:
        ids, dates, favs, emb = immich.candidates(people, d_from, d_to,
                                                  videos=(project.get("videos") or "some") != "off")
    if not ids:
        return []
    pool = Pool(ids, dates, favs, emb, people, project.get("theme"), album, project.get("videos") or "some",
                weights=project_weights(project), avoid=project.get("avoid"),
                lang=lyrics_language(project), text_lang=project.get("language"))
    pool.shirtless_mode = project.get("shirtless") or "show"
    excluded = set(project.get("excluded", [])) | {cur}
    order = sorted([k for k, a in enumerate(ids) if a not in excluded], key=lambda k: dates[k])
    if not order:
        return []
    if everything:
        reps = np.array(order[:ALL_LIMIT], dtype=int) if len(order) <= ALL_LIMIT else \
            np.array(sorted(order, key=lambda k: abs((dates[k] - (center or dates[k])).total_seconds()))[:ALL_LIMIT], dtype=int)
        qs = scores.get([ids[k] for k in reps])
        pool.apply_scores(qs)
        sc, lz = pool.row(cue, reps)
        used = {x.get("asset") for x in slots}
        ctr = center or _slot_center(project, i)
        return [{**_pick_item(pool, k, cue, sc[j], lz[j], ctr, used, qs.get(ids[k])), "rank": j}
                for j, k in enumerate(reps)]
    reps = _collapse_bursts(order, dates, emb, pool.base)
    pool.apply_scores(scores.get([ids[k] for k in reps]))
    sc, lz = pool.row(cue, reps)
    best = np.argsort(-sc)[: limit * 2]
    pool.load_faces([reps[j] for j in best])
    sc, lz = pool.row(cue, reps)  # again, now with face bonuses for the best ones
    best = [j for j in np.argsort(-sc) if j in set(best)][:limit]
    qs = scores.get([ids[reps[j]] for j in best])
    used = {x.get("asset") for x in slots}
    return [{**_pick_item(pool, reps[j], cue, sc[j], lz[j], center, used, qs.get(ids[reps[j]])), "rank": n}
            for n, j in enumerate(best)]


# ---------------- repeated photos in the review ----------------
SIMILAR = 0.86  # CLIP cosine between two chosen photos above which they look alike (the same sofa, two drawings
                # of the same series); suggestions already drop near-copies (> DUP_COS) from the candidates


def repeats(slots, dates=None, vecs=None, dup_ids=None):
    """Pairs of shots showing the same or very similar photos: [{a, b, kind, sim}] with kind
    same (same photo), dup (Immich duplicate), burst (seconds apart and alike) or similar."""
    dates, dup_ids = dates or {}, dup_ids or {}
    used = [(i, s["asset"]) for i, s in enumerate(slots) if s.get("asset")]
    out = []
    for x in range(len(used)):
        for y in range(x + 1, len(used)):
            (i, a), (j, b) = used[x], used[y]
            sim = float(vecs[a] @ vecs[b]) if vecs is not None and a in vecs and b in vecs else None
            if a == b:
                kind = "same"
            elif dup_ids.get(a) and dup_ids.get(a) == dup_ids.get(b):
                kind = "dup"
            elif sim is not None and sim > 0.8 and a in dates and b in dates and abs((dates[a] - dates[b]).total_seconds()) < 60:
                kind = "burst"
            elif sim is not None and sim >= SIMILAR:
                kind = "similar"
            else:
                continue
            out.append({"a": i, "b": j, "kind": kind, "sim": round(sim, 3) if sim is not None else None})
    return out


def burst_quality(rec, people):
    """Simple ranking inside one burst from the GPU scores: smile and a sharp face with open eyes win."""
    if not rec:
        return None, []
    fs = scores.face_summary(rec, set(people)) or {}
    hints, q = [], 0.5 * ((rec.get("aesthetic") or 5) - 5)
    if fs.get("n"):
        q += 1.5 * fs["smile"] - 1.5 * float(fs["eyes_closed"]) - fs["blurry"] + 0.3 * fs["frontal"]
        hints.append(f"😁 {round(fs['smile'] * 100)} %")
        if fs["eyes_closed"]:
            hints.append("😑 eyes closed")
        if fs["blurry"] >= 1:
            hints.append("💨 blurry")
        elif fs["blurry"] > 0:
            hints.append("〰️ slightly soft")
    hints.append(f"🎨 {rec.get('aesthetic', 0):.1f}")
    return q, hints
