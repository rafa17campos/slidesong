import json
from datetime import datetime

import numpy as np
import pytest

from slidesong import learn, suggest


@pytest.fixture
def tuned(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "TUNING_FILE", tmp_path / "tuning.json")
    monkeypatch.setattr(suggest, "WEIGHTS_FILE", tmp_path / "weights.json")
    monkeypatch.setattr(learn, "EVENTS", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(learn, "DATA", tmp_path)
    monkeypatch.setattr(learn, "STATUS", tmp_path / "learning.json")
    monkeypatch.setattr(learn, "_cue_snapshot", lambda project, i: {"words": [], "lyric": "uno"})
    return tmp_path


def test_levels_multiply_the_weights_for_every_project_and_for_one(tuned):
    suggest.save_tuning({"levels": {"smile": 1, "fav": -2}, "dismissed": []})
    D = suggest.DEFAULT_WEIGHTS
    w = suggest.project_weights({})
    assert w["smile"] == pytest.approx(D["smile"] * 1.75) and w["fav"] == 0 and w["lyric"] == D["lyric"]
    w = suggest.project_weights({"tuning": {"smile": 1, "eyes_closed": 2}})
    assert w["smile"] == pytest.approx(D["smile"] * 1.75 * 1.75)
    assert w["eyes_closed"] == pytest.approx(D["eyes_closed"] * 3) and w["eyes_closed"] < 0  # still a penalty
    # learned weights are the base, unless the project asks for the defaults
    (tuned / "weights.json").write_text(json.dumps({"weights": {"smile": 2.0}}))
    assert suggest.project_weights({})["smile"] == pytest.approx(2.0 * 1.75)
    assert suggest.project_weights({"learned": False})["smile"] == pytest.approx(D["smile"] * 1.75)


def test_unknown_levels_in_the_file_are_ignored(tuned):
    (tuned / "tuning.json").write_text(json.dumps({"levels": {"smile": 7, "nope": 1, "fav": -1}}))
    assert suggest.tuning()["levels"] == {"fav": -1}


def test_avoid_pushes_down_photos_that_look_like_it(monkeypatch):
    rng = np.random.default_rng(0)
    emb = rng.normal(size=(200, 64))
    beach = emb[3] / np.linalg.norm(emb[3])
    monkeypatch.setattr(suggest.immich, "text_embedding", lambda t, *a: beach if t == "playa" else -beach)
    monkeypatch.setattr(suggest.geo, "place_words", lambda latlons: [set() for _ in latlons])
    ids = [f"a{i}" for i in range(200)]
    dates = [datetime(2026, 1, 1)] * 200
    favs = np.zeros(200, bool)
    plain = suggest.Pool(ids, dates, favs, emb, [], None, weights=dict(suggest.DEFAULT_WEIGHTS))
    avoid = suggest.Pool(ids, dates, favs, emb, [], None, weights=dict(suggest.DEFAULT_WEIGHTS), avoid="playa")
    assert avoid.base[3] < plain.base[3] - 2  # the beach photo goes well down
    far = int(np.argmin(emb @ beach))
    assert avoid.base[far] == plain.base[far]  # an unlike photo is untouched
    assert "🚫 looks like playa" in avoid.why(3, {"words": set(), "people": [], "month": None}, 0)
    assert suggest.avoid_terms("playa, piscina;\nnieve,") == ["playa", "piscina", "nieve"]


def test_a_removed_correction_does_not_come_back(tuned):
    p = {"id": "p1", "slots": [{"asset": "a", "alts": ["x", "y"], "locked": True}]}
    learn.bootstrap([p])  # a pinned photo becomes a correction
    [e] = learn.events()
    assert learn.remove(e["ts"], "p1")["new"] == "a"
    assert learn.events() == []
    assert learn.bootstrap([p]) == 0  # not imported again from the pin
    learn.log_accepted({**p, "slots": [{"asset": "a", "alts": ["x"], "locked": False}]})
    assert learn.events() == []  # nor from a final render
    assert learn.remove("nope", "p1") is None


def test_a_project_that_does_not_teach_logs_nothing(tuned):
    p = {"id": "p1", "teaches": False, "slots": [{"asset": "a", "alts": ["x"], "locked": True}]}
    learn.log(p, 0, "set", new="a", old="x")
    learn.log_accepted(p)
    assert learn.bootstrap([p]) == 0 and learn.events() == []


@pytest.fixture
def client(tuned, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A
    projects = tuned / "projects"
    projects.mkdir()
    monkeypatch.setattr(A, "PROJECTS", projects)
    monkeypatch.setattr(A, "relearn_later", lambda force=False: None)
    d = projects / "proj1"
    d.mkdir()
    (d / "project.json").write_text(json.dumps({"id": "proj1", "title": "Invierno", "slots": [
        {"asset": "a", "alts": ["x"], "start": 0, "end": 3}], "lines": []}))
    return TestClient(A.app), d


def test_learning_api(client):
    c, d = client
    assert c.put("/api/learning/levels", json={"levels": {"smile": 9}}).status_code == 400
    r = c.put("/api/learning/levels", json={"levels": {"smile": 1, "fav": 0}}).json()
    assert {s["key"]: s["level"] for s in r["signals"]}["smile"] == 1
    assert suggest.tuning()["levels"] == {"smile": 1}  # «Normal» is not stored
    p = json.loads((d / "project.json").read_text())
    learn.log(p, 0, "set", new="b", old="a", source="alts")
    learn.log(p, 0, "accept", new="b", source="final")
    ev = c.get("/api/learning/events").json()
    assert ev["total"] == 1 and ev["events"][0]["title"] == "Invierno" and ev["events"][0]["lyric"] == "uno"
    assert c.get("/api/learning/events?accepted=true").json()["total"] == 2
    assert c.get("/api/learning/detail").json()["projects"][0]["corrections"] == 1
    # taking the project out forgets what it taught
    assert c.post("/api/learning/projects/proj1", json={"on": False}).json()["forgotten"] == 2
    assert learn.events() == [] and json.loads((d / "project.json").read_text())["teaches"] is False
    assert c.delete("/api/learning/events", params={"ts": "x", "project": "proj1"}).status_code == 404


def test_project_tuning_and_avoid_are_settings_with_undo(client):
    c, d = client
    assert c.patch("/api/projects/proj1", json={"tuning": {"lyric": 5}}).status_code == 400
    r = c.patch("/api/projects/proj1", json={"tuning": {"lyric": 2, "fav": 0}, "avoid": "playa"}).json()
    assert r["tuning"] == {"lyric": 2} and r["avoid"] == "playa"
    c.post("/api/projects/proj1/undo")
    q = json.loads((d / "project.json").read_text())
    assert "tuning" not in q and "avoid" not in q


def test_reset_one_project_or_everything(tuned):
    a = {"id": "pa", "slots": [{"asset": "a", "alts": ["x"], "locked": True}]}
    b = {"id": "pb", "slots": [{"asset": "b", "alts": ["y"], "locked": True}]}
    learn.bootstrap([a, b])
    learn.log(a, 0, "accept", new="a", source="pin")
    assert learn.reset([a, b], only="pa") == 2
    assert [e["project"] for e in learn.events()] == ["pb"]
    assert learn.bootstrap([a, b]) == 0  # its pins are not imported again
    assert list(tuned.glob("feedback.jsonl.reset-*"))  # what was forgotten is kept aside
    (tuned / "weights.json").write_text("{}")
    (tuned / "learning.json").write_text("{}")
    assert learn.reset([a, b]) == 1
    assert learn.events() == [] and learn.bootstrap([a, b]) == 0
    assert not (tuned / "weights.json").exists() and not (tuned / "learning.json").exists()
    learn.log(b, 0, "set", new="c", old="b")  # new corrections count again
    assert len(learn.events()) == 1


def test_reset_api(client):
    c, d = client
    p = json.loads((d / "project.json").read_text())
    learn.log(p, 0, "set", new="b", old="a")
    assert c.post("/api/learning/reset", json={"project": "../x"}).status_code == 404
    assert c.post("/api/learning/reset", json={"project": "proj1"}).json()["forgotten"] == 1
    assert c.post("/api/learning/reset", json={}).json()["forgotten"] == 0
