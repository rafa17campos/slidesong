import opentimelineio as otio

from slidesong import export


def _project():
    slots = [{"lyric": f"línea {k}", "asset": f"a{k}", "start": 3.0 * k, "end": 3.0 * (k + 1)} for k in range(3)]
    plan = {"boundaries": [{"after_slot": 0, "kind": "fade", "dur": 0.8, "reason": "verse"},
                           {"after_slot": 1, "kind": "whip", "dur": 0.4, "reason": "estribillo"}]}
    return {"slots": slots, "plan": plan, "song": {"duration": 9.0}}


def _clips():
    return [{"file": f"shot_{k + 1:03d}.mp4", "start": 3.0 * k, "end": 3.0 * (k + 1), "head": 0.0 if k == 0 else 0.5,
             "tail": 0.0 if k == 2 else 0.5, "frames": int((3.0 + (0 if k == 0 else 0.5) + (0 if k == 2 else 0.5)) * 30),
             "kind": "in", "slots": [k]} for k in range(3)]


def test_timeline_places_clips_and_dissolves_only_fades():
    tl = export.timeline(_project(), _clips(), "song.mp3", 9.0, "Prueba")
    v, a = tl.tracks
    clips = [c for c in v if isinstance(c, otio.schema.Clip)]
    trans = [t for t in v if isinstance(t, otio.schema.Transition)]
    assert len(clips) == 3 and len(trans) == 1  # the fade, not the whip
    assert v.range_of_child_at_index(0).start_time.to_seconds() == 0
    assert abs(v.duration().to_seconds() - 9.0) < 1 / 30
    assert clips[1].source_range.start_time.to_seconds() == 0.5  # the handle is skipped
    assert abs(a.duration().to_seconds() - 9.0) < 1 / 30
    for adapter in ("otio_json", "fcp_xml"):
        assert otio.adapters.write_to_string(tl, adapter)


def test_transitions_table_lists_every_cut():
    t = export.transitions_table(_project(), _clips())
    assert "Fade" in t and "Whip pan" in t


def test_srt_format():
    t = export.srt([{"start": 1.5, "end": 3.25, "text": "Hola"}, {"start": 61, "end": 62.5, "text": "Adiós"}])
    assert "1\n00:00:01,500 --> 00:00:03,250\nHola" in t and "00:01:01,000 --> 00:01:02,500" in t
