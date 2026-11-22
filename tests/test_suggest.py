from datetime import datetime, timedelta

import numpy as np

from slidesong import suggest


def test_mentioned_people_rules():
    names, project = ["Nico", "Teo", "Hugo", "Mar", "Ana"], ["Nico", "Teo"]
    m = lambda l: suggest.mentioned_people(l, names, project)
    assert m("Nico y Teo se reían,") == ["Nico", "Teo"]
    assert m("el mar dormía tranquilo") == []
    assert m("Mar y Ana en la playa") == ["Ana"]  # short non-project name only mid-line


def test_slot_cues_months_seasons_and_carry():
    slots = [{"lyric": "En agosto fuimos de acampada", "start": 0, "end": 3},
             {"lyric": "y llegaron los primos", "start": 3, "end": 6},
             {"lyric": "y el verano echó a correr", "start": 6, "end": 9}]
    c = suggest.slot_cues(slots, [], [])
    assert c[0]["month"] == 8 and c[0]["month_w"] == suggest.W_MONTH
    assert c[1]["month"] == 8 and 0 < c[1]["month_w"] < suggest.W_MONTH
    assert c[2]["season"] == "summer" and c[2]["dur"] == 3


def test_align_is_monotonic_and_respects_locks():
    rng = np.random.default_rng(1)
    score = rng.normal(size=(6, 40))
    day = np.repeat(np.arange(20), 2)
    path = suggest._align(score, {2: 30}, day)
    assert path == sorted(path) and len(set(path)) == 6 and path[2] == 30


def test_refine_flexible_stays_within_tolerance():
    rng = np.random.default_rng(2)
    score = rng.normal(size=(5, 60))
    day = np.arange(60)
    base = suggest._align(score, {}, day)
    flex = suggest._refine_flexible(score, base, {}, day, 7)
    assert all(abs(day[a] - day[b]) <= 7 for a, b in zip(base, flex)) and len(set(flex)) == 5


def test_align_free_never_repeats():
    score = np.zeros((4, 10)); score[:, 3] = 5  # everybody wants photo 3
    path = suggest._align_free(score, {}, np.arange(10))
    assert len(set(path)) == 4 and 3 in path


def test_expected_timeline_uses_month_anchors():
    first, last = datetime(2026, 6, 1), datetime(2026, 11, 1)
    slots = [{"lyric": ""}] * 4 + [{"lyric": "Septiembre llegó volando"}] + [{"lyric": ""}] * 5
    exp = suggest._expected_timeline(slots, first, last)
    sept = (datetime(2026, 9, 5) - first) / (last - first)
    assert abs(exp[4] - sept) < 1e-9 and all(np.diff(exp) >= 0)


def test_collapse_bursts_keeps_best_of_each_moment():
    t0 = datetime(2026, 7, 1, 12)
    dates = [t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=20), t0 + timedelta(hours=3)]
    base = np.array([0.1, 0.9, 0.2, 0.5])
    reps = suggest._collapse_bursts([0, 1, 2, 3], dates, None, base)
    assert list(reps) == [1, 3]


def test_place_words_skip_generic_words():
    assert "estacion" not in suggest._place_words(["La Estación", "Andalusia", "Spain"])
    assert "alemania" in suggest._place_words(["Triberg", "Baden-Wurttemberg", "Germany"])


def test_concepts_from_lyrics():
    c = suggest.slot_cues([{"lyric": "Hojas secas en la acera,"}, {"lyric": "saltaremos los charcos."},
                           {"lyric": "Nico sopló las velas."}, {"lyric": "el mar dormía tranquilo"}], [], [])
    assert [t for _, t in c[0]["concepts"]] == ["leaves"]
    assert [t for _, t in c[1]["concepts"]] == ["puddles"]
    assert [t for _, t in c[2]["concepts"]] == ["birthday"]
    assert [t for _, t in c[3]["concepts"]] == ["sea"]


def test_lyric_concepts_carry_ram_tags():
    c = suggest.slot_cues([{"lyric": "saltaremos los charcos."}, {"lyric": "Nico sopló las velas."}], [], [])
    assert "puddle" in c[0]["ram_tags"]
    assert "birthday cake" in c[1]["ram_tags"] and "candle" in c[1]["ram_tags"]


def test_shirtless_modes_penalise_only_flagged_photos():
    assert suggest.SHIRTLESS_PENALTY["show"] == 0 > suggest.SHIRTLESS_PENALTY["avoid"] > suggest.SHIRTLESS_PENALTY["never"]


def test_repeats_kinds():
    from datetime import datetime
    v = {k: np.eye(4)[k] for k in range(4)}
    v["x"], v["y"] = np.array([1, .3, 0, 0]) / np.hypot(1, .3), np.array([1, 0, 0, 0.])
    slots = [{"asset": "x"}, {"asset": "y"}, {"asset": "x"}, {"asset": "d1"}, {"asset": "d2"}, {"asset": 2}]
    vecs = {"x": v["x"], "y": v["y"], "d1": v[1], "d2": v[2], 2: v[3]}
    t = datetime(2026, 8, 1, 10)
    r = suggest.repeats(slots, {"x": t, "y": t}, vecs, {"d1": "g", "d2": "g"})
    kinds = {(e["a"], e["b"]): e["kind"] for e in r}
    assert kinds[(0, 2)] == "same" and kinds[(0, 1)] == "burst" and kinds[(3, 4)] == "dup"
    assert (0, 5) not in kinds


def test_sensitive_tags():
    assert suggest.sensitive({"swimwear", "child"}) == "in swimwear"
    assert suggest.sensitive({"shirtless", "swimwear"}) == "shirtless / in swimwear"
    assert suggest.sensitive({"child", "table"}) is None
