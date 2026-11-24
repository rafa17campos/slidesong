import httpx
import pytest

from slidesong import insights, scores


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(scores, "DB", tmp_path / "scores.sqlite")
    monkeypatch.setattr(scores, "ACTIVE", tmp_path / "scorer.json")
    monkeypatch.setattr(scores, "_active", {"mtime": None, "info": scores.REFERENCE})
    monkeypatch.setattr(insights, "URL", "http://library")
    monkeypatch.setattr(insights, "TOKEN", "lib_t")
    monkeypatch.setattr(insights, "_warned", [0.0])
    calls = []

    def answer(status=200, body=None, exc=None):
        def post(url, **kw):
            calls.append((url, kw))
            if exc:
                raise exc
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))
        monkeypatch.setattr(httpx, "post", post)
    return answer, calls


def rec(aesthetic, tags, v=None):
    return {"record": {"aesthetic": aesthetic, "tags": tags}, "scorerVersion": v or scores.VERSION, "updatedAt": "x"}


def test_records_are_used_as_this_apps_own(hub):
    answer, calls = hub
    answer(body={"items": {"a": rec(5.0, ["dog"]), "b": rec(4.0, ["lawn"])}, "missing": [], "queued": 0})
    assert insights.pull(["a", "b"]) == 0
    url, kw = calls[0]
    assert url == "http://library/api/gallery/insights/lookup" and kw["timeout"] == 2.0
    assert kw["headers"] == {"Authorization": "Bearer lib_t"}
    assert kw["json"] == {"assetIds": ["a", "b"]}
    assert scores.get(["a", "b"])["a"]["tags"] == ["dog"]


def test_partial_answer_leaves_the_rest_to_the_usual_way(hub):
    answer, _ = hub
    answer(body={"items": {"a": rec(5.0, ["dog"]), "b": rec(4.0, [], v=1)}, "missing": ["c"], "queued": 1})
    assert insights.pull(["a", "b", "c"]) == 2  # b: an older scorer version counts as missing
    assert set(scores.get(["a", "b", "c"])) == {"a"}


def test_photos_already_analysed_here_are_not_asked(hub):
    answer, calls = hub
    scores.put([{"id": "a", "aesthetic": 1.0, "tags": []}])
    answer(body={"items": {}, "missing": ["b"], "queued": 1})
    insights.pull(["a", "b"])
    assert calls[0][1]["json"]["assetIds"] == ["b"]


def test_big_requests_go_in_chunks(hub):
    answer, calls = hub
    answer(body={"items": {}, "missing": [], "queued": 0})
    insights.pull([f"id{k}" for k in range(3001)])
    assert [len(c[1]["json"]["assetIds"]) for c in calls] == [3000, 1]


@pytest.mark.parametrize("kind", ["timeout", "401", "500", "bad json"])
def test_any_failure_means_the_usual_way(hub, kind, capsys):
    answer, _ = hub
    if kind == "timeout":
        answer(exc=httpx.ReadTimeout("slow"))
    elif kind == "bad json":
        answer(body=["not", "a", "dict"])
    else:
        answer(status=int(kind), body={"detail": "no"})
    assert insights.pull(["a"]) is None
    assert insights.pull(["a"]) is None
    assert capsys.readouterr().out.count("unavailable") == 1  # one warning a minute, not one per call


def test_without_configuration_nothing_is_asked(hub, monkeypatch):
    answer, calls = hub
    monkeypatch.setattr(insights, "URL", "")
    assert insights.pull(["a"]) is None and insights.status() is None and calls == []


def test_status(hub, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"workerOnline": True, "queued": 3, "processing": 1}, request=httpx.Request("GET", url)))
    assert insights.status() == {"workerOnline": True, "queued": 3, "processing": 1}


def test_records_of_another_scorer_are_not_taken(hub):
    answer, _ = hub
    answer(body={"items": {"a": {**rec(5.0, ["dog"]), "scorerName": "other-scorer"}, "b": rec(4.0, ["cat"])},
                  "missing": [], "queued": 0})
    assert insights.pull(["a", "b"]) == 1 and set(scores.get(["a", "b"])) == {"b"}
