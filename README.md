# Slidesong

Self-hosted app that turns your [Immich](https://immich.app) photos and a song into a video whose photos follow
the lyrics: a line about the beach gets a beach photo, a line that names July gets a photo from July, the chorus
gets livelier cuts. Made for family songs (for example ones made with Suno) and the photos that go with them.

- **Suggests a photo for every shot** from the people, dates and album you choose: in order through time, the best
  of each burst, matching each line (people, places, months and seasons it names, what it describes), avoiding
  near-duplicates and, if you want, sensitive photos (swimwear, shirtless…).
- **You review everything**: change a photo (search, paste an Immich link, same burst), pin, swap shots, frame and
  move the camera, transitions, captions under album-style prints, subtitles. Every edit can be undone.
- **Makes the video**: a quick 360p preview or the final 1080p, 2K or 4K at 60 fps, or an editable project for
  DaVinci Resolve, Premiere or Kdenlive.
- **Learns from your corrections** which signals matter to you (smiles, sharpness, the lyrics…), and lets you tune
  them by hand.
- Interface in **English and Spanish**; songs in English or Spanish (other languages work with the lyrics model).
- Your photos never leave your network: Slidesong reads them from Immich and renders on your own machines.

How to use it, step by step: the [user guide](docs/user-guide.md) ([en español](docs/user-guide.es.md)).

## Requirements
- Immich, reachable from the machine that runs Slidesong, and an API key of your user (see below).
- Docker (or Python 3.12 + [uv](https://docs.astral.sh/uv/) and Node 24 to run it from source).
- Optional: an NVIDIA GPU machine for the [worker](#gpu-worker-optional) (photo quality scores and tags, faster
  transcription and rendering); an [Anthropic API key](#lyrics-model-optional) for a better reading of the lyrics.

## Quick start
```sh
cp secrets.env.example secrets.env && chmod 600 secrets.env   # then fill it in
docker compose up -d --build                                  # http://localhost:8096
```
`secrets.env.example` lists every setting. The data (projects, songs, videos, what was learned) lives in `./data`, or wherever `SLIDESONG_DATA` points in
`.env` (for example next to your other Docker volumes).

### Immich access
- **API key** (Immich → Account settings → API keys) with read permissions only: `asset.read`, `asset.view`,
  `asset.download`, `album.read`, `person.read`, `face.read`. Set `IMMICH_URL` and `IMMICH_API_KEY`.
- **Machine learning**: Slidesong asks Immich's machine-learning service for text embeddings (to match lyrics with
  photos): `IMMICH_ML_URLS`. Immich's compose file does not publish its port (3003): publish it, or run Slidesong
  where it can reach the `immich-machine-learning` container.
- **Optional, better suggestions**: the CLIP vectors Immich already computed, through a Postgres role that can only
  read them (`IMMICH_VEC_DSN`). Vectors are only read for photos the API already returned, so Immich's permissions
  still hold:
  ```sql
  CREATE ROLE slidesong_ro LOGIN PASSWORD 'change-me' CONNECTION LIMIT 5;
  ALTER ROLE slidesong_ro SET default_transaction_read_only = on;
  GRANT CONNECT ON DATABASE immich TO slidesong_ro;
  GRANT USAGE ON SCHEMA public TO slidesong_ro;
  GRANT SELECT ("assetId", embedding) ON smart_search TO slidesong_ro;
  ```
  Without vectors the app still works, with simpler suggestions.

### Security
**Slidesong has no login.** Anyone who can reach it can see any photo of the Immich user whose key it uses, and
change or delete projects. Keep it on your home network or VPN, or behind an authenticating proxy (for example
Cloudflare Access, Authelia or oauth2-proxy). `SLIDESONG_ALLOWED_HOSTS` limits the host names it answers to
(protection against DNS rebinding).

## GPU worker (optional)
`slidesong/worker.py` runs the heavy jobs on a machine with an NVIDIA GPU: Whisper large-v3 on CUDA, rendering
with NVENC, the photo quality scores (`scorer/`: aesthetics, faces, sharpness) and the RAM++ tags (`tagger/`), which
the sensitive-photo warnings and part of the matching come from. Without it everything except the photo scores
and tags runs on the Slidesong machine, more slowly.

1. Copy `slidesong/`, `pyproject.toml`, `uv.lock` and `worker/start-worker.bat` (Windows) or
   `worker/start-worker.sh` (Linux) to a folder on the GPU machine; run `uv sync --extra gpu` there. For the
   scores and tags, copy `scorer/` and `tagger/` next to it and run `uv sync` inside each. FFmpeg with NVENC must
   be on the PATH. (Tested on Windows with an RTX 2070; on Linux you need CUDA 12 and cuDNN 9 for
   faster-whisper.)
2. `worker.env` next to the start script (see `worker/worker.env.example`): a token, and a read-only Immich key of
   its own (`asset.read`, `asset.view`, `face.read`) so it fetches photos and faces itself. Without that key it
   gets them through Slidesong (`SLIDESONG_IMAGES_URL`).
3. In Slidesong's `secrets.env`: `SLIDESONG_WORKER_URL` and the same `WORKER_TOKEN`.
4. Start it by hand when you make videos. Before each job Slidesong checks `GET /health`; if the worker is off or
   busy, jobs run locally (the photo analysis waits for it). One job at a time. Firewall its port (8097) so only
   its clients reach it.

The scorer and the tagger are replaceable: any program that keeps the contract in
[docs/analysers.md](docs/analysers.md) works (`SCORER_DIR`, `TAGGER_DIR`). The worker can serve other apps too,
each with its own token (`WORKER_TOKENS`): with its own Immich key, a client
only sends asset ids to `/score` and `/tag` and polls `/jobs/{id}`.

## Lyrics model (optional)
With `ANTHROPIC_API_KEY`, Claude reads the lyrics once per song: for every line an English translation, what a
photo illustrating it would show, a few tags, and the month or season it names. Only the lyrics, the song title
and the names of the people you chose are sent; never photos. It costs a few cents per song.

Without it, a local translator is used if you install one: convert
[NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) (non-commercial licence) or,
for Spanish only, [opus-mt-es-en](https://huggingface.co/Helsinki-NLP/opus-mt-es-en) with CTranslate2 into
`data/models/nllb-600m-ct2` or `data/models/opus-mt-es-en-ct2`:
```sh
ct2-transformers-converter --model facebook/nllb-200-distilled-600M --output_dir data/models/nllb-600m-ct2 \
  --quantization int8 --copy_files sentencepiece.bpe.model
```
(for opus-mt, `--copy_files source.spm target.spm`).
Without either, lines are matched in their own language only.

## Photo analysis kept by another service (optional)
With `SLIDESONG_INSIGHTS_URL` and `SLIDESONG_INSIGHTS_TOKEN` (`slidesong/insights.py` has the contract), Slidesong
takes the quality scores and tags from a service that keeps them for your whole library (and drives the same
worker) before each suggestion, keeps a copy, and analyses what that service lacks the usual way. Any failure, or a
reply slower than 2 s, just means the usual way.

## Languages
English and Spanish, for the interface and for the songs. The song's language is detected from the lyrics or
chosen in the Song step; Whisper, the lyrics model, the local translator and the CLIP text encoder are told it.
With the lyrics model, songs in other languages work too, without the word lists.

### Adding a language
- **Songs:** copy `slidesong/languages/en.py` to `slidesong/languages/<code>.py` (ISO 639-1) and fill it in: common
  words (to detect it), months, seasons, the words for each thing a line can name, countries, place stop words and
  Suno section words. It is found on its own (`tests/test_lexicon.py` checks it defines everything).
- **Interface:** copy `frontend/src/i18n/locales/en/` to `frontend/src/i18n/locales/<code>/` and translate it
  (`common.json` also holds the language's own name and its locale for dates); the folder is found on its own and
  the language appears in the switch (`i18n.test.ts` checks every key is there). For the server's messages, add
  `TEXTS` (and `WORDS`, the words that fill their placeholders) to the language's module, as in
  `slidesong/languages/es.py`.

## Backups
«Backup» (home page, or a project's ⋯ menu) downloads a zip laid out like the data folder: each project's
`project.json`, undo history and song (and, if asked, the videos made), plus what was learned and the photo
analysis for a whole backup. Photos stay in Immich. `backup-manifest.json` lists every file with its SHA-256
(`python -c "from pathlib import Path; from slidesong import backup; print(backup.verify(Path('backup.zip')))"`).
To restore: stop Slidesong, unzip over the data folder (`unzip -o backup.zip -d data`), start it again.

## Development
- Server: `uv sync`, then `set -a; . ./secrets.env; set +a; uv run uvicorn slidesong.app:app --port 8096 --reload`.
- Interface: `cd frontend && npm install && npm run dev` (port 5196, proxies `/api` to 8096).
- Checks: `uv run pytest` (no Immich needed); `cd frontend && npm run typecheck && npm run lint && npm test`.
- Code, comments and commits in English; every text people see goes through the translations (`frontend/src/i18n`,
  `slidesong/i18n.py` with `slidesong/languages/`).

### How it works
- **Song** (`analyze.py`): beats and audio features with librosa, lyrics aligned with faster-whisper, shots planned
  from the pace and the song's sections (Suno tags like `[Chorus – Energetic…]`).
- **Photos** (`suggest.py`, `lexicon.py`): candidates from Immich, the best of each burst, scored per shot (quality
  and faces from the worker, CLIP affinity with the line and its English reading, people, places, months, seasons,
  things the line names, the theme, what to avoid) and placed in time order with dynamic programming.
- **Edit plan** (`plan.py`): each shot's layout (zoom, pan, tilt, whole photo, album prints, diptychs) and each
  transition (cut, fade, push, dips, flash, zoom…), from the sections, the beat, the continuity between photos
  (same moment, or a new chapter) and the camera moves, with a reason shown in the editor. The worker renders
  exactly this plan (`render.py`).
- **Learning** (`learn.py`): every correction becomes pairwise preferences; the scoring weights are refitted with a
  pairwise logistic loss pulled towards the defaults, and only used when they agree better with held-out
  corrections. The «Learning» page shows them, lets you remove corrections and set each signal's level.
- **State**: `data/projects/<id>/project.json` (+ song, videos, undo history); photo scores in `data/scores.sqlite`.

## License
Copyright (C) 2026 Rafa Campos

Slidesong is free software: you can redistribute it and/or modify it under the terms of the
[GNU Affero General Public License](LICENSE) as published by the Free Software Foundation, version 3.
It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the license for details.

If you run a modified Slidesong for other people over a network, the AGPL asks you to offer them its source:
point `SLIDESONG_SOURCE_URL` to it (the «Source code» link at the bottom of the home page).

## Third-party software, models and data
Nothing third-party is included in this repository except the two fonts burnt into videos (`slidesong/fonts/`,
with their licences). Everything else is installed or downloaded by whoever runs Slidesong, under its own licence:
- [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) in the worker's `scorer/`:
  **AGPL-3.0**.
- [Recognize Anything (RAM++)](https://github.com/xinyu1205/recognize-anything) in `tagger/`, code and weights:
  Apache-2.0. [MediaPipe](https://github.com/google-ai-edge/mediapipe) face landmarks: Apache-2.0.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and the Whisper models: MIT.
  [librosa](https://librosa.org): ISC. [OpenTimelineIO](https://opentimeline.io): Apache-2.0.
- Optional translators: NLLB-200 (CC-BY-NC-4.0, non-commercial), opus-mt-es-en (Apache-2.0).
- Place names: [GeoNames](https://www.geonames.org) (CC BY 4.0), downloaded on first use and credited where they
  are shown.
- Fonts: Caveat, Fredoka (burnt into videos, `slidesong/fonts/`), Instrument Sans and Instrument Serif: SIL Open
  Font License 1.1.
- On the GPU worker, PyTorch and faster-whisper use NVIDIA's CUDA libraries, installed from NVIDIA under its own
  (proprietary) licence.
- Python and JavaScript dependencies: permissive or weak-copyleft licences (MIT, BSD, ISC, Apache-2.0, MPL-2.0,
  LGPL), all compatible with the AGPL.
