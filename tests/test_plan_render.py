import numpy as np

from slidesong import plan, render


def test_pick_chapters_only_biggest_local_jumps():
    jumps = [0.1, 1.5, 0.2, 1.2, 0.3, 0.1, 0.1, 0.1, 2.0]
    assert plan.pick_chapters(jumps, window=2) == {1, 8}


def test_layout_video_and_landscape(monkeypatch):
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: True)
    slots = [{"asset": "a", "start": 0, "end": 3}, {"asset": "b", "start": 3, "end": 6},
             {"asset": "c", "start": 6, "end": 9}]
    metas = [{"aspect": 1.5}, {"aspect": 0.75, "video": True, "duration": 10}, {"aspect": 1.33}]
    shots = plan.layout(slots, metas)
    assert [s["kind"] for s in shots][1] == "video"
    v = shots[1]
    assert abs((v["clip_start"] + v["clip_end"]) / 2 - 5) < 0.01  # centre of the clip


def test_layout_pairs_portraits_into_diptych(monkeypatch):
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: True)
    slots = [{"asset": x, "start": 3 * k, "end": 3 * k + 3} for k, x in enumerate("abc")]
    metas = [{"aspect": 1.5}, {"aspect": 0.75}, {"aspect": 0.75}]
    assert [s["kind"] for s in plan.layout(slots, metas)][-1] == "diptych"


def test_compose_transitions_shapes_and_ends():
    a = np.full((90, 160, 3), 10, np.uint8)
    b = np.full((90, 160, 3), 200, np.uint8)
    for kind in ("fade", "dipwhite", "dipblack", "zoom", "push"):
        out = render.compose(kind, 0.5, a, b, "left")
        assert out.shape == a.shape and out.dtype == np.uint8
    assert (render.compose("push", 1.0, a, b, "left") == b).all()
    assert (render.compose("fade", 0.0, a, b) == a).all()


def test_layout_respects_user_clip_start(monkeypatch):
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: True)
    slots = [{"asset": "v", "start": 0, "end": 3, "clip_start": 7.0}]
    v = plan.layout(slots, [{"aspect": 1.78, "video": True, "duration": 9}])[0]
    assert v["clip_start"] == 6.0 and v["clip_end"] == 9.0  # clamped so the whole shot fits in the clip
    slots[0]["clip_start"] = 2.0
    assert plan.layout(slots, [{"aspect": 1.78, "video": True, "duration": 9}])[0]["clip_start"] == 2.0



def test_every_transition_composes_any_direction():
    import numpy as np
    from slidesong import plan, render
    a = np.zeros((90, 160, 3), np.uint8)
    b = np.full((90, 160, 3), 200, np.uint8)
    for k in plan.KINDS:
        if k in ("cut", "flash"):
            continue
        for d in ("left", "right", "up", "down"):
            for p in (0.0, np.float64(0.5), 1.0):
                f = render.compose(k, p, a, b, d)
                assert f.shape == a.shape and f.dtype == np.uint8, (k, d, p)
        assert render.compose(k, 1.0, a, b, "left").mean() > 150, k  # ends on the incoming shot


def test_subtitles_choice_and_timing():
    from slidesong import app
    p = {"subtitles": "some", "song": {"duration": 20}, "lines": [
        {"text": "uno", "start": 1.0, "end": 2.0, "sub": True}, {"text": "dos", "start": 2.2, "end": 4.0},
        {"text": "tres", "start": 5.0, "end": 6.0, "sub": True}]}
    s = app.subtitle_lines(p)
    assert [x["text"] for x in s] == ["uno", "tres"]
    assert s[0]["end"] <= 2.2 - 0.05 + 1e-9  # never over the next line
    assert len(app.subtitle_lines({**p, "subtitles": "all"})) == 3
    assert app.subtitle_lines({**p, "subtitles": "off"}) == []


def test_subtitle_overlay_wraps_long_lines():
    from slidesong import render
    rgb, alpha, y0 = render.subtitle_overlay("una frase bastante larga " * 4, 640, 360)
    short = render.subtitle_overlay("corta", 640, 360)
    assert rgb.shape[0] > short[0].shape[0] and y0 + rgb.shape[0] <= 360 and alpha.max() > 0.9


