import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A, learn
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "ensure_plan", lambda pid: {**A.load(pid), "plan": {"shots": [], "boundaries": []}})
    monkeypatch.setattr(A.remote, "available", lambda: None)
    monkeypatch.setattr(learn, "log", lambda *a, **k: None)
    return TestClient(A.app)


def _project(tmp_path, pid="proj1"):
    d = tmp_path / pid
    d.mkdir()
    (d / "song.mp3").write_bytes(b"ID3 fake")
    (d / "renders").mkdir()
    proj = {"id": pid, "title": "Otoño", "pace": "normal", "excluded": [], "people": ["Nico"],
            "song": {"file": "song.mp3", "name": "verano.mp3", "duration": 10},
            "lines": [{"text": "uno", "start": 0, "end": 3}], "renders": [{"file": "a.mp4", "quality": "final"}],
            "jobs": {"render": {"state": "done"}}, "edit_rev": 4,
            "slots": [{"asset": "a", "lyric": "uno", "start": 0, "end": 3, "locked": True, "line_idx": [0]},
                      {"asset": "b", "lyric": "dos", "start": 3, "end": 6, "line_idx": []}],
            "shot_overrides": {"0": "polaroid"}, "captions": {"a": "julio"}}
    (d / "project.json").write_text(json.dumps(proj))
    return pid


def test_a_blocked_project_refuses_edits_but_can_be_unblocked(tmp_path, client):
    pid = _project(tmp_path)
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.5})  # something to undo
    r = client.post(f"/api/projects/{pid}/freeze", json={"on": True}).json()
    assert r["frozen"]["at"]
    for method, url, body in [
        ("patch", "", {"title": "otro"}),
        ("post", "/slots/0", {"action": "unlock"}),
        ("post", "/exchange", {"a": 0, "b": 1}),
        ("post", "/shots/0/move", {"factor": 1.0}),
        ("post", "/undo", None),
        ("post", "/suggest", None),
        ("post", "/analyze", None),
        ("delete", "", None),
    ]:
        resp = getattr(client, method)(f"/api/projects/{pid}{url}", **({"json": body} if body else {}))
        assert resp.status_code == 423, (url, resp.status_code)
    assert client.get(f"/api/projects/{pid}").json()["title"] == "Otoño"
    assert client.post(f"/api/projects/{pid}/freeze", json={"on": False}).json().get("frozen") is None
    assert client.patch(f"/api/projects/{pid}", json={"title": "otro"}).status_code == 200


def test_a_new_version_copies_the_edit_but_not_the_videos(tmp_path, client):
    pid = _project(tmp_path)
    client.post(f"/api/projects/{pid}/freeze", json={"on": True})
    new = client.post(f"/api/projects/{pid}/duplicate", json={"title": "Otoño · abuelos"}).json()["id"]
    q = client.get(f"/api/projects/{new}").json()
    assert q["title"] == "Otoño · abuelos" and q["parent"] == {"id": pid, "title": "Otoño"}
    assert [s["asset"] for s in q["slots"]] == ["a", "b"] and q["slots"][0]["locked"]
    assert q["shot_overrides"] == {"0": "polaroid"} and q["captions"] == {"a": "julio"} and q["people"] == ["Nico"]
    assert q["renders"] == [] and q["jobs"] == {} and not q.get("frozen") and not q.get("edit_rev")
    assert (tmp_path / new / "song.mp3").read_bytes() == b"ID3 fake"
    assert not (tmp_path / new / "song.mp3").samefile(tmp_path / pid / "song.mp3")
    row = next(x for x in client.get("/api/projects").json() if x["id"] == new)
    assert row["parent"] == pid and not row["frozen"]
    assert client.patch(f"/api/projects/{new}", json={"title": "x"}).status_code == 200  # the copy is editable


def test_coverage_counts_photos_not_analysed(tmp_path, client, monkeypatch):
    from slidesong import app as A, scores
    pid = _project(tmp_path)
    monkeypatch.setattr(A, "pool_ids", lambda p: ["x", "y", "z"])
    monkeypatch.setattr(scores, "missing", lambda ids: ["x"])
    monkeypatch.setattr(scores, "untagged", lambda ids: ["y"])
    c = client.get(f"/api/projects/{pid}/coverage").json()
    assert c["pool"] == 3 and c["pending"] == 2 and c["worker"] is False and c["can_analyse"] is False


def test_settings_are_validated(tmp_path, client):
    pid = _project(tmp_path)
    assert client.patch(f"/api/projects/{pid}", json={"date_from": "06/01/2026"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"date_from": ""}).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"title": "x" * 500}).status_code == 422


def test_looking_at_the_plan_does_not_touch_the_project(tmp_path, monkeypatch):
    from slidesong import app as A, plan
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(plan, "build", lambda p: {"shots": [], "boundaries": []})
    monkeypatch.setattr(A, "repeated_photos", lambda p: [])
    pid = _project(tmp_path)
    p = A.load(pid)
    p.update(plan={"shots": [], "boundaries": [], "repeats": []}, updated="2026-11-01T10:00:00")
    A.save(p, touch=False)
    mtime = (tmp_path / pid / "project.json").stat().st_mtime_ns
    A.ensure_plan(pid)  # same plan: nothing to write
    assert (tmp_path / pid / "project.json").stat().st_mtime_ns == mtime
    monkeypatch.setattr(plan, "build", lambda p: {"shots": [{"slots": [0]}], "boundaries": []})
    A.ensure_plan(pid)  # a new plan is saved, but the project is not "updated" (it keeps its place on home)
    q = A.load(pid)
    assert q["plan"]["shots"] == [{"slots": [0]}] and q["updated"] == "2026-11-01T10:00:00"


def test_restart_marks_interrupted_jobs_and_removes_partial_files(tmp_path, monkeypatch):
    from slidesong import app as A
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "DATA", tmp_path)
    pid = _project(tmp_path)
    p = A.load(pid)
    p["jobs"] = {"render": {"state": "running", "progress": 0.4}, "suggest": {"state": "done"}}
    A.save(p)
    (tmp_path / pid / "renders" / "x.part.mp4").write_bytes(b"half")
    A.cleanup_after_restart()
    q = A.load(pid)
    assert q["jobs"]["render"]["state"] == "error" and "restarted" in q["jobs"]["render"]["error"]
    assert q["jobs"]["suggest"]["state"] == "done"
    assert not (tmp_path / pid / "renders" / "x.part.mp4").exists()


def test_video_hash_tells_whether_a_render_is_up_to_date(tmp_path, client):
    pid = _project(tmp_path)
    h0 = client.get(f"/api/projects/{pid}").json()["video_hash"]
    client.patch(f"/api/projects/{pid}", json={"theme": "playa"})  # applies on the next suggestion only
    assert client.get(f"/api/projects/{pid}").json()["video_hash"] == h0
    client.post(f"/api/projects/{pid}/shots/0/move", json={"factor": 0.5})
    assert client.get(f"/api/projects/{pid}").json()["video_hash"] != h0
    client.post(f"/api/projects/{pid}/undo")
    assert client.get(f"/api/projects/{pid}").json()["video_hash"] == h0  # back to what was rendered
    assert client.post(f"/api/projects/{pid}/shots/9/move", json={"factor": 0.5}).status_code == 404
