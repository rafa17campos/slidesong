import json

import pytest

from slidesong import history, learn


def _project(tmp_path, pid="proj1", **extra):
    (tmp_path / pid).mkdir()
    proj = {"id": pid, "title": "t", "pace": "normal", "excluded": [], "lines": [{"text": "uno"}, {"text": "dos"}],
            "slots": [{"asset": "a", "lyric": "uno", "start": 0, "end": 3, "line_idx": [0]},
                      {"asset": "b", "lyric": "dos", "start": 3, "end": 6, "line_idx": [1]}],
            **extra}
    (tmp_path / pid / "project.json").write_text(json.dumps(proj))
    return pid


def test_snapshot_restore_roundtrip():
    p = {"title": "a", "slots": [{"asset": "x"}], "lines": [{"text": "l", "sub": True}, {"text": "m"}]}
    s = history.snapshot(p)
    p.update(title="b", move={"0": 0.5})
    p["slots"][0]["asset"] = "y"
    p["lines"][0].pop("sub")
    p["lines"][1]["sub"] = False
    history.restore(p, s)
    assert p["title"] == "a" and p["slots"][0]["asset"] == "x" and "move" not in p
    assert p["lines"][0]["sub"] is True and "sub" not in p["lines"][1]


def test_runs_on_one_control_merge(tmp_path):
    history.push(tmp_path, "mover", {"title": "0"}, key="move:1")
    history.push(tmp_path, "mover", {"title": "1"}, key="move:1")
    history.push(tmp_path, "otro", {"title": "2"}, key="move:2")
    h = history.read(tmp_path)
    assert [e["state"]["title"] for e in h["undo"]] == ["0", "2"]  # the state before the first edit is kept


def test_new_edit_clears_redo(tmp_path):
    p = {"title": "b"}
    history.push(tmp_path, "uno", history.snapshot({"title": "a"}))
    history.step(tmp_path, p, "undo")
    assert history.summary(tmp_path) == {"undo": None, "redo": "uno"}
    history.push(tmp_path, "dos", history.snapshot(p))
    assert history.summary(tmp_path)["redo"] is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "ensure_plan", lambda pid: {**A.load(pid), "plan": {"shots": [], "boundaries": []}})
    monkeypatch.setattr(A.remote, "available", lambda: None)
    monkeypatch.setattr(learn, "log", lambda *a, **k: None)
    return TestClient(A.app)


def test_undo_redo_through_the_api(tmp_path, client):
    pid = _project(tmp_path)
    r = client.post(f"/api/projects/{pid}/exchange", json={"a": 0, "b": 1}).json()
    assert [s["asset"] for s in r["slots"]] == ["b", "a"]
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.4})
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.8})  # same slider: one step
    p = client.get(f"/api/projects/{pid}").json()
    assert p["history"] == {"undo": "change the movement of shot 1", "redo": None}

    r = client.post(f"/api/projects/{pid}/undo").json()
    assert r["undone"] == "change the movement of shot 1" and r.get("move", {}) == {}
    r = client.post(f"/api/projects/{pid}/undo").json()
    assert [s["asset"] for s in r["slots"]] == ["a", "b"] and not any(s.get("locked") for s in r["slots"])
    assert r["history"] == {"undo": None, "redo": "swap shots 1 and 2"}
    assert client.post(f"/api/projects/{pid}/undo").status_code == 409

    r = client.post(f"/api/projects/{pid}/redo").json()
    assert [s["asset"] for s in r["slots"]] == ["b", "a"]


def test_settings_undo_and_unchanged_edits_are_not_recorded(tmp_path, client):
    pid = _project(tmp_path)
    client.patch(f"/api/projects/{pid}", json={"title": "Nuevo"})
    client.patch(f"/api/projects/{pid}", json={"title": "Nuevo"})  # no change: still one step
    p = client.get(f"/api/projects/{pid}").json()
    assert p["history"]["undo"] == "change the title"
    r = client.post(f"/api/projects/{pid}/undo").json()
    assert r["title"] == "t" and r["history"]["undo"] is None


def test_undo_forgets_what_the_edit_taught(tmp_path, monkeypatch):
    monkeypatch.setattr(learn, "EVENTS", tmp_path / "feedback.jsonl")
    lines = [{"project": "p1", "n": 0}, {"project": "p2", "n": 1}, {"project": "p1", "n": 2}]
    learn.EVENTS.write_text("".join(json.dumps(e) + "\n" for e in lines))
    assert learn.forget("p1", 1) == 1
    assert [e["n"] for e in learn.events()] == [0, 1]  # other projects' and older corrections stay


def test_edits_are_counted_for_the_stale_video_notice(tmp_path, client):
    pid = _project(tmp_path)
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.4})
    client.post(f"/api/projects/{pid}/slots/1/subs", json={"on": True})
    assert client.get(f"/api/projects/{pid}").json()["edit_rev"] == 2
    assert client.post(f"/api/projects/{pid}/undo").json()["edit_rev"] == 3  # an undo changes the video too


def test_line_subtitle_toggle(tmp_path, client):
    pid = _project(tmp_path)
    r = client.post(f"/api/projects/{pid}/lines/1/sub", json={"on": True}).json()
    assert r["lines"][1]["sub"] is True
    assert client.get(f"/api/projects/{pid}").json()["history"]["undo"] == "add the subtitle of a line"
    assert client.post(f"/api/projects/{pid}/lines/9/sub", json={"on": True}).status_code == 404


def test_project_list_says_where_each_project_is(tmp_path, client):
    pid = _project(tmp_path)
    row = next(x for x in client.get("/api/projects").json() if x["id"] == pid)
    assert row["photos"] == 2 and row["finals"] == 0 and row["running"] is None and row["song"] is False


def test_toast_undo_only_undoes_its_own_edit(tmp_path, client):
    pid = _project(tmp_path)
    r = client.post(f"/api/projects/{pid}/slots/0", json={"action": "lock"}).json()
    rev = r["edit_rev"]
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.4})  # another edit after it
    resp = client.post(f"/api/projects/{pid}/undo?expect_rev={rev}")
    assert resp.status_code == 409 and "another change" in resp.json()["detail"]
    r2 = client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.6})
    rev2 = client.get(f"/api/projects/{pid}").json()["edit_rev"]
    assert client.post(f"/api/projects/{pid}/undo?expect_rev={rev2}").status_code == 200
