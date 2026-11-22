"""Edit plan: which layout each shot uses and which transition goes between shots, with a reason for each.

Runs in the app (it needs Immich and the song); the renderer only executes the plan, so the GPU worker
gets exactly what the review screen shows. Transitions are chosen from:
  1. Song structure from Suno tags ([Verse], [Chorus – Energetic…], [Bridge – Intimate…]).
  2. Audio: onset strength / loudness at the cut, downbeats, pauses in the vocals.
  3. Tempo: transition lengths are whole beats.
  4. Continuity between the two photos: same moment, or a jump in time/place (a new chapter).
  5. Camera direction: pushes follow the outgoing shot's movement.
User overrides (per boundary) always win.
"""
import numpy as np

from . import analyze, immich, scores
from . import i18n, lexicon, suggest
from .i18n import tr

KINDS = ["cut", "fade", "push", "dipwhite", "dipblack", "flash", "zoom", "slide", "wipe", "whip", "iris", "blur", "light"]
NAMES = {"cut": "Cut", "fade": "Fade", "push": "Push", "dipwhite": "Dip to white", "dipblack": "Dip to black",
         "flash": "Flash", "zoom": "Zoom", "slide": "Slide over", "wipe": "Wipe", "whip": "Whip pan", "iris": "Iris",
         "blur": "Blur", "light": "Warm light", "diptych": "Diptych"}
SECTION_NAMES = {"intro": "Intro", "verse": "Verse", "prechorus": "Pre-chorus", "chorus": "Chorus",
                 "bridge": "Bridge", "outro": "Outro", "interlude": "Instrumental"}
# the interface names sections by their kind; reasons use these (i18n.py has them in Spanish too)
_REASON_SECTION = {"intro": "intro", "verse": "verse", "prechorus": "pre-chorus", "chorus": "chorus",
                   "bridge": "bridge", "outro": "outro", "interlude": "instrumental"}


def transition_name(kind):
    """«Fade», «Whip pan»… in the request's language (the editable export lists them)."""
    return tr(NAMES.get(kind, kind))
A = 16 / 9


# ---------------- layout ----------------
def _pick(key, options):
    """Deterministic 'random' choice so the same project always gets the same edit."""
    return options[sum(ord(c) for c in key) % len(options)]


def face_box(meta):
    fl = meta.get("faces") or []
    sel = [f["box"] for f in fl if f.get("selected")] or [f["box"] for f in fl]
    if not sel:
        return None
    return (min(b[0] for b in sel), min(b[1] for b in sel), max(b[2] for b in sel), max(b[3] for b in sel))


def aspect_of(asset_id, meta):
    """Displayed aspect ratio (from the oriented preview), cached in the asset metadata."""
    if meta.get("aspect"):
        return meta["aspect"]
    from PIL import Image
    import io
    try:
        got = immich.fetch(asset_id, "preview")
    except Exception as e:  # Immich unreachable: use the stored size for now, do not cache the guess
        print("aspect:", e)
        return round((meta.get("w") or 4) / (meta.get("h") or 3), 4)
    if got:
        w, h = Image.open(io.BytesIO(got[0])).size
    else:
        w, h = meta.get("w") or 4, meta.get("h") or 3
    meta["aspect"] = round(w / h, 4)
    return meta["aspect"]


def _tilt_fits(aspect, box):
    return bool(box) and aspect < 0.95 and (box[3] - box[1]) <= 0.8 * (aspect / A)


def _same_scene(a_id, b_id):
    """Diptychs only pair photos from the same outing: within 2 days and 50 km."""
    ia, ib = immich._info_one(a_id) or {}, immich._info_one(b_id) or {}
    da, db = immich.parse_date(ia.get("date")), immich.parse_date(ib.get("date"))
    if not da or not db or abs((db - da).total_seconds()) > 2 * 86400:
        return False
    km = _km(ia.get("latlon"), ib.get("latlon"))
    return km is None or km < 50


