"""The scorer's per-face record entries. scorer/score.py runs in its own venv (torch, MediaPipe...), so only its
record helpers are taken from it here, without importing the whole script."""
import ast
import uuid
from pathlib import Path

import pytest

PID = "1c0d9a7e-5b8f-4a2e-9d3c-7f6e5d4c3b2a"


@pytest.fixture(scope="module")
def score():
    src = (Path(__file__).parent.parent / "scorer" / "score.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("person_id", "face_entry")]
    ns = {"uuid": uuid}
    exec(compile(tree, "score.py", "exec"), ns)
    return type("score", (), {k: staticmethod(ns[k]) for k in ("person_id", "face_entry")})


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


def test_an_unknown_person_id_is_left_out_not_null(score):
    face = {"name": "Nico", "box": [0, 0, 1, 1], "found": False}
    assert "person_id" not in score.face_entry(face, {"box": [0, 0, 1, 1], "name": "Nico"}, None)
    assert "person_id" not in score.face_entry(face, {"box": [0, 0, 1, 1], "name": "Nico", "person_id": "abc"}, None)