def test_move_overrides_and_style(monkeypatch):
    from slidesong import plan
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: True)
    slots = [{"asset": f"a{k}", "start": 3.0 * k, "end": 3.0 * (k + 1)} for k in range(4)]
    land = {"aspect": 1.5, "faces": []}
    port = {"aspect": 0.75, "faces": []}
    metas = [land, port, port, land]
    sh = plan.layout(slots, metas, overrides={0: "pan_rl", 1: "single", 3: "contain_out"}, style="calm")
    kinds = [(s["slots"], s["kind"]) for s in sh]
    assert kinds[0] == ([0], "pan_rl") and ([1, 2], "diptych") not in kinds and kinds[-1] == ([3], "contain_out")
    assert all(s["amp"] == plan.MOTION["calm"] for s in sh)
    sh = plan.layout(slots, metas, overrides={1: "diptych"})
    assert ([1, 2], "diptych") in [(s["slots"], s["kind"]) for s in sh]
    calm = plan.layout(slots, [land] * 4, style="calm")
    assert all(s["kind"] in ("in", "out") for s in calm)


def test_lone_portraits_vary_and_use_partners(monkeypatch):
    from slidesong import plan
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: False)  # no consecutive diptychs
    n = 12
    slots = [{"asset": f"photo-{k}", "start": 3.0 * k, "end": 3.0 * (k + 1)} for k in range(n)]
    port = {"aspect": 0.75, "faces": []}
    sh = plan.layout(slots, [port] * n, partners={k: f"partner-{k}" for k in range(n)})
    looks = [s["look"] for s in sh]
    assert len(set(looks)) >= 3                                   # varied
    assert all(a != b for a, b in zip(looks, looks[1:]))          # never the same effect twice in a row
    assert all(s.get("pair") == f"partner-{s['slots'][0]}" for s in sh if s["kind"] in ("diptych", "polaroid_pair"))
    assert not any(a.get("pair") and b.get("pair") for a, b in zip(sh, sh[1:]))  # no two pairs in a row


def test_push_after_a_vertical_pan_follows_its_direction():
    from slidesong import plan
    assert plan._push_dir({"kind": "tilt", "tilt_dir": "down"}) == "down"
    assert plan._push_dir({"kind": "tilt", "tilt_dir": "up"}) == "up"
    assert plan._push_dir({"kind": "pan_rl"}) == "right"
    # faces at the very top of a portrait photo: no room above, the camera comes up from below
    assert plan.tilt_dir(0.75, [0.3, 0.02, 0.6, 0.2]) == "down"
    assert plan.tilt_dir(0.75, [0.3, 0.5, 0.6, 0.7]) == "up"


def test_vertical_pan_never_turns_back():
    import numpy as np
    from slidesong import plan, render

    class P:  # a 9:16 portrait with the face right at the up/down limit (the case that turned back)
        id, aspect, box = "x", 0.5625, [0.31, 0.124, 0.565, 0.311]
        def image(self, px):
            return np.zeros((1600, 900, 3), np.uint8)
    c = render.Cover(P(), 480, 270, "tilt", 1600)
    ys, orig = [], c._view
    c._view = lambda z, cx, cy: (lambda r: (ys.append(r[3]), r)[1])(orig(z, cx, cy))
    for u in np.linspace(0, 1, 30):
        c.frame(u)
    d = np.diff(ys)
    assert (d <= 1e-6).all() or (d >= -1e-6).all()  # one direction only
    assert ("up" if d.sum() > 0 else "down") == plan.tilt_dir(P.aspect, P.box)


def test_zoom_moves_at_a_steady_speed():
    import numpy as np
    from slidesong import render

    class P:
        id, box = "x", None
        def image(self, px):
            return np.zeros((900, 1600, 3), np.uint8)
    free = 1e-9  # no pixelation limit: this test is about the planned move
    z = {d: render.Cover(P(), 320, 180, "in", 1600, 1.0, d, free).zmax - 1 for d in (1.0, 3.0, 4.0, 20.0)}
    assert abs(z[1.0] - 0.12) < 1e-6 and abs(z[3.0] - 0.21) < 1e-6 and abs(z[20.0] - 0.35) < 1e-6
    assert render.Cover(P(), 320, 180, "in", 1600, 0.6, 4.0, free).zmax - 1 < z[4.0]  # calm moves less


