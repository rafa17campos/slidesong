import json
import os
import time

import pytest

from slidesong import videoframes as vf


def test_parse_duration_both_immich_formats():
    assert vf.parse_duration(451040) == 451.04  # milliseconds (Immich 2+)
    assert vf.parse_duration("0:02:30.500000") == 150.5  # older Immich
    assert vf.parse_duration("1:00:00.000000") == 3600
    for nothing in (None, 0, "0:00:00.00000", "", "bad", True):
        assert vf.parse_duration(nothing) is None


def test_sampling_every_5_s_from_1_s():
    assert vf.sample_times(12) == [1, 6, 11]
    assert vf.sample_times(30)[:3] == [1, 6, 11] and vf.sample_times(30)[-1] == 26


def test_sampling_150_s_is_30_frames_and_longer_videos_spread_them():
    t = vf.sample_times(150)
    assert len(t) == 30 and t[0] == 1 and t[1] - t[0] == 5
    for d in (151, 300, 3600, 36000):
        t = vf.sample_times(d)
        assert len(t) == 30 and t[0] == 1 and t[-1] < d
        assert t[1] - t[0] == pytest.approx(d / 30, abs=0.01)


def test_never_more_than_30_frames():
    assert max(len(vf.sample_times(d)) for d in range(1, 2000, 7)) == 30


def test_short_videos_get_their_preview_only():
    assert vf.sample_times(None) == [] and vf.sample_times(0) == []
    assert vf.sample_times(0.8) == []  # shorter than the first frame
    assert vf.sample_times(1.1) == []  # too close to the end to seek
    assert vf.sample_times(1.5) == [1]
    assert vf.sample_times(5.9) == [1]


def test_frame_ids_round_trip():
    a = "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"
    assert vf.frame_id(a, 6.0) == a + "@6" and vf.frame_id(a, 10.33) == a + "@10.33"
    assert vf.split_id(vf.frame_id(a, 10.33)) == (a, 10.33)
    assert vf.split_id(a) == (a, None)
    assert vf.split_id(a + "@x") == (a + "@x", None)


def test_expand_puts_the_frames_after_their_video():
    items = [{"id": "p"}, {"id": "v", "faces": []}]
    out = vf.expand(items, {"v": [(1, "/f/1.jpg"), (6, "/f/6.jpg")]})
    assert out == [{"id": "p"}, {"id": "v", "faces": []}, {"id": "v@1", "image": "/f/1.jpg"},
                   {"id": "v@6", "image": "/f/6.jpg"}]
    assert vf.expand(items, {}) == items


def test_sensitive_tags_match_slidesongs_warnings():
    from slidesong import suggest
    assert vf.ANY_FRAME_TAGS == set(suggest.SENSITIVE)


def test_tags_fold_keeps_preview_sensitive_and_repeated_tags():
    lines = [{"id": "p", "tags": ["dog"]},
             {"id": "v", "tags": ["beach", "child"]},  # the preview
             {"id": "v@1", "tags": ["beach", "swimwear", "kite"]},
             {"id": "v@6", "tags": ["sea", "child"]},
             {"id": "v@11", "tags": ["sea", "umbrella"]}]
    out = vf.fold(lines, {"v"}, "tag")
    assert out[0] == {"id": "p", "tags": ["dog"]}
    # kite and umbrella: one frame each, not in the preview, not sensitive
    assert out[1] == {"id": "v", "tags": ["beach", "child", "swimwear", "sea"], "video_mode": "deep",
                      "video_frames": 4}


def test_tags_fold_without_the_preview():
    out = vf.fold([{"id": "v@1", "tags": ["sea"]}, {"id": "v@6", "tags": ["sea", "bath"]}], {"v"}, "tag")
    assert out == [{"id": "v", "tags": ["sea", "bath"], "video_mode": "deep", "video_frames": 2}]


def _score(i, a, **kw):
    return {"id": i, "v": 4, "aesthetic": a, "sharp": kw.get("sharp", 2.0), "bright": 0.5, "clip_hi": 0.01,
            "clip_lo": 0.0, "faces": kw.get("faces", [])}