def burst_partner(project, s, used, vecs):
    """Another portrait photo of the same moment (burst) to show beside a portrait shot: not near-identical
    (that would look like a glitch), not used elsewhere, the best by the GPU scores. None if there is none."""
    from . import suggest
    aid = s["asset"]
    excluded = set(project.get("excluded", []))
    sibs = [a for a in s.get("burst", []) if a != aid and a not in used and a not in excluded]
    if aid in vecs:
        sibs = [a for a in sibs if a in vecs and float(vecs[a] @ vecs[aid]) < 0.94]
    if not sibs:
        return None
    have = scores.get(sibs)
    people = project.get("people") or []
    sibs = [a for a in sibs if not suggest.sensitive((have.get(a) or {}).get("tags"))]  # never unreviewed ⚠️ ones
    sibs.sort(key=lambda a: -(suggest.burst_quality(have.get(a), people)[0] or -9))
    assets = project.setdefault("assets", {})
    for a in sibs[:3]:
        m = assets.setdefault(a, {})
        if "faces" not in m:
            m.update(immich.asset_meta([a], people).get(a, {}))
        if aspect_of(a, m) < 0.95 and not m.get("video"):
            return a
    return None


MOVES = ["in", "out", "pan_lr", "pan_rl", "tilt", "contain_in", "contain_out", "whole_to_face", "face_to_whole",
         "polaroid", "polaroid_pair", "diptych", "diptych_next", "diptych_other", "single"]
# diptych = with the next shot if possible, else with another photo; diptych_next / diptych_other = exactly that
MOTION = {"calm": 0.6, "normal": 1.0, "lively": 1.35}  # project style -> camera move amplitude


def auto_caption(asset_id, language="es"):
    """Default text for a print's bottom edge: the month and year it was taken ('julio 2026', 'July 2026'), in the
    song's language (else the project's; older projects, made before either was known, are Spanish)."""
    d = immich.parse_date((immich._info_one(asset_id) or {}).get("date"))
    if not d:
        return ""
    names = lexicon.MONTH_NAMES.get(language) or lexicon.MONTH_NAMES["en"]
    return f"{names[d.month - 1]} {d.year}"


def captions_for(project, sh):
    """Texts of the prints of a shot: the user's (an empty one means no text) or the automatic one (not
    repeated on the second print when it says the same)."""
    own = project.get("captions") or {}
    ids = [project["slots"][sh["slots"][0]]["asset"]] + ([sh["pair"]] if sh.get("pair") and sh["kind"] == "polaroid_pair" else [])
    lang = suggest.lyrics_language(project) or project.get("language") or "es"
    caps = [own[a] if a in own else auto_caption(a, lang) for a in ids]
    if len(ids) == 2 and ids[1] not in own and caps[1] == caps[0]:
        caps[1] = ""
    return caps, ids


def partner_candidates(project, i):
    """Photos that can be the second photo of shot i: its burst first, then the rest of that day (portraits
    first), not used elsewhere. [{id, date, portrait, sensitive, burst}]"""
    from . import suggest
    s = project["slots"][i]
    aid = s.get("asset")
    inf = immich._info_one(aid) or {}
    d = immich.parse_date(inf.get("date"))
    if not aid or not d:
        return []
    day = d.date().isoformat()
    ids, _, _, _ = immich.candidates(project.get("people") or [], day, day)
    used = {x.get("asset") for x in project["slots"]}
    burst = [a for a in s.get("burst") or [] if a != aid]
    rest = [a for a in ids if a not in set(burst) and a != aid]
    have = scores.get(burst + rest)
    out = []
    for a in burst + rest:
        if a in used or a in set(project.get("excluded", [])):
            continue
        i2 = immich._info.get(a) or {}
        if i2.get("type") == "VIDEO":
            continue
        w, h = i2.get("w") or 0, i2.get("h") or 0
        q, hints = suggest.burst_quality(have.get(a), project.get("people") or [])
        out.append({"id": a, "date": i2.get("date"), "portrait": bool(w and h and h > w * 1.05), "burst": a in burst,
                    "sensitive": suggest.sensitive((have.get(a) or {}).get("tags")), "q": q, "why": hints})
    out.sort(key=lambda x: (not x["burst"], not x["portrait"], x["date"] or ""))
    return out


