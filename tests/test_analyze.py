from slidesong import analyze

LYRICS = """[Intro – Short warm acoustic guitar]

[Verse 1 – Rhythmic acoustic folk-pop]
Se cerró la puerta del cole,
y el verano echó a correr.

[Chorus – Energetic melodic pop-rock]
¡Que vuelva la tormenta!
(Coro)
[Bridge – Intimate vocals, piano, gradual build]
Hay tardes que no se van
[End]
"""


def test_clean_lyrics_drops_tags_and_keeps_order():
    assert analyze.clean_lyrics(LYRICS) == ["Se cerró la puerta del cole,", "y el verano echó a correr.",
                                             "¡Que vuelva la tormenta!", "Hay tardes que no se van"]


def test_sections_follow_suno_tags():
    secs = analyze.lyric_sections(LYRICS)
    assert [s["kind"] for s in secs] == ["verse", "verse", "chorus", "bridge"]
    assert secs[2]["mood"] == "high" and secs[3]["mood"] == "low" and secs[3]["build"]


def test_parse_section_variants():
    assert analyze.parse_section("[Final Chorus – warm]")["kind"] == "chorus"
    assert analyze.parse_section("[Pre-Chorus]")["kind"] == "prechorus"
    assert analyze.parse_section("[Outro – fading vocals]")["kind"] == "outro"


def test_align_matches_words_and_interpolates_gaps():
    lines = ["hola mundo bonito", "esta línea no se canta", "adiós amigos"]
    words = [{"w": w, "start": t, "end": t + 0.4} for w, t in
             [("hola", 1.0), ("mundo", 1.5), ("bonito", 2.0), ("adiós", 6.0), ("amigos", 6.5)]]
    al = analyze.align(lines, words, 10.0)
    assert al[0]["start"] == 1.0 and al[2]["start"] == 6.0
    assert al[1].get("guess") and al[0]["end"] <= al[1]["start"] < al[2]["start"]


def test_plan_slots_cut_at_lines_on_beats():
    lines = [{"text": "a", "start": 4.0, "end": 7.0}, {"text": "b", "start": 12.0, "end": 15.0}]
    beats = [round(0.5 * k, 2) for k in range(41)]
    slots = analyze.plan_slots(20.0, beats, lines, "normal")
    starts = [s["start"] for s in slots]
    assert starts[0] == 0.0 and 4.0 in starts and 12.0 in starts
    assert all(b["start"] == a["end"] for a, b in zip(slots, slots[1:]))
    assert all(s["end"] - s["start"] >= 1.5 for s in slots)


def _song(n=12, gap=3.3, kinds=None):
    lines = [{"text": f"l{k}", "start": 5 + gap * k, "end": 5 + gap * k + 3.0,
              "section": {"kind": (kinds or ["verse"] * n)[k], "mood": "mid"}} for k in range(n)]
    beats = [round(0.25 * k, 2) for k in range(int((10 + gap * n) / 0.25))]
    return 10 + gap * n, beats, lines


def test_pace_changes_shots_per_line():
    dur, beats, lines = _song()
    n = {p: len(analyze.plan_slots(dur, beats, lines, p)) for p in ("slow", "normal", "fast")}
    assert n["slow"] < n["normal"] < n["fast"]
    slow = analyze.plan_slots(dur, beats, lines, "slow")
    assert any(len(s["line_idx"]) == 2 and " " in s["lyric"] for s in slow)  # two lines share a photo


def test_chorus_is_faster_than_verse():
    dur, beats, lines = _song(n=12, gap=4.4, kinds=["verse"] * 6 + ["chorus"] * 6)
    sl = analyze.plan_slots(dur, beats, lines, "normal")  # (in "fast" both hit the 1.5 s minimum)
    verse = [s for s in sl if s["line_idx"] and s["line_idx"][0] < 6 and s["start"] >= 5]
    chorus = [s for s in sl if s["line_idx"] and s["line_idx"][0] >= 6]
    avg = lambda xs: sum(s["end"] - s["start"] for s in xs) / len(xs)
    assert avg(chorus) < avg(verse)


def test_line_ai_joins_shared_lines():
    from slidesong import suggest
    lines = [{"text": "a", "ai": {"english": "A", "visual": "va", "tags": ["x"]}},
             {"text": "b", "ai": {"english": "B", "visual": "vb", "tags": ["y"]}}]
    ai = suggest._line_ai({"lyric": "a b", "line_idx": [0, 1]}, lines)
    assert ai["english"] == "A B" and ai["tags"] == ["x", "y"]


def test_carry_over_keeps_pins_where_they_were():
    old = [{"start": 0, "end": 4, "asset": "a", "locked": True}, {"start": 4, "end": 8, "asset": "b"},
           {"start": 8, "end": 12, "asset": "c", "locked": True}]
    new = [{"start": 0, "end": 2}, {"start": 2, "end": 6}, {"start": 6, "end": 12}]
    lost = analyze.carry_over(old, new)
    assert lost == 0
    assert new[2]["asset"] == "c" and new[2]["locked"]
    assert {n.get("asset") for n in new} >= {"a", "c"}
    pinned = [n for n in new if n.get("locked")]
    assert len(pinned) == 2


def test_line_sung_from_the_start_is_kept():
    lines = [{"text": "primera", "start": 0.0, "end": 3.0}, {"text": "segunda", "start": 3.5, "end": 6.5},
             {"text": "tercera", "start": 7.0, "end": 10.0}]
    beats = [round(0.25 * k, 2) for k in range(60)]
    for pace in ("slow", "normal", "fast"):
        sl = analyze.plan_slots(14.0, beats, lines, pace)
        covered = {k for s in sl for k in s["line_idx"]}
        assert covered == {0, 1, 2}, pace
        assert "primera" in sl[0]["lyric"]


def test_each_line_goes_where_it_is_sung_most():
    lines = [{"text": "uno", "start": 0.0, "end": 2.0}, {"text": "dos", "start": 4.9, "end": 7.0},
             {"text": "tres", "start": 7.6, "end": 10.0}]
    slots = [{"start": 0, "end": 2.2}, {"start": 2.2, "end": 5.0}, {"start": 5.0, "end": 8.0}, {"start": 8.0, "end": 9.0},
             {"start": 9.0, "end": 12.0}]
    analyze.assign_lines(slots, lines)
    assert [s["lyric"] for s in slots] == ["uno", "", "dos", "tres", "tres"]
    assert slots[1]["line_idx"] == []                      # instrumental gap: no borrowed next line
    assert slots[4]["lyric_cont"] and not slots[3]["lyric_cont"]
