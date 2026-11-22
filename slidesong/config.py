"""Settings from the environment: SLIDESONG_<NAME>, or MONTAJE_<NAME> as they were called before the rename."""
import os
from pathlib import Path


def env(name: str, default=None):
    return os.environ.get(f"SLIDESONG_{name}") or os.environ.get(f"MONTAJE_{name}") or default


DATA = Path(env("DATA") or Path(__file__).resolve().parent.parent / "data")
