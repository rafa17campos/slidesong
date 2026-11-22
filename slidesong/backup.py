"""Backups: a zip of what cannot be made again, laid out like the data folder.

Restoring is unzipping it over the data folder with the app stopped (see README). Included:
- each project: project.json, its undo history and its song (optionally the videos made);
- the learning log and its state (feedback.jsonl, learning.json);
- the photo scores computed on the GPU (scores.sqlite, copied consistently with SQLite's backup API).
Left out, as they are made again on demand: caches, snippets, photo exports, models and place names.
"""
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

FORMAT = 1
MANIFEST = "backup-manifest.json"
PROJECT_FILES = ("project.json", "history.json")
# already compressed: stored as they are
STORED = {".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".mov"}


def project_files(d: Path, p: dict, videos: bool) -> list[Path]:
    """The files of one project that go in a backup."""
    out = [d / n for n in PROJECT_FILES if (d / n).exists()]
    song = (p.get("song") or {}).get("file")
    if song and (d / song).exists():
        out.append(d / song)
    if videos:
        for r in p.get("renders") or []:
            f = d / "renders" / r.get("file", "")
            if r.get("file") and f.is_file():
                out.append(f)
    return out


def videos_size(d: Path, p: dict) -> int:
    return sum(f.stat().st_size for f in project_files(d, p, True) if f.parent.name == "renders")


def _add(zf: zipfile.ZipFile, src: Path, name: str, files: list):
    h = hashlib.sha256()
    method = zipfile.ZIP_STORED if src.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
    info = zipfile.ZipInfo.from_file(src, name)
    info.compress_type = method
    with src.open("rb") as fi, zf.open(info, "w", force_zip64=True) as fo:
        while chunk := fi.read(1 << 20):
            h.update(chunk)
            fo.write(chunk)
    files.append({"path": name, "size": src.stat().st_size, "sha256": h.hexdigest()})


def _add_bytes(zf: zipfile.ZipFile, data: bytes, name: str, files: list):
    zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})


def build(dest: Path, *, data: Path, projects: list[tuple[str, Path]], videos: bool, whole: bool,
          project_lock, learn_lock, scores_lock, scores_db: Path, app_version: str = "") -> dict:
    """Write the backup zip to `dest`; returns its manifest.

    `projects` are (id, folder); each is read under its own lock (project_lock(pid)), so an edit in flight is
    either fully in or out. `whole` adds the learning and the photo scores."""
    files: list[dict] = []
    done = []
    with zipfile.ZipFile(dest, "w", allowZip64=True) as zf:
        for pid, d in projects:
            with project_lock(pid):
                raw = (d / "project.json").read_bytes()  # one read: the files listed are the ones it names
                p = json.loads(raw)
                _add_bytes(zf, raw, f"projects/{pid}/project.json", files)
                for f in project_files(d, p, videos):
                    if f.name != "project.json":
                        _add(zf, f, f"projects/{pid}/{f.relative_to(d).as_posix()}", files)
            done.append({"id": pid, "title": p.get("title"), "frozen": bool(p.get("frozen"))})
        if whole:
            with learn_lock:
                for n in ("feedback.jsonl", "learning.json"):
                    if (data / n).exists():
                        _add_bytes(zf, (data / n).read_bytes(), n, files)
            if scores_db.exists():
                with tempfile.TemporaryDirectory(dir=dest.parent) as t:
                    copy = Path(t) / "scores.sqlite"
                    with scores_lock, sqlite3.connect(scores_db, timeout=30) as src, sqlite3.connect(copy) as dst:
                        src.backup(dst)
                    dst.close()
                    _add(zf, copy, "scores.sqlite", files)
        manifest = {
            "format": FORMAT,
            "made": datetime.now().isoformat(timespec="seconds"),
            "app": app_version,
            "whole": whole,
            "videos": videos,
            "projects": done,
            "files": files,
        }
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)
    return manifest


def verify(path: Path) -> list[str]:
    """Problems found in a backup zip (empty when every file is there with its checksum)."""
    problems = []
    with zipfile.ZipFile(path) as zf:
        m = json.loads(zf.read(MANIFEST))
        for f in m["files"]:
            h = hashlib.sha256()
            try:
                with zf.open(f["path"]) as fi:
                    while chunk := fi.read(1 << 20):
                        h.update(chunk)
            except KeyError:
                problems.append(f"falta {f['path']}")
                continue
            if h.hexdigest() != f["sha256"]:
                problems.append(f"{f['path']} no coincide")
    return problems
