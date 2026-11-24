"""The scorer's per-face record entries (scorer/score.py runs in its own venv: torch is stubbed here)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PID = "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"


@pytest.fixture
def score(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    spec = importlib.util.spec_from_file_location("score", Path(__file__).parent.parent / "scorer" / "score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_faces_carry_the_immich_person_id(score):
    measured = {"name": "Nico", "box": [0.1, 0.1, 0.3, 0.2], "found": True, "sharp": 2.1, "smile": 0.8,
                "eyes_open": 0.9}
    assigned = score.face_entry(measured, {"box": [0.1, 0.1, 0.3, 0.2], "name": "Nico",
                                           "person_id": PID.upper()}, 2.3)
    assert assigned == {**measured, "focus": 2.3, "person_id": PID}
    assert list(assigned) == ["name", "box", "found", "sharp", "smile", "eyes_open", "focus", "person_id"]

    unassigned = score.face_entry({"name": "", "box": [0, 0, 1, 1], "found": False},
                                  {"box": [0, 0, 1, 1], "name": "", "person_id": None}, None)
    assert unassigned["person_id"] is None and unassigned["name"] == ""


def test_faces_without_a_person_id_in_the_input_do_not_claim_one(score):
    e = score.face_entry({"name": "Nico", "box": [0, 0, 1, 1], "found": False}, {"box": [0, 0, 1, 1], "name": "Nico"}, None)
    assert "person_id" not in e
    assert score.person_id({"person_id": "not-a-uuid"}) is None
