import os
import sys
from pathlib import Path

# tests never talk to Immich or a worker
os.environ.setdefault("IMMICH_URL", "http://127.0.0.1:9")
os.environ.setdefault("IMMICH_API_KEY", "test")
os.environ.setdefault("SLIDESONG_DATA", str(Path(__file__).parent / "_data"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
