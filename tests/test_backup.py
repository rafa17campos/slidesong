import io
import json
import sqlite3
import zipfile

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A, learn, scores
    data = tmp_path / "data"
    projects = data / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(A, "DATA", data)
    monkeypatch.setattr(A, "PROJECTS", projects)
    monkeypatch.setattr(A, "BACKUP_TMP", data / "cache" / "backup")
    monkeypatch.setattr(A, "BACKUP_LAST", data / "backup.json")
    monkeypatch.setattr(scores, "DB", data / "scores.sqlite")
    (data / "feedback.jsonl").write_text('{"ts": 1, "project": "pr1"}\n')
    (data / "learning.json").write_text('{"events": 1}')
    with sqlite3.connect(data / "scores.sqlite") as c:
        c.execute("create table scores (id text primary key, v integer, data text, updated text)")
        c.execute("insert into scores values ('a', 2, '{}', 'x')")
    c.close()
    for pid in ("pr1", "pr2"):
        d = projects / pid
        (d / "renders").mkdir(parents=True)
        (d / "snips").mkdir()
        (d / "song.mp3").write_bytes(b"ID3 song " + pid.encode())
        (d / "history.json").write_text('{"undo": [], "redo": []}')
        (d / "renders" / "v.mp4").write_bytes(b"video" * 100)
        (d / "renders" / "old.mp4").write_bytes(b"not listed")
        (d / "snips" / "s.mp4").write_bytes(b"snippet")
        (d / "project.json").write_text(json.dumps({
            "id": pid, "title": f"Título {pid}", "song": {"file": "song.mp3"},
            "renders": [{"file": "v.mp4", "quality": "final"}], "slots": []}))
    return TestClient(A.app), data


def _zip(r):
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_a_whole_backup_has_what_cannot_be_made_again_laid_out_like_the_data_folder(env):
    client, data = env
    r = client.get("/api/backup")
    assert r.headers["content-disposition"].startswith('attachment; filename="slidesong-backup-')
    z = _zip(r)
    names = set(z.namelist())
    assert names == {
        "backup-manifest.json", "feedback.jsonl", "learning.json", "scores.sqlite",
        *(f"projects/{p}/{f}" for p in ("pr1", "pr2") for f in ("project.json", "history.json", "song.mp3")),
    }  # no videos by default, never snippets, caches or renders the project does not list
    m = json.loads(z.read("backup-manifest.json"))
    assert m["whole"] and not m["videos"] and [p["id"] for p in m["projects"]] == ["pr1", "pr2"]
    assert z.read("projects/pr2/song.mp3") == b"ID3 song pr2"
    # the temporary zip is gone once sent, and the home page knows when the last copy was made
    assert not list((data / "cache" / "backup").iterdir())
    assert json.loads((data / "backup.json").read_text())["projects"] == 2


def test_videos_go_in_only_when_asked(env):
    client, _ = env
    z = _zip(client.get("/api/backup?videos=true"))
    assert "projects/pr1/renders/v.mp4" in z.namelist()
    assert "projects/pr1/renders/old.mp4" not in z.namelist()
    assert z.getinfo("projects/pr1/renders/v.mp4").compress_type == zipfile.ZIP_STORED


def test_one_project_backup(env):
    client, data = env
    z = _zip(client.get("/api/backup?project=pr2"))
    assert {n for n in z.namelist() if n != "backup-manifest.json"} == {
        "projects/pr2/project.json", "projects/pr2/history.json", "projects/pr2/song.mp3"}
    assert not (data / "backup.json").exists()  # not a whole copy
    assert client.get("/api/backup?project=nope").status_code == 404
    assert client.get("/api/backup?project=../x").status_code == 404


def test_the_backup_checks_out_and_restores_by_unzipping(env, tmp_path):
    from slidesong import backup
    client, data = env
    f = tmp_path / "b.zip"
    f.write_bytes(client.get("/api/backup?videos=true").content)
    assert backup.verify(f) == []
    restored = tmp_path / "restored"
    zipfile.ZipFile(f).extractall(restored)
    for rel in ("projects/pr1/project.json", "projects/pr1/renders/v.mp4", "feedback.jsonl"):
        assert (restored / rel).read_bytes() == (data / rel).read_bytes()
    with sqlite3.connect(restored / "scores.sqlite") as c:
        assert c.execute("select id from scores").fetchall() == [("a",)]
    c.close()
    # a damaged file is caught
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(f) as zi, zipfile.ZipFile(bad, "w") as zo:
        for i in zi.infolist():
            zo.writestr(i, b"x" if i.filename == "feedback.jsonl" else zi.read(i))
    assert backup.verify(bad) == ["feedback.jsonl no coincide"]


def test_info_sizes(env):
    client, _ = env
    i = client.get("/api/backup/info").json()
    assert i["projects"] == 2 and i["videos_size"] == 1000 and i["size"] > 0 and i["last"] is None
