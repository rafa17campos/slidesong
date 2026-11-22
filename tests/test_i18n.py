import json

import pytest

from slidesong import i18n


@pytest.fixture
def es():
    token = i18n.LANG.set("es")
    yield
    i18n.LANG.reset(token)


def test_messages_follow_the_language(es):
    assert i18n.tr("Project not found") == "Proyecto no encontrado"
    assert i18n.tr("Wait until «{job}» finishes", job="Choosing photos") == "Espera a que termine «Eligiendo fotos»"
    assert i18n.tr("something new") == "something new"  # not in the table yet: English


def test_english_is_the_default():
    assert i18n.lang() == "en" and i18n.tr("Project not found") == "Project not found"


def test_stored_texts_read_in_either_language(es):
    assert i18n.localize("change the photo of shot 4") == "cambiar la foto del plano 4"
    assert i18n.localize("📅 July") == "📅 julio"
    assert i18n.localize("⚠️ in swimwear") == "⚠️ en bañador"
    assert i18n.localize("change the theme and the people") == "cambiar el tema y las personas"
    assert i18n.localize("new verse") == "nueva estrofa" and i18n.localize("new chorus") == "nuevo estribillo"
    assert i18n.localize("📍 Teruel") == "📍 Teruel"  # unknown: as it is


def test_older_spanish_texts_read_in_english():
    assert i18n.localize("cambiar la foto del plano 4") == "change the photo of shot 4"
    assert i18n.localize("🎵 encaja con la letra") == "🎵 fits the lyrics"
    assert i18n.localize("⚠️ sin camiseta") == "⚠️ shirtless"
    assert i18n.localize("Se interrumpió al reiniciarse Montaje") == "Interrupted when Slidesong restarted"
    assert i18n.localize("empieza el estrofa, más íntimo") == "the verse begins, more intimate"
    assert i18n.localize(None) is None


def test_every_translation_fills_the_same_placeholders():
    import re
    for code, texts in i18n.TEXTS.items():
        for en, tx in texts.items():
            assert sorted(re.findall(r"\{(\w+)\}", en)) == sorted(re.findall(r"\{(\w+)\}", tx)), (code, en)


def test_interface_languages_come_from_the_language_modules():
    from slidesong.languages import ALL, INTERFACE
    assert INTERFACE == ["en", "es"] and set(ALL) == {"en", "es"}
    i18n.use("fr-FR,es;q=0.8,en;q=0.5")  # the first one this server speaks
    assert i18n.lang() == "es"
    i18n.use("de")
    assert i18n.lang() == "en"


def test_the_api_answers_in_the_language_asked(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from slidesong import app as A, learn
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(A, "ensure_plan", lambda pid: {**A.load(pid), "plan": {"shots": [], "boundaries": []}})
    monkeypatch.setattr(learn, "log", lambda *a, **k: None)
    (tmp_path / "proj1").mkdir()
    (tmp_path / "proj1" / "project.json").write_text(json.dumps({
        "id": "proj1", "title": "t", "lines": [], "excluded": [],
        "slots": [{"asset": "a", "start": 0, "end": 3, "why": {"a": ["🎵 encaja con la letra", "⭐ favorite"]}}],
        "jobs": {"render": {"state": "error", "error": "ffmpeg failed"}}}))
    c = TestClient(A.app)
    c.post("/api/projects/proj1/shots/0/move", json={"factor": 0.5})
    en = c.get("/api/projects/proj1").json()
    es = c.get("/api/projects/proj1", headers={"Accept-Language": "es-ES,es;q=0.9"}).json()
    assert en["history"]["undo"] == "change the movement of shot 1"
    assert es["history"]["undo"] == "cambiar el movimiento del plano 1"
    assert en["slots"][0]["why"]["a"] == ["🎵 fits the lyrics", "⭐ favorite"]
    assert es["slots"][0]["why"]["a"] == ["🎵 encaja con la letra", "⭐ favorita"]
    assert es["jobs"]["render"]["error"] == "ffmpeg falló"
    assert c.get("/api/projects/nope-x", headers={"Accept-Language": "es"}).json()["detail"] == "Proyecto no encontrado"
    # stored as written: the project file keeps the original texts
    assert json.loads((tmp_path / "proj1" / "project.json").read_text())["slots"][0]["why"]["a"][0] == "🎵 encaja con la letra"


def test_old_host_names_redirect(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slidesong.app import HostRedirects
    inner = FastAPI()
    inner.get("/x")(lambda: {"ok": True})
    inner.add_middleware(HostRedirects, redirects={"old.example.com": "new.example.com"})
    c = TestClient(inner)
    r = c.get("/p/a/storyboard?shot=3", headers={"host": "old.example.com"}, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "https://new.example.com/p/a/storyboard?shot=3"
    assert c.post("/api/x", headers={"host": "OLD.example.com:443"}, follow_redirects=False).status_code == 308
    assert c.get("/x", headers={"host": "new.example.com"}).json() == {"ok": True}
