# The new interface: built here so the image needs no Node at run time.
FROM node:26-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY slidesong ./slidesong
COPY --from=web /web/dist ./web
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 SLIDESONG_DATA=/data HF_HOME=/data/hf HOME=/data
EXPOSE 8096
CMD ["uvicorn", "slidesong.app:app", "--host", "0.0.0.0", "--port", "8096"]
