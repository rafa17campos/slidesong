#!/usr/bin/env bash
# Slidesong GPU worker on Linux: run from the worker folder (with slidesong/, .venv and worker.env); Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "$0")"
set -a
[ -f worker.env ] && . ./worker.env
set +a
echo "Slidesong worker on port ${WORKER_PORT:-8097} (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn slidesong.worker:app --host 0.0.0.0 --port "${WORKER_PORT:-8097}"