def test_whole_photo_stays_whole():
    import numpy as np
    from slidesong import render

    class P:
        id, box = "x", [0.3, 0.1, 0.6, 0.3]
        def image(self, px):
            return np.full((1800, 1012, 3), 200, np.uint8)
    for dur in (2.0, 3.2, 8.0):
        c = render.Contain(P(), 1920, 1080, 1800, True, 1.35, dur)
        f = c.frame(1.0)
        # the photo (flat 200) must not touch the top or bottom row: there is background above and below
        assert (f[0] != 200).any() and (f[-1] != 200).any(), dur
        assert c.z[1] > 1.06 or dur < 3


def test_zoom_goes_closer_with_faces_but_keeps_them():
    import numpy as np
    from slidesong import render

    class P:
        id = "x"
        def __init__(self, box):
            self.box = box
        def image(self, px):
            return np.zeros((900, 1600, 3), np.uint8)
    plain = render.Cover(P(None), 320, 180, "in", 1600, 1.0, 4.0, 1e-9).zmax
    faces = render.Cover(P([0.45, 0.4, 0.55, 0.55]), 320, 180, "in", 1600, 1.0, 4.0, 1e-9).zmax
    big = render.Cover(P([0.2, 0.1, 0.8, 0.9]), 320, 180, "in", 1600, 1.0, 4.0, 1e-9).zmax
    assert faces > plain and big < faces  # closer on small faces, held back on faces that fill the photo


def test_whole_to_face_ends_on_the_face():
    import numpy as np
    from slidesong import render

    class P:
        id, box = "x", [0.4, 0.15, 0.6, 0.3]
        def image(self, px):
            img = np.full((1600, 900, 3), 60, np.uint8)
            img[240:480, 360:540] = 250          # the "face" (box above, in pixels)
            return img
    fz = render.FaceZoom(P(), 480, 270, 1600, True, 1.0)
    start, end = fz.frame(0.0), fz.frame(1.0)
    assert (start[:, :60] != 60).any()           # starts whole: background visible at the sides
    assert end[135, 240].min() == 250            # ends with the face in the centre of the screen
    back = render.FaceZoom(P(), 480, 270, 1600, False, 1.0)
    assert np.array_equal(back.frame(1.0), start) and np.array_equal(back.frame(0.0), end)


def test_finals_are_60_fps_and_get_more_bitrate(monkeypatch):
    from slidesong import render
    monkeypatch.setenv("SLIDESONG_VCODEC", "h264_nvenc")
    a30, a60 = render.video_codec_args(1920, 30), render.video_codec_args(1920, 60)
    rate = lambda a: int(a[a.index("-maxrate") + 1].rstrip("M"))
    assert rate(a60) > rate(a30) and a60[a60.index("-cq") + 1] < a30[a30.index("-cq") + 1]
    assert render.FINAL_FPS == 60 and render.FPS == 30


def test_explicit_diptych_modes(monkeypatch):
    from slidesong import plan
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: False)
    slots = [{"asset": f"a{k}", "start": 3.0 * k, "end": 3.0 * (k + 1)} for k in range(4)]
    port, land = {"aspect": 0.75, "faces": []}, {"aspect": 1.5, "faces": []}
    metas = [port, land, port, port]
    sh = plan.layout(slots, metas, partners={2: "other"}, overrides={0: "diptych_next", 2: "diptych_other"})
    got = [(s["slots"], s["kind"], s.get("pair")) for s in sh]
    assert ([0, 1], "diptych", None) in got          # with the next one, even a landscape
    assert ([2], "diptych", "other") in got          # with the chosen / found second photo


def test_one_shot_diptych_keeps_its_transition(monkeypatch):
    from slidesong import plan
    monkeypatch.setattr(plan, "_same_scene", lambda a, b: False)
    slots = [{"asset": f"a{k}", "start": 3.0 * k, "end": 3.0 * (k + 1)} for k in range(3)]
    port = {"aspect": 0.75, "faces": []}
    sh = plan.layout(slots, [port] * 3, partners={0: "other"}, overrides={0: "diptych_other"})
    assert sh[0]["slots"] == [0] and sh[0].get("pair") == "other" and sh[1]["slots"] == [1]


