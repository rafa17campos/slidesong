from slidesong import scores


def test_blur_uses_face_focus_only_when_judged():
    rec = {"faces": [{"found": True, "name": "A", "box": [0, 0, .3, .3], "focus": 1.5, "sharp": 3.1}]}
    assert scores.face_summary(rec, {"A"})["blurry"] == 1
    rec["faces"][0]["focus"] = 1.7
    assert scores.face_summary(rec, {"A"})["blurry"] == 0.5
    rec["faces"][0]["focus"] = 2.1
    assert not scores.face_summary(rec, {"A"})["blurry"]
    rec["faces"][0]["focus"] = None  # face too small to judge
    assert not scores.face_summary(rec, {"A"})["blurry"]


def test_rescoring_keeps_tags():
    scores.put([{"id": "t-keep", "aesthetic": 5, "tags": ["puddle"]}])
    scores.put([{"id": "t-keep", "aesthetic": 6}])
    assert scores.get(["t-keep"])["t-keep"]["tags"] == ["puddle"]


def _fresh(tmp_path, monkeypatch):
    from slidesong import scores
    monkeypatch.setattr(scores, "DB", tmp_path / "scores.sqlite")
    monkeypatch.setattr(scores, "ACTIVE", tmp_path / "scorer.json")
    monkeypatch.setattr(scores, "_active", {"mtime": None, "info": scores.REFERENCE})
    return scores


def test_records_belong_to_the_scorer_that_made_them(tmp_path, monkeypatch):
    scores = _fresh(tmp_path, monkeypatch)
    scores.put([{"id": "a", "aesthetic": 5.0}])
    assert "a" in scores.get(["a"])
    scores.use_scorer({"name": "my-scorer", "version": 1, "face_focus": {"blurry": 10, "soft": 20}})
    assert scores.get(["a"]) == {} and scores.missing(["a"]) == ["a"]  # scored again, never mixed
    scores.put([{"id": "a", "aesthetic": 0.7}])
    assert scores.get(["a"])["a"]["aesthetic"] == 0.7
    scores.use_scorer(scores.REFERENCE)  # back: one record per photo, so scored again with this one
    assert scores.missing(["a"]) == ["a"]


def test_face_sharpness_uses_the_scorers_own_thresholds(tmp_path, monkeypatch):
    scores = _fresh(tmp_path, monkeypatch)
    assert scores._blur([1.5]) == 1.0 and scores._blur([1.7]) == 0.5 and scores._blur([2.0]) == 0.0
    scores.use_scorer({"name": "other", "version": 1, "face_focus": {"blurry": 0.3, "soft": 0.5}})
    assert scores._blur([0.4]) == 0.5 and scores._blur([1.5]) == 0.0
    scores.use_scorer({"name": "no-faces", "version": 1})  # a scorer that does not judge sharpness
    assert scores._blur([0.1]) == 0.0


def test_older_databases_are_the_version_2_reference_scorers(tmp_path, monkeypatch):
    import json as js
    import sqlite3
    scores = _fresh(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "scores.sqlite") as c:
        c.execute("create table scores (id text primary key, v integer, data text, updated text)")
        c.execute("insert into scores values ('a', 2, ?, 'x')", (js.dumps({"id": "a", "aesthetic": 5.0}),))
        c.execute("insert into scores values ('b', 1, ?, 'x')", (js.dumps({"id": "b", "aesthetic": 4.0}),))
    c.close()
    assert scores.get(["a", "b"]) == {}  # the reference scorer is version 3 now: scored again
    scores.use_scorer(scores.UNNAMED)
    assert set(scores.get(["a", "b"])) == {"a"}  # version 1 was already out of date


def test_version_2_records_without_faces_are_kept_for_version_3(tmp_path, monkeypatch):
    scores = _fresh(tmp_path, monkeypatch)
    scores.put([{"id": "land", "v": 2, "aesthetic": 5.0, "faces": [], "tags": ["sea"]},
                {"id": "kids", "v": 2, "aesthetic": 6.0, "faces": [{"box": [0, 0, .1, .1], "found": True}]}],
               scores.UNNAMED)
    assert scores.missing(["land", "kids", "new"]) == ["kids", "new"]  # only faces changed in version 3
    assert scores.get(["land"])["land"] == {"id": "land", "v": 3, "aesthetic": 5.0, "faces": [], "tags": ["sea"]}
    scores.use_scorer({"name": "other", "version": 1})  # another scorer: nothing carried over
    assert scores.missing(["land"]) == ["land"]