def day_partner(project, s, used):
    """A portrait photo of the same day and place (<= 50 km) to pair with a portrait shot that has no burst
    partner: measured by the GPU, never flagged ⚠️, not used elsewhere, not near-identical; the best one."""
    from . import suggest
    aid = s["asset"]
    inf = immich._info_one(aid) or {}
    d = immich.parse_date(inf.get("date"))
    if not d:
        return None
    day = d.date().isoformat()
    ids, _, _, emb = immich.candidates(project.get("people") or [], day, day)
    if not ids:
        return None
    vec = {a: emb[k] for k, a in enumerate(ids)} if emb is not None else {}
    excluded = set(project.get("excluded", []))
    have = scores.get(ids)
    people = project.get("people") or []
    cands = []
    for a in ids:
        i = immich._info.get(a) or {}
        rec = have.get(a)
        w, h = i.get("w") or 0, i.get("h") or 0
        if (a == aid or a in used or a in excluded or i.get("type") == "VIDEO" or not (w and h and h > w * 1.05)
                or not rec or suggest.sensitive(rec.get("tags"))):
            continue
        if aid in vec and a in vec and float(vec[a] @ vec[aid]) >= 0.94:
            continue
        km = _km(inf.get("latlon"), i.get("latlon"))
        if km is not None and km > 50:
            continue
        cands.append((suggest.burst_quality(rec, people)[0] or -9, a))
    assets = project.setdefault("assets", {})
    for _, a in sorted(cands, reverse=True)[:3]:
        m = assets.setdefault(a, {})
        if "faces" not in m:
            m.update(immich.asset_meta([a], people).get(a, {}))
        if aspect_of(a, m) < 0.95:
            return a
    return None


def layout(slots, metas, partners=None, overrides=None, style="normal"):
    """Group slots into shots and pick each shot's layout/motion. metas[i] = asset metadata of slot i.
    partners[i] = asset of the same moment that may share slot i's screen as a diptych.
    overrides[i] = the user's choice for slot i (one of MOVES); style = calm | normal | lively."""
    partners, overrides = partners or {}, overrides or {}
    amp = MOTION.get(style, 1.0)
    shots = _layout(slots, metas, partners, overrides, style)
    for sh in shots:
        sh["amp"] = amp
        o = overrides.get(sh["slots"][0])
        if o:
            sh["override"] = o
    return shots