def test_print_captions(monkeypatch):
    from slidesong import plan
    info = {"a": {"date": "2026-07-03T10:00:00"}, "b": {"date": "2026-07-03T10:05:00"}}
    monkeypatch.setattr(plan.immich, "_info_one", lambda a: info.get(a))
    assert plan.auto_caption("a") == "julio 2026"
    proj = {"slots": [{"asset": "a"}], "captions": {}}
    caps, ids = plan.captions_for(proj, {"slots": [0], "kind": "polaroid_pair", "pair": "b"})
    assert caps == ["julio 2026", ""]                      # the same text is not repeated on the second print
    proj["captions"] = {"b": "Titisee"}
    assert plan.captions_for(proj, {"slots": [0], "kind": "polaroid_pair", "pair": "b"})[0] == ["julio 2026", "Titisee"]


def test_moves_never_pixelate_the_original():
    import numpy as np
    from slidesong import render

    class P:
        id, box = "x", [0.45, 0.2, 0.55, 0.3]           # a small face: zooming on it needs resolution
        def __init__(self, w, h):
            self.meta = {"w": w, "h": h}
            self._img = np.zeros((h // 10, w // 10, 3), np.uint8)   # loaded 10x smaller than the original
        def image(self, px):
            return self._img
    big, small = P(4000, 3000), P(1600, 1200)
    c = render.Cover(big, 1920, 1080, "in", 0, 1.0, 6.0)
    assert (1920 / c.cw) * c.zmax / render._src_k(big, big._img) <= render.MAX_MAG + 1e-6 or c.zmax == 1.0
    assert render.Cover(small, 1920, 1080, "in", 0, 1.0, 6.0).zmax == 1.0       # no room: no zoom at all
    fz = render.FaceZoom(big, 1920, 1080, 0, True, 1.0)
    assert fz.limited and fz.s1 / render._src_k(big, big._img) <= render.MAX_MAG + 1e-6
    lim, share = render.motion_limited("whole_to_face", 3072, 4080, [0.45, 0.2, 0.55, 0.3], 4.0, 1.0)
    assert lim and 0 < share < 1


def test_exchange_moves_photo_choices(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from slidesong import app as A, learn
    monkeypatch.setattr(A, "PROJECTS", tmp_path)
    monkeypatch.setattr(learn, "log", lambda *a, **k: None)
    pid = "proj1"  # (ids are 3+ chars)
    (tmp_path / pid).mkdir()
    proj = {"id": pid, "slots": [{"asset": "a", "lyric": "uno", "start": 0, "end": 3, "clip_start": 2.0},
                                 {"asset": "b", "lyric": "dos", "start": 3, "end": 6, "locked": True}],
            "shot_overrides": {"0": "tilt"}, "move": {"1": 0.5}, "transition_overrides": {"0": "fade"}}
    A.save(proj)
    resp = TestClient(A.app).post(f"/api/projects/{pid}/exchange", json={"a": 0, "b": 1})
    assert resp.status_code == 200, resp.text
    r = resp.json()
    s0, s1 = r["slots"]
    assert (s0["asset"], s1["asset"]) == ("b", "a") and s1["clip_start"] == 2.0 and "clip_start" not in s0
    assert (s0["lyric"], s1["lyric"]) == ("uno", "dos")                      # the lyric stays with the shot
    assert r["shot_overrides"] == {"1": "tilt"} and r["move"] == {"0": 0.5}  # the photo's choices travel
    assert r["transition_overrides"] == {"0": "fade"} and s0["locked"] and s1["locked"]


def test_old_setting_names_still_work(monkeypatch):
    from slidesong import config
    monkeypatch.delenv("SLIDESONG_VCODEC", raising=False)
    monkeypatch.setenv("MONTAJE_VCODEC", "h264_nvenc")  # before the rename
    assert config.env("VCODEC") == "h264_nvenc"
    monkeypatch.setenv("SLIDESONG_VCODEC", "libx264")
    assert config.env("VCODEC") == "libx264"
