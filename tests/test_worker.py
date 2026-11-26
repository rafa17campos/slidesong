import importlib
import json

import pytest


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_TOKEN", "slide-tok")
    monkeypatch.setenv("WORKER_TOKENS", "photo-library:lib-tok, other:x-tok")
    monkeypatch.setenv("WORKER_DIR", str(tmp_path))
    monkeypatch.delenv("IMMICH_URL", raising=False)
    monkeypatch.delenv("IMMICH_API_KEY", raising=False)
    monkeypatch.delenv("SLIDESONG_IMAGES_URL", raising=False)
    from slidesong import worker as w
    return importlib.reload(w)


def test_each_client_has_its_own_token(worker):
    assert worker.auth("Bearer slide-tok") == "slidesong"
    assert worker.auth("Bearer lib-tok") == "photo-library"
    with pytest.raises(Exception):
        worker.auth("Bearer nope")


def test_photo_source_per_client(worker, monkeypatch):
    with pytest.raises(Exception):  # no Immich key and no Slidesong to go through
        worker._can_fetch("photo-library")
    monkeypatch.setenv("SLIDESONG_IMAGES_URL", "http://app:8096")
    worker._can_fetch("slidesong")  # through Slidesong: only for Slidesong
    with pytest.raises(Exception):
        worker._can_fetch("photo-library")
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")
    worker._can_fetch("photo-library")  # with its own Immich key, for anyone