def test_scores_fold_median_best_and_faces_from_the_preview():
    face = {"name": "Nico", "box": [0.1, 0.1, 0.3, 0.3], "found": True, "smile": 0.9}
    lines = [_score("v", 5.0, faces=[face]), _score("v@1", 4.0, sharp=1.0), _score("v@6", 6.5, sharp=3.0),
             _score("v@11", 5.5, sharp=2.5), _score("p", 3.0)]
    v, p = vf.fold(lines, {"v"}, "score")
    assert p == _score("p", 3.0)  # a photo's record does not change
    assert v["id"] == "v" and v["v"] == 4 and v["faces"] == [face]
    assert v["aesthetic"] == 5.25 and v["sharp"] == 2.25  # medians of 4 images
    assert v["aesthetic_best"] == 6.5 and v["best_at"] == 6
    assert v["video_mode"] == "deep" and v["video_frames"] == 4
    assert list(v)[:8] == list(_score("v", 0))  # same keys first, in the same order


def test_scores_fold_best_is_the_preview():
    v, = vf.fold([_score("v", 7.0), _score("v@1", 4.0)], {"v"}, "score")
    assert v["best_at"] == 0 and v["aesthetic_best"] == 7.0 and v["aesthetic"] == 5.5


def test_scores_fold_preview_only_and_frames_only():
    v, = vf.fold([_score("v", 7.0, faces=[{"name": ""}])], {"v"}, "score")
    assert v["aesthetic"] == 7.0 and v["video_frames"] == 1 and v["best_at"] == 0 and v["faces"] == [{"name": ""}]
    v, = vf.fold([_score("v@1", 4.0), _score("v@6", 5.0)], {"v"}, "score")
    assert "faces" not in v and v["video_frames"] == 2 and v["best_at"] == 6


def test_fold_leaves_out_items_with_no_line_and_videos_not_deep():
    out = vf.fold([_score("a", 1.0), _score("c", 2.0)], {"b"}, "score")
    assert out == [_score("a", 1.0), _score("c", 2.0)]


class FakeExtractor(vf.Extractor):
    def __init__(self, cache, fail=(), hdr=False, none=()):
        super().__init__("http://immich", "k", cache)
        self.calls, self.fail, self.hdr, self.none = [], set(fail), hdr, set(none)

    def _run(self, cmd, timeout):
        self.calls.append(cmd)
        if cmd[0] == "ffprobe":
            return 0, "arib-std-b67\n" if self.hdr else "bt709\n"
        t = float(cmd[cmd.index("-ss") + 1])
        if t in self.fail:
            return 1, ""
        if t in self.none:  # ffmpeg found no frame there: success, but no file
            return 0, ""
        open(cmd[-1], "wb").write(b"jpg")
        return 0, ""


def test_frames_are_cached_between_jobs(tmp_path):
    ex = FakeExtractor(tmp_path)
    got = ex.frames("v", "sum1", [1, 6])
    assert [t for t, _ in got] == [1, 6] and all(p.exists() for _, p in got)
    n = len(ex.calls)
    ex2 = FakeExtractor(tmp_path)
    assert ex2.frames("v", "sum1", [1, 6]) == got and ex2.calls == []  # the scorer's job after the tagger's
    assert len(ex2.used) == 1
    ex2.frames("v", "sum2", [1, 6])  # the video changed in Immich
    assert len(ex2.calls) == n


def test_frames_the_key_goes_in_a_header_and_reads_are_small(tmp_path):
    ex = FakeExtractor(tmp_path)
    ex.frames("v", "s", [1])
    cmd = ex.calls[-1]
    assert cmd[cmd.index("-headers") + 1] == "x-api-key: k\r\n"
    assert cmd[cmd.index("-i") + 1] == "http://immich/api/assets/v/video/playback"
    assert cmd.index("-ss") < cmd.index("-i") and "-recv_buffer_size" in cmd  # seek in the stream, not decode to it


