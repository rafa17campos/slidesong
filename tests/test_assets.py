from fastapi.testclient import TestClient

VID, PHOTO = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def test_the_worker_gets_originals_of_photos_but_never_of_videos(monkeypatch):
    from slidesong import app as A
    monkeypatch.setattr(A.remote, "TOKEN", "tok")
    monkeypatch.setattr(A.immich, "_info_one", lambda aid: {"type": "VIDEO" if aid == VID else "IMAGE"})
    fetched = []
    monkeypatch.setattr(A.immich, "fetch", lambda aid, kind: fetched.append(aid) or (b"jpeg", "image/jpeg"))
    c, auth = TestClient(A.app), {"Authorization": "Bearer tok"}
    assert c.get(f"/api/assets/{PHOTO}/original").status_code == 401  # worker only
    assert c.get(f"/api/assets/{PHOTO}/original", headers=auth).content == b"jpeg"
    assert c.get(f"/api/assets/{VID}/original", headers=auth).status_code == 404
    assert fetched == [PHOTO]  # the video was never pulled from Immich