def test_scripts_get_immich_as_the_source_when_the_worker_has_a_key(worker, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")
    monkeypatch.setattr(worker, "_venv_python", lambda folder: None)
    calls = {}

    class Proc:
        returncode = 0

        def poll(self):
            return 0

    def popen(cmd, **kw):
        calls["input"] = json.loads(open(cmd[-2], encoding="utf-8").read())
        open(cmd[-1], "w").write("")
        return Proc()
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", popen)
    worker._run_script(tmp_path, "tag.py", [{"id": "a"}], tmp_path, lambda x: None, "r.json")
    assert calls["input"]["immich_url"] == "http://immich:2283" and "images_url" not in calls["input"]


def test_faces_are_looked_up_when_missing(worker, monkeypatch):
    import httpx
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")

    class Resp:
        def json(self):
            return [{"boundingBoxX1": 10, "boundingBoxY1": 20, "boundingBoxX2": 30, "boundingBoxY2": 40,
                     "imageWidth": 100, "imageHeight": 200,
                     "person": {"name": "Nico", "id": "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"}}]

    class Client:
        def __init__(self, **kw):
            pass

        def get(self, path, params=None):
            return Resp()
    monkeypatch.setattr(httpx, "Client", Client)
    items = [{"id": "a"}, {"id": "b", "faces": []}]
    worker._immich_faces(items)
    assert items[0]["faces"] == [{"box": [0.1, 0.1, 0.3, 0.2], "name": "Nico",
                                  "person_id": "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"}] and items[1]["faces"] == []


def test_health_tells_the_scorer_version_and_tagger_model(worker):
    h = worker.health()
    assert h["scorer_version"] == 4 and h["tagger_model"] == "ram_plus_swin_large_14m"
    assert {"ok", "busy", "scorer", "tagger"} <= set(h)


def test_unknown_jobs_are_404(worker):
    for fn in (worker.job, worker.result, worker.cancel, worker.delete):
        with pytest.raises(Exception) as e:
            fn("gone")
        assert getattr(e.value, "status_code", None) == 404


def test_busy_worker_refuses_a_second_job(worker):
    worker._busy.acquire()
    try:
        with pytest.raises(Exception) as e:
            worker._start("tag", lambda d, prog: None)
        assert e.value.status_code == 409
    finally:
        worker._busy.release()


def test_analysers_announce_who_they_are(worker, tmp_path, monkeypatch):
    import json as js
    h = worker.health()
    assert h["scorer_info"] == {"kind": "scorer", "name": "aesthetic-v2.5", "version": 4, "script": "score.py",
                                "local_images": True, "face_focus": {"blurry": 1.6, "soft": 1.8}}
    assert h["tagger_info"]["local_images"] is True
    assert h["scorer_name"] == "aesthetic-v2.5" and h["tagger_info"]["name"] == h["tagger_model"]
    # another scorer: its own folder and manifest (SCORER_DIR)
    (tmp_path / "analyser.json").write_text(js.dumps({"kind": "scorer", "name": "my-scorer", "version": 1,
                                                      "script": "run.py"}))
    monkeypatch.setattr(worker, "SCORER_DIR", tmp_path)
    h = worker.health()
    assert h["scorer_version"] == 1 and h["scorer_name"] == "my-scorer" and h["scorer_info"]["script"] == "run.py"


def test_a_scorer_without_manifest_is_the_reference_one(worker, tmp_path, monkeypatch):
    (tmp_path / "score.py").write_text("VERSION = 2\n")
    monkeypatch.setattr(worker, "SCORER_DIR", tmp_path)
    assert worker.health()["scorer_info"]["name"] == "aesthetic-v2.5"


def test_the_shipped_manifests_match_their_scripts():
    import json as js
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sc = js.loads((root / "scorer" / "analyser.json").read_text())
    assert f"VERSION = {sc['version']}" in (root / "scorer" / "score.py").read_text()
    tg = js.loads((root / "tagger" / "analyser.json").read_text())
    assert f"{tg['name']}.pth" in (root / "tagger" / "tag.py").read_text()
    from slidesong import scores
    assert {k: sc[k] for k in ("name", "version", "face_focus")} == scores.REFERENCE


def test_script_warnings_reach_the_worker_log(worker, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(worker, "_venv_python", lambda folder: None)

    class Proc:
        returncode = 0

        def poll(self):
            return 0

    def popen(cmd, stderr=None, **kw):
        stderr.write(b"W0000 mediapipe chatter\nwarning: the original photos are not allowed\n")
        open(cmd[-1], "w").write("")
        return Proc()
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", popen)
    worker._run_script(tmp_path, "score.py", [{"id": "a"}], tmp_path, lambda x: None, "r.json")
    out = capsys.readouterr().out
    assert "score.py: warning: the original photos are not allowed" in out and "mediapipe" not in out


def test_slidesong_sends_the_person_ids_and_leaves_unknown_faces_to_the_worker(monkeypatch):
    from slidesong import app as A, immich, insights, scores
    pid = "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"
    faces = {"a": [{"boundingBoxX1": 0, "boundingBoxY1": 0, "boundingBoxX2": 50, "boundingBoxY2": 50,
                    "imageWidth": 100, "imageHeight": 100, "person": {"name": "Nico", "id": pid}},
                   {"boundingBoxX1": 50, "boundingBoxY1": 50, "boundingBoxX2": 100, "boundingBoxY2": 100,
                    "imageWidth": 100, "imageHeight": 100, "person": None}]}

    def get(path, id=None, **kw):
        if id not in faces:
            raise immich.httpx.ConnectError("down")
        return faces[id]
    sent = []
    monkeypatch.setattr(immich, "_get", get)
    for a in ("a", "b"):
        immich._faces_cache.pop(a, None)
    monkeypatch.setattr(insights, "pull", lambda ids: None)
    monkeypatch.setattr(A.remote, "available", lambda: {"scorer": True})
    monkeypatch.setattr(A.remote, "score", lambda items, progress=None: sent.extend(items) or [])
    monkeypatch.setattr(scores, "use_scorer", lambda info: None)
    monkeypatch.setattr(scores, "missing", lambda ids: list(ids))
    monkeypatch.setattr(scores, "put", lambda recs: None)
    monkeypatch.setattr(A, "tag_missing", lambda *a, **k: 0)
    try:
        A.score_missing(["a", "b"])
    finally:
        for a in ("a", "b"):
            immich._faces_cache.pop(a, None)
    assert [f["person_id"] for f in sent[0]["faces"]] == [pid, None]
    assert sent[1] == {"id": "b"}  # Immich did not answer: the worker looks its faces up


def _fake_script(monkeypatch, worker, lines_for, seen):
    """Popen standing in for an analyser: writes lines_for(items) and keeps the input it was given."""
    monkeypatch.setattr(worker, "_venv_python", lambda folder: None)

    class Proc:
        returncode = 0

        def poll(self):
            return 0

    def popen(cmd, **kw):
        job = json.loads(open(cmd[-2], encoding="utf-8").read())
        seen.append(job)
        with open(cmd[-1], "w") as f:
            for rec in lines_for(job["items"]):
                f.write(json.dumps(rec) + "\n")
        return Proc()
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", popen)


def _prog():
    got = []

    def prog(x):
        got.append(x)
    prog.check = lambda: None
    prog.got = got
    return prog


def test_video_mode_is_fast_or_deep(worker):
    assert worker._video_mode("") == "fast" and worker._video_mode(None) == "fast"
    assert worker._video_mode("deep") == "deep" and worker._video_mode(" fast ") == "fast"
    with pytest.raises(Exception) as e:
        worker._video_mode("slow")
    assert e.value.status_code == 400


def test_fast_sends_the_analyser_what_it_always_did(worker, monkeypatch, tmp_path):
    seen = []
    _fake_script(monkeypatch, worker, lambda items: [{"id": it["id"], "tags": ["x"]} for it in items], seen)
    monkeypatch.setattr(worker, "_immich_assets", lambda ids: pytest.fail("fast asks Immich nothing more"))
    data = [{"id": "a"}, {"id": "v"}]
    worker._analyse(worker.TAGGER_DIR, "tag", "tag.py", data, tmp_path, _prog(), "fast")
    assert seen[0]["items"] == data
    assert json.loads((tmp_path / "result.json").read_text()) == [{"id": "a", "tags": ["x"]},
                                                                   {"id": "v", "tags": ["x"]}]


def _deep_worker(worker, monkeypatch, tmp_path, frames_of):
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")
    monkeypatch.setattr(worker, "FRAMES", tmp_path / "frames")
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(worker, "_immich_assets", lambda ids: {
        "a": {"type": "IMAGE"}, "v": {"type": "VIDEO", "duration": 12000, "checksum": "c1"},
        "s": {"type": "VIDEO", "duration": 600, "checksum": "c2"}, "x": None})

    def frames(self, asset, checksum, times):
        self.used.add(asset)
        return [(t, f"/frames/{asset}/{t:g}.jpg") for t in frames_of(asset, times)]
    monkeypatch.setattr(worker.videoframes.Extractor, "frames", frames)


def test_deep_expands_videos_into_frames_and_folds_them_back(worker, monkeypatch, tmp_path):
    _deep_worker(worker, monkeypatch, tmp_path, lambda asset, times: times)
    seen = []
    tags = {"a": ["dog"], "v": ["beach"], "v@1": ["beach", "kite"], "v@6": ["kite"], "v@11": ["sea"],
            "s": ["cake"], "x": ["cat"]}
    _fake_script(monkeypatch, worker, lambda items: [{"id": it["id"], "tags": tags[it["id"]]} for it in items], seen)
    data = [{"id": "a"}, {"id": "v"}, {"id": "s"}, {"id": "x"}]
    prog = _prog()
    worker._analyse(worker.TAGGER_DIR, "tag", "tag.py", data, tmp_path, prog, "deep")
    assert [it["id"] for it in seen[0]["items"]] == ["a", "v", "v@1", "v@6", "v@11", "s", "x"]
    assert seen[0]["items"][2] == {"id": "v@1", "image": "/frames/v/1.jpg"}
    assert json.loads((tmp_path / "result.json").read_text()) == [
        {"id": "a", "tags": ["dog"]},
        {"id": "v", "tags": ["beach", "kite"], "video_mode": "deep", "video_frames": 4},
        {"id": "s", "tags": ["cake"], "video_mode": "deep", "video_frames": 1},  # under a second: its preview
        {"id": "x", "tags": ["cat"]}]  # Immich did not say what it is: as in fast
    assert prog.got == [0.15, 0.3]  # each video's frames extracted: the first 30 % of the job


def test_deep_a_video_ffmpeg_cannot_read_falls_back_to_its_preview(worker, monkeypatch, tmp_path, capsys):
    _deep_worker(worker, monkeypatch, tmp_path, lambda asset, times: [])
    seen = []
    _fake_script(monkeypatch, worker, lambda items: [{"id": it["id"], "aesthetic": 5.0, "faces": []}
                                                     for it in items], seen)
    worker._analyse(worker.SCORER_DIR, "score", "score.py", [{"id": "v", "faces": []}], tmp_path, _prog(), "deep")
    assert [it["id"] for it in seen[0]["items"]] == ["v"]
    rec, = json.loads((tmp_path / "result.json").read_text())
    assert rec["video_frames"] == 1 and rec["best_at"] == 0
    assert capsys.readouterr().out.count("warning: video v: ffmpeg could not read it") == 1


def test_deep_falls_back_to_fast_without_the_workers_own_immich_key(worker, monkeypatch, tmp_path, capsys):
    seen = []
    _fake_script(monkeypatch, worker, lambda items: [{"id": it["id"], "tags": []} for it in items], seen)
    monkeypatch.setattr(worker, "_immich_assets", lambda ids: pytest.fail("no key: nothing to ask"))
    worker._analyse(worker.TAGGER_DIR, "tag", "tag.py", [{"id": "v"}], tmp_path, _prog(), "deep")
    assert seen[0]["items"] == [{"id": "v"}]
    assert json.loads((tmp_path / "result.json").read_text()) == [{"id": "v", "tags": []}]
    assert "no Immich key of its own" in capsys.readouterr().out


def test_deep_falls_back_to_fast_with_an_analyser_that_reads_no_local_images(worker, monkeypatch, tmp_path, capsys):
    _deep_worker(worker, monkeypatch, tmp_path, lambda asset, times: times)
    (tmp_path / "analyser.json").write_text(json.dumps({"kind": "tagger", "name": "mine", "script": "run.py"}))
    seen = []
    _fake_script(monkeypatch, worker, lambda items: [{"id": it["id"], "tags": []} for it in items], seen)
    worker._analyse(tmp_path, "tag", "tag.py", [{"id": "v"}], tmp_path, _prog(), "deep")
    assert seen[0]["items"] == [{"id": "v"}] and "local_images" in capsys.readouterr().out


def test_deep_progress_counts_frames_so_a_video_is_still_one_item(worker, monkeypatch, tmp_path):
    _deep_worker(worker, monkeypatch, tmp_path, lambda asset, times: times)
    out = tmp_path / "out.jsonl"

    class Proc:
        returncode = None
        polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 1:  # half the frames done
                with open(out, "w") as f:
                    f.writelines(json.dumps({"id": i, "tags": []}) + "\n" for i in ("v", "v@1"))
                return None
            with open(out, "w") as f:
                f.writelines(json.dumps({"id": i, "tags": []}) + "\n" for i in ("v", "v@1", "v@6", "v@11"))
            self.returncode = 0
            return 0

    import subprocess
    monkeypatch.setattr(worker, "_venv_python", lambda folder: None)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: Proc())
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    prog = _prog()
    worker._analyse(worker.TAGGER_DIR, "tag", "tag.py", [{"id": "v"}], tmp_path, prog, "deep")
    # two videos' frames extracted (0..0.3), then half of the 4 analysed images (0.3..1)
    assert prog.got == pytest.approx([0.15, 0.3, 0.3 + 0.7 * 2 / 4])
    assert json.loads((tmp_path / "result.json").read_text())[0]["video_frames"] == 4


def test_deep_needs_ffprobe_too(worker, monkeypatch, capsys):
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert not worker._deep_ready({"local_images": True}) and "ffprobe" in capsys.readouterr().out
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert worker.health()["video_deep"] is False


def test_deep_does_not_look_up_items_that_say_they_are_photos(worker, monkeypatch, tmp_path):
    _deep_worker(worker, monkeypatch, tmp_path, lambda asset, times: times)
    asked = []
    monkeypatch.setattr(worker, "_immich_assets", lambda ids: asked.extend(ids) or {})
    worker._video_frames([{"id": "a", "type": "IMAGE"}, {"id": "b", "type": "image"}, {"id": "v", "type": "VIDEO"},
                          {"id": "u"}], _prog())
    assert asked == ["v", "u"]


def test_failed_asset_lookups_are_logged_once(worker, monkeypatch, capsys):
    import httpx
    monkeypatch.setattr(worker, "IMMICH", "http://immich:2283")
    monkeypatch.setattr(worker, "IMMICH_KEY", "k")

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {"type": "VIDEO"}

    class Client:
        def __init__(self, **kw):
            pass

        def get(self, path):
            if path.endswith("/x"):
                raise httpx.ConnectError("down")
            return Resp(200 if path.endswith("/ok") else 403)
    monkeypatch.setattr(httpx, "Client", Client)
    out = worker._immich_assets(["ok", "a", "b", "x"])
    assert out["ok"] == {"type": "VIDEO"} and out["a"] is None and out["x"] is None
    log = capsys.readouterr().out
    assert log.count("Immich did not describe 3 of 4 assets") == 1 and "HTTP 403: 2" in log
    assert "ConnectError: 1" in log