def _layout(slots, metas, partners, overrides, style):
    shots, i = [], 0
    while i < len(slots):
        s, m = slots[i], metas[i]
        asp, box, aid = m["aspect"], face_box(m), s["asset"]
        nxt = metas[i + 1] if i + 1 < len(slots) else None
        portrait = asp < 0.95
        if m.get("video"):
            shot_len = s["end"] - s["start"]
            dur = float(m.get("duration") or 0)
            start = max(0.0, (dur - shot_len) / 2)  # middle of the clip; transitions may borrow ~0.5 s each side
            if s.get("clip_start") is not None:  # chosen by the user in the review
                start = min(max(0.0, float(s["clip_start"])), max(0.0, dur - shot_len))
            shots.append({"slots": [i], "kind": "video", "start": s["start"], "end": s["end"],
                          "clip_start": round(start, 2), "clip_end": round(min(dur, start + shot_len), 2),
                          "aspect": asp})
            i += 1
            continue
        o, o_next = overrides.get(i), overrides.get(i + 1)
        next_portrait = nxt is not None and nxt["aspect"] < 0.95 and not nxt.get("video")
        next_photo = nxt is not None and not nxt.get("video")
        if o == "diptych_next" and next_photo:  # asked for: with the next shot, whatever it is
            shots.append({"slots": [i, i + 1], "kind": "diptych", "start": s["start"], "end": slots[i + 1]["end"],
                          "split": slots[i + 1]["start"]})
            i += 2
            continue
        if o == "diptych" and next_portrait and o_next in (None, "diptych"):  # asked for: pair with the next one
            shots.append({"slots": [i, i + 1], "kind": "diptych", "start": s["start"], "end": slots[i + 1]["end"],
                          "split": slots[i + 1]["start"]})
            i += 2
            continue
        if o in ("diptych", "diptych_other") and i in partners:
            shots.append({"slots": [i], "kind": "diptych", "pair": partners[i], "start": s["start"], "end": s["end"],
                          "split": round(s["start"] + min(0.8, (s["end"] - s["start"]) * 0.25), 3)})
            i += 1
            continue
        if (o is None and o_next in (None, "diptych") and i > 0 and portrait and next_portrait
                and _same_scene(aid, slots[i + 1]["asset"])
                and s["end"] - s["start"] <= 6.5 and slots[i + 1]["end"] - slots[i + 1]["start"] <= 6.5
                and (not (_tilt_fits(asp, box) and _tilt_fits(nxt["aspect"], face_box(nxt)))
                     or _pick(aid + slots[i + 1]["asset"], {"calm": [True, False, False, False],
                                                            "lively": [True, True, False]}.get(style, [True, False, False])))):
            shots.append({"slots": [i, i + 1], "kind": "diptych", "start": s["start"], "end": slots[i + 1]["end"],
                          "split": slots[i + 1]["start"]})
            i += 2
            continue
        if o in MOVES and o not in ("diptych", "diptych_next", "diptych_other", "single", "polaroid_pair"):
            kind = o  # the user's choice
        elif o == "polaroid_pair":
            kind = "polaroid_pair" if i in partners else "polaroid"
        elif not portrait and asp >= 1.2:
            kind = _pick(aid, {"calm": ["in", "out"], "lively": ["pan_lr", "pan_rl", "in", "out", "pan_lr", "pan_rl"]}
                         .get(style, ["in", "out", "pan_lr", "pan_rl", "in", "out"]))
        elif portrait:
            # a portrait photo alone wastes half the screen: vary between the effects that fit it, never the
            # same as the previous shot
            prev = shots[-1].get("look") if shots else None
            opts = (["tilt"] if _tilt_fits(asp, box) else []) + ["contain", "polaroid"]
            if box:  # from the whole photo to the faces, or back
                opts.append(_pick(aid + "fz", ["whole_to_face", "face_to_whole"]))
            if (o != "single" and i in partners and s["end"] - s["start"] >= 2.6
                    and not (shots and shots[-1].get("pair"))):
                opts += {"calm": ["polaroid_pair"], "lively": ["diptych", "polaroid_pair", "diptych"]}.get(
                    style, ["diptych", "polaroid_pair"])
            kind = _pick(aid + "lone", [k for k in opts if k != prev] or opts)
        else:
            kind = "contain"
        look = kind
        if kind == "contain":
            kind = _pick(aid, ["contain_in", "contain_out"])
        shot = {"slots": [i], "kind": kind, "start": s["start"], "end": s["end"], "look": look}
        if kind == "tilt":
            shot["tilt_dir"] = tilt_dir(asp, box)
        if kind in ("diptych", "polaroid_pair"):
            shot.update(pair=partners[i], split=round(s["start"] + min(0.8, (s["end"] - s["start"]) * 0.25), 3))
        shots.append(shot)
        i += 1
    return shots


