from slidesong import lyrics_llm, suggest


def test_line_ai_matches_text_and_nearest_time():
    lines = [{"text": "Hojas secas en la acera,", "start": 10, "ai": {"visual": "first"}},
             {"text": "Hojas secas en la acera,", "start": 90, "ai": {"visual": "second"}},
             {"text": "otra", "start": 12}]
    assert suggest._line_ai({"lyric": "Hojas secas en la acera,", "start": 88}, lines)["visual"] == "second"
    assert suggest._line_ai({"lyric": "otra", "start": 12}, lines) is None


def test_cues_carry_ai_reading_and_tags():
    lines = [{"text": "Si mañana llueve fuerte,", "start": 0, "ai": {"english": "If it rains hard tomorrow,",
              "visual": "kids jumping in puddles in rain boots", "tags": ["puddles", "rain boot"]}}]
    c = suggest.slot_cues([{"lyric": "Si mañana llueve fuerte,", "start": 0, "end": 3}], [], [], lines)[0]
    assert c["en"] == "If it rains hard tomorrow," and "puddles" in c["visual"]
    assert {"puddles", "rain boot"} <= set(c["ram_tags"])


def test_tag_normalisation():
    assert suggest._tag_norm("Puddles") == suggest._tag_norm("puddle")
    assert suggest._tag_norm("grass") == "grass"


def test_annotate_falls_back_without_api(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr(lyrics_llm.translate, "available", lambda: False)
    out = lyrics_llm.annotate(["hola", "adiós"])
    assert len(out) == 2 and all(o["source"] == "local" for o in out)
    assert lyrics_llm.annotate([]) == []


def test_common_tags_are_ignored():
    import numpy as np
    pool = suggest.Pool.__new__(suggest.Pool)
    pool.tags = [{"boy", "puddle"}] + [{"boy"}] * 99
    pool.tag_df = {"boy": 1.0, "puddle": 0.01}
    cue = {"ram_tags": ["boys", "puddles"]}
    assert pool.wanted_tags(cue) == {"puddle"}


def test_project_can_ignore_learned_weights():
    assert suggest.project_weights({"learned": False}) == suggest.DEFAULT_WEIGHTS
