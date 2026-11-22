import io
import json
import shutil
import subprocess

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A, learn
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "ensure_plan", lambda pid: {**A.load(pid), "plan": {"shots": [], "boundaries": []}})
    monkeypatch.setattr(A.remote, "available", lambda: None)
    monkeypatch.setattr(learn, "log", lambda *a, **k: None)
    d = tmp_path / "proj1"
    d.mkdir()
    (d / "song.mp3").write_bytes(b"OLD SONG")
    proj = {"id": "proj1", "title": "t", "pace": "normal", "excluded": [], "renders": [], "jobs": {},
            "song": {"file": "song.mp3", "name": "a.mp3", "duration": 6}, "lines": [{"text": "uno", "start": 0, "end": 3}],
            "slots": [{"asset": "a", "lyric": "uno", "start": 0, "end": 3, "locked": True, "line_idx": [0]},
                      {"asset": "b", "lyric": "dos", "start": 3, "end": 6, "line_idx": []}]}
    (d / "project.json").write_text(json.dumps(proj))
    yield A, TestClient(A.app), d
    A._running.pop("proj1", None)


def test_no_edits_while_suggest_or_analyze_rewrite_the_shots(env):
    A, c, d = env
    A._running["proj1"] = "suggest"
    r = c.post("/api/projects/proj1/slots/0", json={"action": "unlock"})
    assert r.status_code == 409 and "Choosing photos" in r.json()["detail"]
    assert c.patch("/api/projects/proj1", json={"pace": "fast"}).status_code == 409
    # the job's own write goes through
    A.update("proj1", lambda p: p["slots"][1].update(asset="c"), undo="sugerir las fotos", job=True)
    assert A.load("proj1")["slots"][1]["asset"] == "c"
    A._running["proj1"] = "render"  # a render does not rewrite the shots: editing is fine
    assert c.post("/api/projects/proj1/slots/0", json={"action": "unlock"}).status_code == 200


def test_a_broken_upload_keeps_the_old_song(env):
    A, c, d = env
    c.post("/api/projects/proj1/shots/0/move", json={"factor": 0.5})  # some history
    r = c.post("/api/projects/proj1/song", files={"file": ("nueva.mp3", io.BytesIO(b"not audio"), "audio/mpeg")})
    assert r.status_code == 400
    assert (d / "song.mp3").read_bytes() == b"OLD SONG"
    assert c.get("/api/projects/proj1").json()["history"]["undo"]  # history kept
    assert not list(d.glob("upload*"))


def test_no_upload_while_a_job_runs(env):
    A, c, d = env
    A._running["proj1"] = "analyze"
    r = c.post("/api/projects/proj1/song", files={"file": ("x.mp3", io.BytesIO(b"x"), "audio/mpeg")})
    assert r.status_code == 409


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_new_song_keeps_the_photos_for_the_next_analysis(env, tmp_path):
    A, c, d = env
    wav = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", str(wav)], check=True)
    r = c.post("/api/projects/proj1/song", files={"file": ("nueva.wav", wav.open("rb"), "audio/wav")})
    assert r.status_code == 200, r.text
    p = A.load("proj1")
    assert p["song"]["file"] == "song.wav" and abs(p["song"]["duration"] - 2) < 0.1
    assert p["slots"] == [] and [s["asset"] for s in p["slots_kept"]] == ["a", "b"]
    assert not (d / "song.mp3").exists() and (d / "song.wav").exists()


def test_undo_is_allowed_during_a_render_but_not_during_suggest(env):
    A, c, d = env
    c.post("/api/projects/proj1/shots/0/move", json={"factor": 0.5})
    A._running["proj1"] = "render"
    assert c.post("/api/projects/proj1/undo").status_code == 200
    c.post("/api/projects/proj1/shots/0/move", json={"factor": 0.7})
    A._running["proj1"] = "suggest"
    assert c.post("/api/projects/proj1/undo").status_code == 409


def test_a_double_tap_does_not_reject_the_replacement_too(env):
    A, c, d = env
    p = A.load("proj1")
    p["slots"][1]["alts"] = ["x", "y"]
    A.save(p)
    assert c.post("/api/projects/proj1/slots/1", json={"action": "reject", "expect": "b"}).status_code == 200
    r = c.post("/api/projects/proj1/slots/1", json={"action": "reject", "expect": "b"})  # the second tap
    assert r.status_code == 409 and A.load("proj1")["slots"][1]["asset"] == "x"


def test_pace_before_analysing_does_not_fail(env):
    A, c, d = env
    p = A.load("proj1")
    p["song"] = {"file": "song.mp3", "name": "a.mp3", "duration": 6}  # uploaded, not analysed: no beats
    A.save(p)
    assert c.patch("/api/projects/proj1", json={"pace": "fast"}).status_code == 200


def test_a_blocked_project_keeps_its_plan(tmp_path, monkeypatch):
    from slidesong import app as A, plan
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "repeated_photos", lambda p: [])
    d = tmp_path / "proj2"
    d.mkdir()
    kept = {"shots": [{"slots": [0], "kind": "in"}], "boundaries": []}
    (d / "project.json").write_text(json.dumps({"id": "proj2", "title": "t", "slots": [{"asset": "a"}],
                                                "frozen": {"at": "x"}, "plan": kept}))
    monkeypatch.setattr(plan, "build", lambda p: {"shots": [{"slots": [0], "kind": "out"}], "boundaries": []})
    assert A.ensure_plan("proj2")["plan"] == kept and A.load("proj2")["plan"] == kept