def test_frames_unreadable_are_left_out_and_tried_again_next_job(tmp_path):
    ex = FakeExtractor(tmp_path, fail={6})
    assert [t for t, _ in ex.frames("v", "s", [1, 6, 11])] == [1, 11]
    assert FakeExtractor(tmp_path, fail={1}).frames("w", "s", [1]) == []
    # Immich is back: the next job extracts again instead of reusing the incomplete result
    ex = FakeExtractor(tmp_path)
    assert [t for t, _ in ex.frames("v", "s", [1, 6, 11])] == [1, 6, 11] and ex.calls
    assert [t for t, _ in ex.frames("w", "s", [1])] == [1]
    ex = FakeExtractor(tmp_path)
    ex.frames("v", "s", [1, 6, 11])
    assert ex.calls == []  # complete now: cached


def test_ffmpeg_that_cannot_start_reads_nothing(tmp_path):
    ex = vf.Extractor("http://immich", "k", tmp_path)
    assert ex._run(["no-such-ffmpeg-here"], 5) == (-1, "")


def test_frame_times_keep_their_hundredths():
    a = "v"
    assert vf.seconds(6.0) == "6" and vf.seconds(10.3) == "10.3" and vf.seconds(12345.67) == "12345.67"
    assert vf.split_id(vf.frame_id(a, 12345.67)) == (a, 12345.67)


def test_hdr_frames_are_tone_mapped(tmp_path):
    ex = FakeExtractor(tmp_path, hdr=True)
    ex._zscale = True
    ex.frames("v", "s", [1])
    assert "tonemap" in ex.calls[-1][ex.calls[-1].index("-vf") + 1]
    logs = []
    ex = FakeExtractor(tmp_path, hdr=True)
    ex._zscale, ex.log = False, logs.append
    ex.frames("w", "s", [1])
    assert "tonemap" not in ex.calls[-1][ex.calls[-1].index("-vf") + 1] and logs[0].startswith("warning: ")


def test_cancel_kills_ffmpeg(tmp_path):
    import sys

    class Stop(Exception):
        pass

    def check():
        raise Stop()
    ex = vf.Extractor("http://immich", "k", tmp_path, check=check)
    t0 = time.monotonic()
    with pytest.raises(Stop):
        ex._run([sys.executable, "-c", "import time; time.sleep(30)"], 60)
    assert time.monotonic() - t0 < 5


def test_cache_cleanup_by_age_and_size(tmp_path):
    def entry(name, size, age):
        d = tmp_path / name
        d.mkdir()
        (d / "1.jpg").write_bytes(b"x" * size)
        os.utime(d, (time.time() - age, time.time() - age))
    entry("old", 10, 7 * 3600)
    entry("a", 100, 300)
    entry("b", 100, 200)
    entry("mine", 100, 400)
    vf.clean_cache(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "b", "mine"]
    vf.clean_cache(tmp_path, keep=["mine"], max_bytes=250)  # the least recently used goes, not this job's
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b", "mine"]
    vf.clean_cache(tmp_path / "none")  # no cache yet


def test_frames_come_from_the_video_stream_not_a_motion_photos_still(tmp_path):
    ex = FakeExtractor(tmp_path)
    ex.frames("v", "s", [1])
    probe, frame = ex.calls
    assert probe[probe.index("-select_streams") + 1] == "V:0"
    assert frame[frame.index("-map") + 1] == "0:V:0" and frame.index("-map") > frame.index("-i")


def test_no_frame_at_a_time_is_not_an_unreadable_video(tmp_path):
    ex = FakeExtractor(tmp_path, none={6})
    assert [t for t, _ in ex.frames("v", "s", [1, 6])] == [1] and ex.unreadable == set()
    ex = FakeExtractor(tmp_path, none={1})
    assert ex.frames("w", "s", [1]) == [] and ex.unreadable == set()
    again = FakeExtractor(tmp_path)
    assert again.frames("w", "s", [1]) == [] and again.calls == []  # a definite answer: cached
    ex = FakeExtractor(tmp_path, fail={1})
    assert ex.frames("x", "s", [1]) == [] and ex.unreadable == {"x"}
