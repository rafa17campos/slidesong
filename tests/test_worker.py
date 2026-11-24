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
                     "imageWidth": 100, "imageHeight": 200, "person": {"name": "Nico"}}]

    class Client:
        def __init__(self, **kw):
            pass

        def get(self, path, params=None):
            return Resp()
    monkeypatch.setattr(httpx, "Client", Client)
    items = [{"id": "a"}, {"id": "b", "faces": []}]
    worker._immich_faces(items)
    assert items[0]["faces"] == [{"box": [0.1, 0.1, 0.3, 0.2], "name": "Nico"}] and items[1]["faces"] == []


def test_health_tells_the_scorer_version_and_tagger_model(worker):
    h = worker.health()
    assert h["scorer_version"] == 3 and h["tagger_model"] == "ram_plus_swin_large_14m"
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
    assert h["scorer_info"] == {"kind": "scorer", "name": "aesthetic-v2.5", "version": 3, "script": "score.py",
                                "face_focus": {"blurry": 1.6, "soft": 1.8}}
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