# ---------------- song context ----------------
def slot_sections(project):
    """Section (from Suno tags) of every slot, by the lyric line it overlaps or the nearest one."""
    lines = project.get("lines") or []
    secs = [l.get("section") for l in lines]
    if lines and not all(secs):
        parsed = analyze.lyric_sections(project.get("lyrics", ""))
        if len(parsed) == len(lines):
            secs = parsed
    out = []
    for s in project["slots"]:
        mid = (s["start"] + s["end"]) / 2
        best, best_d = None, 1e9
        for l, sec in zip(lines, secs):
            if l.get("start") is None or not sec:
                continue
            d = 0 if l["start"] <= mid <= l["end"] else min(abs(mid - l["start"]), abs(mid - l["end"]))
            if d < best_d:
                best, best_d = sec, d
        if best is None:
            best = {"kind": "verse", "label": "", "mood": "mid", "build": False}
        if lines and mid < (lines[0].get("start") or 0) - 1:
            best = {**best, "kind": "intro"}
        out.append(best)
    return out


def _beat_info(project, t):
    """(strength 0..1, loudness 0..1, is_downbeat, beat length s) for the beat nearest to time t."""
    song = project.get("song") or {}
    beats = song.get("beats") or []
    f = song.get("features") or {}
    tempo = song.get("tempo") or 120
    beat_len = 60.0 / tempo if tempo else 0.5
    if not beats or not f.get("beat_strength"):
        return 0.5, 0.5, False, beat_len
    k = int(np.argmin(np.abs(np.array(beats) - t)))
    return f["beat_strength"][k], f["beat_loud"][k], (k - f.get("downbeat_phase", 0)) % 4 == 0, beat_len


def _vocal_pause(project, t):
    """True if the cut falls in a gap of the vocals (between lyric lines) of at least 0.6 s."""
    for a, b in zip(project.get("lines") or [], (project.get("lines") or [])[1:]):
        if a.get("end") is not None and b.get("start") is not None and a["end"] <= t <= b["start"]:
            return b["start"] - a["end"] >= 0.6
    return False


# ---------------- continuity ----------------
def _km(a, b):
    if not a or not b or None in a or None in b:
        return None
    la1, lo1, la2, lo2 = map(np.radians, (a[0], a[1], b[0], b[1]))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(h)))


def continuity(a_id, b_id, vec_sim):
    """(kind, reason, jump): kind 'moment' (same scene) or 'normal'; jump >= 1 means a big jump in
    distance (~150 km) or time (~10 days). Which jumps become chapters is decided across the whole song."""
    ia, ib = immich._info_one(a_id) or {}, immich._info_one(b_id) or {}
    da, db = immich.parse_date(ia.get("date")), immich.parse_date(ib.get("date"))
    if not da or not db:
        return "normal", "", 0.0
    gap_h = abs((db - da).total_seconds()) / 3600
    if gap_h < 2 and (vec_sim is None or vec_sim > 0.75):
        return "moment", "same moment", 0.0
    km = _km(ia.get("latlon"), ib.get("latlon"))
    pa, pb = ia.get("place") or [], ib.get("place") or []
    jump = max((km or 0) / 150, gap_h / 24 / 10)
    if pa and pb and pa[-1] != pb[-1]:
        jump = max(jump, 1.5)  # another country
    if km is not None and km >= 150 and pa and pb:
        reason = f"jump: {pa[0]} → {pb[0]}"
    else:
        reason = f"jump: {int(gap_h // 24)} days {'later' if db > da else 'earlier'}"
    return "normal", reason, jump


def pick_chapters(jumps, window=3):
    """Boundaries that open a new chapter: big jumps that are also the biggest within ±window boundaries."""
    out = set()
    for k, j in enumerate(jumps):
        if j >= 1 and j == max(jumps[max(0, k - window): k + window + 1]):
            out.add(k)
    return out


# ---------------- transitions ----------------
def _push_dir(shot):
    """Continue the outgoing camera movement: content moving left -> next shot enters from the right; a vertical
    pan pushes the way its photo was moving (up or down, see tilt_dir)."""
    if shot["kind"] == "tilt":
        return shot.get("tilt_dir", "up")
    return {"pan_rl": "right", "pan_lr": "left"}.get(shot["kind"], "left")


