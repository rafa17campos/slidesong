from slidesong import analyze, lexicon, suggest


def test_detects_the_language_of_the_lyrics():
    assert lexicon.detect("Se cerró la puerta del cole, y el verano echó a correr. Con las toallas a la playa, "
                          "nuestra historia comenzó") == "es"
    assert lexicon.detect("When the summer comes and the rain falls down on the street, we will dance all "
                          "night with you") == "en"
    assert lexicon.detect("la la la") is None  # too little to tell


def test_months_seasons_and_things_named_in_each_language():
    assert lexicon.months_named("Septiembre llegó volando", "es") == [9]
    assert lexicon.months_named("In July we went to the sea", "en") == [7]
    assert lexicon.months_named("you may come back", "en") == []  # «may» the verb is not a month
    assert lexicon.months_named("Then came May", "en") == [5]
    assert lexicon.season_named("y el verano echó a correr", "es") == "summer"
    assert lexicon.season_named("we fall in love", "en") is None
    assert lexicon.concepts_named("saltaremos los charcos.", "es") == ["puddles"]
    assert lexicon.concepts_named("we start to dance under the stars by the sea", "en") == ["sea", "night"]
    # not known: Spanish and English
    assert lexicon.concepts_named("puddles and charcos", None) == ["puddles"]


def test_cues_use_the_song_language_and_the_lyrics_model():
    slots = [{"lyric": "In August we went camping", "start": 0, "end": 3},
             {"lyric": "the summer came", "start": 3, "end": 6},
             {"lyric": "Wir tanzen im Regen", "start": 6, "end": 9, "line_idx": [0]}]
    c = suggest.slot_cues(slots[:2], [], [], None, "en")
    assert c[0]["month"] == 8 and c[1]["season"] == "summer" and c[0]["lang"] == "en"
    # a language without a module: the lyrics model's month, season and tags still count
    lines = [{"text": "Wir tanzen im Regen", "ai": {"english": "We dance in the rain", "visual": "kids in rain",
                                                   "tags": ["puddle", "umbrella"], "month": 10, "season": "autumn"}}]
    c = suggest.slot_cues([slots[2]], [], [], lines, "nl")
    assert c[0]["month"] == 10 and c[0]["season"] == "autumn"
    assert [t for _, t in c[0]["concepts"]] == ["puddles", "rain"]


def test_older_cues_with_a_spanish_season_still_work():
    assert suggest._season("verano") == "summer" and suggest._season("summer") == "summer"
    assert suggest._season(None) is None


def test_lyrics_language_setting_wins_over_detection():
    p = {"lyrics": "Se cerró la puerta del cole, y el verano echó a correr, con las toallas a la playa de nuestra historia"}
    assert suggest.lyrics_language(p) == "es"
    assert suggest.lyrics_language({**p, "lyrics_lang": "en"}) == "en"
    assert suggest.lyrics_language({**p, "lyrics_lang": "auto"}) == "es"


def test_section_tags_in_each_language():
    assert analyze.parse_section("[Estribillo final]")["kind"] == "chorus"
    assert analyze.parse_section("[Puente – suave]")["kind"] == "bridge"
    assert analyze.parse_section("[Pre-estribillo]")["kind"] == "prechorus"
    assert analyze.parse_section("[Verse 2 – folk]")["kind"] == "verse"


def test_places_in_the_song_language():
    assert "alemania" in suggest._place_words(["Triberg", "Germany"], "es")
    assert "germany" in suggest._place_words(["Triberg", "Germany"], "en")


def test_every_language_module_defines_what_the_engine_reads():
    """The contract of slidesong/languages/<code>.py (copy en.py to add a language)."""
    from slidesong.languages import ALL
    for code, m in ALL.items():
        assert m.CODE == code and m.NAME and m.NLLB.endswith(("_Latn", "_Cyrl", "_Grek", "_Arab", "_Hans", "_Jpan"))
        assert len(m.COMMON_WORDS.split()) >= 20, code
        assert len(m.MONTHS.split()) == 12 and len(m.MONTH_NAMES.split()) == 12, code
        assert all(1 <= n <= 12 for n in m.MONTH_ALIASES.values()) and set(m.AMBIGUOUS_MONTHS) <= set(m.MONTHS.split())
        assert set(m.SEASONS.values()) <= set(lexicon.SEASON_MONTHS), code
        assert set(m.CONCEPTS) <= set(lexicon.CONCEPTS), code
        assert isinstance(m.COUNTRIES, dict) and isinstance(m.PLACE_STOP, set)
        assert set(m.SECTIONS) <= {k for k, _ in lexicon.section_kinds()}, code
        assert isinstance(getattr(m, "TEXTS", {}), dict) and isinstance(getattr(m, "WORDS", {}), dict)
