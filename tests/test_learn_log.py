import json

import pytest

from slidesong import learn


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(learn, "EVENTS", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(learn, "DATA", tmp_path)
    monkeypatch.setattr(learn, "_cue_snapshot", lambda project, i: {"words": []})
    return learn


def _p(pid="p1", locked=False):
    return {"id": pid, "slots": [{"asset": "a", "alts": ["x", "y"], "locked": locked},
                                 {"asset": "b", "alts": ["z"], "locked": False}]}


def test_final_renders_log_each_agreement_once(log):
    log.log_accepted(_p())
    log.log_accepted(_p())  # a second final render of the same edit
    assert [(e["slot"], e["new"]) for e in log.events() if e["action"] == "accept"] == [(0, "a"), (1, "b")]


def test_bootstrap_does_not_repeat_a_photo_put_by_hand(log):
    log.log(_p(), 0, "set", new="a", old="x", source="alts")  # put by hand (and so pinned)
    assert log.bootstrap([_p(locked=True)]) == 0


def test_forget_by_time_leaves_other_projects_alone(log):
    log.log(_p("A"), 0, "set", new="a", old="x")
    since = log.now()
    log.log(_p("B"), 0, "set", new="a", old="x")
    log.log(_p("A"), 1, "set", new="b", old="z")
    assert log.forget("A", since) == 1
    assert [(e["project"], e["slot"]) for e in log.events()] == [("A", 0), ("B", 0)]


def test_a_damaged_line_does_not_break_the_log(log):
    log.log(_p(), 0, "set", new="a", old="x")
    with open(log.EVENTS, "a") as f:
        f.write('{"ts": "2026-11-21T1')  # a write cut short
    assert len(log.events()) == 1 and log.corrections() == 1


def test_dedupe_cleans_an_old_log(log):
    ev = lambda **k: {"ts": "t", "project": "p1", "slot": 0, "new": "a", **k}
    lines = [ev(action="accept", source="final"), ev(action="accept", source="final"),
             ev(action="set", source="alts"), ev(action="set", source="fijada"), ev(action="reject", new=None)]
    log.EVENTS.write_text("".join(json.dumps(e) + "\n" for e in lines))
    assert log.dedupe() == 2
    assert [(e["action"], e.get("source")) for e in log.events()] == [("accept", "final"), ("set", "alts"), ("reject", None)]


def test_a_new_version_does_not_teach_the_same_thing_twice(log):
    original = {**_p("orig", locked=True)}
    version = {**_p("orig-v2", locked=True), "lineage": "orig"}
    assert log.bootstrap([original]) == 1
    assert log.bootstrap([version]) == 0  # same pinned photo, same shot, same family
    log.log_accepted({**_p("orig"), "slots": [{"asset": "a"}, {"asset": "b"}]})
    log.log_accepted({**version, "slots": [{"asset": "a"}, {"asset": "b"}]})
    assert sum(1 for e in log.events() if e["action"] == "accept") == 1  # shot 0 was corrected (pinned import)