def tilt_dir(aspect, box):
    """Which way the photo slides in a vertical pan (same rule as render.Cover): with room above the faces the
    camera comes down onto them, so the photo slides up; otherwise it comes up from below and slides down."""
    return "up" if not box or box[1] > 0.4 * aspect / A else "down"


def choose(project, a, b, sec_a, sec_b, cont, cont_reason, idx):
    """Transition between shots a and b (dicts from layout) -> dict(kind, beats, dir, reason)."""
    t = a["end"]
    strength, loud, downbeat, beat = _beat_info(project, t)
    pause = _vocal_pause(project, t)
    min_dur = min(a["end"] - a["start"], b["end"] - b["start"])
    high = sec_b["kind"] == "chorus" or sec_b["mood"] == "high" or loud > 0.8
    low = sec_b["kind"] in ("bridge", "outro") or sec_b["mood"] == "low"
    key = f"{idx}{a['kind']}{b['kind']}"

    def r(kind, beats, reason, d=None):
        return {"kind": kind, "beats": beats, "dir": d or _push_dir(a), "reason": reason}

    if sec_a["kind"] != sec_b["kind"] or sec_a.get("label") != sec_b.get("label"):
        name = _REASON_SECTION.get(sec_b["kind"], sec_b["kind"])
        if sec_b["kind"] == "chorus":
            res = r("flash", 0, f"the {name} comes in" + (" (strong hit)" if strength > 0.7 else ""))
        elif sec_b["kind"] in ("bridge", "outro") or sec_b["mood"] == "low":
            res = _pick(key, [r("dipblack", 4, f"the {name} begins, more intimate"),
                              r("light", 4, f"the {name} begins, more intimate: warm light")])
        elif sec_a["kind"] == "intro":
            res = r("iris", 2, "the lyrics begin: the story opens")
        elif sec_a["kind"] == "chorus":
            res = r("fade", 2, f"the chorus ends, the {name} is back")
        elif sec_a["kind"] == sec_b["kind"]:
            res = r("fade", 2, f"new {name}")
        else:
            res = r("dipwhite", 2, f"new section: {name}")
    elif cont == "chapter":
        res = (r("flash", 0, cont_reason) if high and strength > 0.6
               else _pick(key, [r("dipwhite", 2, cont_reason), r("wipe", 2, cont_reason)]))
    elif cont == "moment":
        res = r("cut", 0, "same moment: hard cut") if not low else r("fade", 1, "same moment, soft part")
    elif low or pause:
        res = (_pick(key, [r("fade", 2, "intimate part"), r("blur", 2, "intimate part: soft blur")]) if low
               else r("fade", 1, "pause in the vocals"))
    elif high:
        if downbeat and strength > 0.75:
            res = r("zoom", 1, "strong hit on the downbeat")
        elif strength > 0.5 or min_dur < 2.6:
            res = r("cut", 0, "chorus: cut on the beat")
        else:
            res = _pick(key, [r("push", 1, "chorus: follows the movement"),
                              r("whip", 1, "chorus: whip pan with the movement")])
    elif min_dur < 2.6:
        res = r("cut", 0, "short shots")
    else:
        res = _pick(key, [r("fade", 1, "verse"), r("fade", 1, "verse"), r("push", 1, "verse: follows the movement"),
                          r("slide", 1, "verse: the next one slides in on top"), r("blur", 1, "verse: soft blur")])
    # durations are whole beats, never longer than ~60 % of the shorter shot
    secs = res["beats"] * beat
    if res["kind"] not in ("cut", "flash") and secs > 0.6 * min_dur:
        fit = int(0.6 * min_dur / beat)
        if fit < 1:
            res = r("cut", 0, f"{res['reason']} (short shot)")
        else:
            res["beats"] = fit
    res["dur"] = round(res["beats"] * beat, 3) if res["kind"] not in ("cut", "flash") else (0.0 if res["kind"] == "cut" else 0.3)
    if res["kind"] == "whip":  # a whip is quick by nature
        res["dur"] = min(res["dur"], 0.45)
    return res


def build(project):
    """Full edit plan for the project's current photos. Caches photo aspects in project['assets']."""
    slots = [s for s in project["slots"] if s.get("asset")]
    if not slots:
        return {"shots": [], "boundaries": []}
    assets = project.setdefault("assets", {})
    missing = [s["asset"] for s in slots if "faces" not in assets.get(s["asset"], {})]
    if missing:
        assets.update(immich.asset_meta(missing, project.get("people")))
    metas = []
    for s in slots:
        m = assets.setdefault(s["asset"], {})
        aspect_of(s["asset"], m)
        metas.append(m)
    index_of = {id(s): k for k, s in enumerate(project["slots"])}
    used = {s["asset"] for s in slots}
    index_of_slot = {id(s): k for k, s in enumerate(slots)}
    burst_ids = sorted({a for s in slots for a in s.get("burst", [])} | used)
    bemb = immich.vectors(burst_ids)
    bvec = {a: bemb[k] for k, a in enumerate(burst_ids)} if bemb is not None else {}
    partners, pair_from = {}, {}
    chosen = {}
    for i, a in (project.get("pair_overrides") or {}).items():  # second photos the user picked
        if int(i) < len(project["slots"]) and id(project["slots"][int(i)]) in index_of_slot:
            chosen[index_of_slot[id(project["slots"][int(i)])]] = a
    for k, a in chosen.items():
        if a and a not in used:
            m = project.setdefault("assets", {}).setdefault(a, {})
            if "faces" not in m:
                m.update(immich.asset_meta([a], project.get("people")).get(a, {}))
            aspect_of(a, m)
            partners[k], pair_from[a] = a, "chosen"
            used.add(a)
    for k, (s, m) in enumerate(zip(slots, metas)):
        if k not in partners and m.get("aspect", 1) < 0.95 and not m.get("video"):
            a, src = (burst_partner(project, s, used, bvec), "burst") if s.get("burst") else (None, None)
            if not a:
                a, src = day_partner(project, s, used), "day"
            if a:
                partners[k], pair_from[a] = a, src
                used.add(a)
    local = {id(s): k for k, s in enumerate(slots)}
    ovr = {local[id(project["slots"][int(i)])]: o for i, o in (project.get("shot_overrides") or {}).items()
           if int(i) < len(project["slots"]) and id(project["slots"][int(i)]) in local and o in MOVES}
    shots = layout(slots, metas, partners, ovr, project.get("motion") or "normal")
    for sh in shots:
        if sh.get("pair"):
            sh["pair_from"] = pair_from.get(sh["pair"], "burst")

    for sh in shots:  # slot positions in the full project list (slots without photo are skipped above)
        sh["slots"] = [index_of[id(slots[k])] for k in sh["slots"]]
    moves = project.get("move") or {}
    for sh in shots:  # how much the camera moves: the user's factor per shot, and whether resolution limits it
        f = moves.get(str(sh["slots"][0]))
        base = sh.get("amp", 1.0)  # the style's amount, before the user's factor
        if f is not None:
            sh["amp"] = round(sh.get("amp", 1.0) * float(f), 3)
            sh["move"] = f
        if sh["kind"] in ("in", "out", "pan_lr", "pan_rl", "tilt", "whole_to_face", "face_to_whole",
                          "contain_in", "contain_out"):
            a = project["slots"][sh["slots"][0]]["asset"]
            m = project.get("assets", {}).get(a) or {}
            inf = immich._info_one(a) or {}
            w, h = inf.get("w") or 0, inf.get("h") or 0
            if w and h:
                if ((m.get("aspect") or w / h) < 1) != (w < h):
                    w, h = h, w                       # as displayed
                from . import render
                d, box = sh["end"] - sh["start"], face_box(m)
                if (f is None and sh["kind"] in ("in", "out", "pan_lr", "pan_rl", "tilt") and not sh.get("override")
                        and render.motion_mag(sh["kind"], w, h, box, d, 0.0) > render.MAX_MAG):
                    # too small to fill the screen even without moving: show it whole instead of stretching it
                    sh["kind"] = sh["look"] = _pick(a, ["contain_in", "contain_out"])
                # slider zones (0..150 %): where the photo starts to stretch (yellow) and to pixelate (red)
                steps = [x / 20 for x in range(31)]
                mags = [render.motion_mag(sh["kind"], w, h, box, d, base * x) for x in steps]
                yellow = next((x for x, g in zip(steps, mags) if g > render.MAX_MAG), None)
                red = next((x for x, g in zip(steps, mags) if g > 1.5), None)
                sh["zones"] = [None if yellow is None else round(yellow * 100), None if red is None else round(red * 100)]
                cur = render.motion_mag(sh["kind"], w, h, box, d, sh.get("amp", 1.0))
                sh["mag"] = round(cur, 2)
                if f is None and cur > render.MAX_MAG:   # automatic stops at the end of the green zone
                    sh["res_limited"], sh["auto_pct"] = True, max(0, round(((yellow or 0.05) - 0.05) * 100))
    own = project.get("captions") or {}
    for sh in shots:  # handwritten text on the prints (the user's, or the automatic month and year)
        if sh["kind"] in ("polaroid", "polaroid_pair"):
            sh["captions"], ids = captions_for(project, sh)
            sh["caption_auto"] = [a not in own for a in ids]
    secs = slot_sections(project)
    ids = [s["asset"] for s in slots]
    emb = immich.vectors(ids)
    vec = {a: emb[k] for k, a in enumerate(ids)} if emb is not None else {}
    overrides = project.get("transition_overrides") or {}
    conts = []
    for k in range(len(shots) - 1):
        aa = project["slots"][shots[k]["slots"][-1]]["asset"]
        ab = project["slots"][shots[k + 1]["slots"][0]]["asset"]
        sim = float(vec[aa] @ vec[ab]) if aa in vec and ab in vec else None
        conts.append(continuity(aa, ab, sim))
    # free order jumps back and forth in time by design: time/place jumps are not chapters there
    chapters = set() if project.get("order") == "free" else pick_chapters([c[2] for c in conts])
    boundaries = []
    for k in range(len(shots) - 1):
        a, b = shots[k], shots[k + 1]
        ia, ib = a["slots"][-1], b["slots"][0]
        kind, reason, _ = conts[k]
        if k in chapters:
            kind = "chapter"
        auto = choose(project, a, b, secs[ia], secs[ib], kind, reason, k)
        res = dict(auto)
        res["auto"] = auto["kind"]
        o = overrides.get(str(ia))
        if o in KINDS:
            res.update(kind=o, reason="chosen by you", override=True)
            beat = _beat_info(project, a["end"])[3]
            res["beats"] = 0 if o in ("cut", "flash") else max(1, res.get("beats") or 1)
            res["dur"] = 0.0 if o == "cut" else 0.3 if o == "flash" else round(res["beats"] * beat, 3)
        res["after_slot"] = ia
        boundaries.append(res)
    # boundaries inside a diptych (shown in the UI, not editable)
    inner = [{"after_slot": sh["slots"][0], "kind": "diptych", "reason": "diptych with the next one"}
             for sh in shots if sh["kind"] == "diptych" and len(sh["slots"]) > 1]  # two-shot diptychs only
    sections = [{"slot": i, "kind": sec["kind"], "name": SECTION_NAMES.get(sec["kind"], sec["kind"]),
                 "label": sec.get("label", ""), "mood": sec["mood"]}
                for i, sec in enumerate(secs) if i == 0 or sec.get("label") != secs[i - 1].get("label")]
    return {"shots": shots, "boundaries": boundaries, "inner": inner, "sections": sections}
