# Photo analysers

The GPU worker runs two analysers, each a program in its own folder (and its own Python environment):

- **scorer** (`scorer/`, or the folder in `SCORER_DIR`): quality per photo (looks, faces, sharpness).
- **tagger** (`tagger/`, or `TAGGER_DIR`): what a photo shows, as tags.

The ones shipped are a reference: any program that keeps this contract can replace them (another model, another
licence, your own heuristics).

## Manifest: `analyser.json`
```json
{
  "kind": "scorer",
  "name": "aesthetic-v2.5",
  "version": 4,
  "script": "score.py",
  "local_images": true,
  "face_focus": { "blurry": 1.6, "soft": 1.8 }
}
```
- `name` and `version` are the analyser's identity. The worker announces them (`GET /health`: `scorer_name`,
  `scorer_version`, `scorer_info`, `tagger_model`, `tagger_info`) and Slidesong keeps every record with its
  scorer's identity: records of another scorer, or of another version of it, do not count and the photos are
  scored again. Bump `version` whenever the meaning or scale of a field changes.
- `script`: run as `<folder>/.venv/bin/python <script> input.json output.jsonl` (`.venv\Scripts\python.exe` on
  Windows).
- `local_images` (optional): the script reads an item's `image` (a local file) instead of fetching it (see
  [Videos](#videos)). Without it, the worker analyses videos on their preview only, even when `deep` is asked for.
- `face_focus` (scorer, optional): below `blurry` a face counts as blurry, below `soft` as a bit soft, in the scale
  of the scorer's own `focus`. Without it, face sharpness is not judged.

## Input: `input.json`
```json
{
  "immich_url": "http://immich:2283", "immich_key": "…",
  "items": [{ "id": "<asset id>", "faces": [{ "box": [x1, y1, x2, y2], "name": "Nico" }] }]
}
```
Either `immich_url` + `immich_key` (fetch `GET {immich_url}/api/assets/{id}/thumbnail?size=preview` with the
header `x-api-key`) or `images_url` + `token` (fetch `GET {images_url}/api/assets/{id}/preview` with
`Authorization: Bearer {token}`). The reference scorer also fetches the photo's `original` (same paths, `original`
instead of the preview) when a face is under 200 px wide in the preview, and measures those faces on it: only an
image original (never a video's), keeping just a crop around each small face, and on the preview as before when the
original cannot be had (the worker's Immich key then needs `asset.download`). Face boxes are relative (0..1) to the
photo, with the person's name (empty when unknown) and `person_id` (the Immich person id, null when the face
has none); the tagger gets no faces.

An item may instead carry `image`, the path of a local JPEG (a frame the worker took from a video), with an id of
the form `<asset id>@<seconds>` and no faces: the script reads that file and fetches nothing. Only analysers whose
manifest says `local_images` get such items.

Lines a script writes to stderr starting with `warning: ` show up in the worker's log.

## Output: `output.jsonl`
One JSON object per photo, written as soon as it is done (the worker counts lines for the progress). A photo that
cannot be read is left out. Every field but `id` is optional: what a scorer does not compute simply does not
count.

**Scorer**
| Field | Meaning | Used as |
|---|---|---|
| `id` | the asset id | |
| `aesthetic` | how good the photo looks, any scale | ranked within each project's photos (only the order matters) |
| `faces[]` | one per face of the input, same order | |
| `faces[].box`, `.name` | as given | which faces belong to the project's people; small faces are not judged |
| `faces[].found` | the face could be analysed | only found faces count |
| `faces[].smile` | 0..1 | «smiling» |
| `faces[].eyes_open` | 0..1 | below 0.25 on a big enough face: «eyes closed» |
| `faces[].frontal` | true / false | «looking at the camera» |
| `faces[].focus` | sharpness of the face itself, the scorer's own scale | against `face_focus` |
| `faces[].person_id` | the Immich person the face is assigned to (lowercase UUID), `null` when none; missing in older records and when the input face did not carry a UUID (unknown) | for other apps: matching faces to people by id, not by name |

The reference scorer also writes `sharp`, `bright`, `clip_hi`, `clip_lo` and per face `yaw`, `pitch`, `sharp`:
kept, not used by the suggestions.

**Tagger**
```json
{ "id": "<asset id>", "tags": ["dog", "lawn", "swimwear"] }
```
Lower-case English nouns. Slidesong matches them with what each lyric line names (`slidesong/lexicon.py`, the
RAM++ tags of every concept) and warns about sensitive photos from these: `shirtless`, `swimwear`, `bikini`,
`swim`, `sunbathe`, `diaper`, `bath`, `belly`. A tagger with another vocabulary works, with fewer matches.

## Videos

`POST /score` and `POST /tag` take an optional form field `video_mode`:

- `fast` (the default, also when the field is absent or empty): a video is analysed on Immich's preview only, like
  a photo. Its record is the same as a photo's.
- `deep`: a video is analysed on frames sampled from the video itself, plus Immich's preview, and its lines are
  folded into one record per video. For callers that can wait (a whole library in the background); building
  something interactively, use `fast`.

Anything else is refused (`400`). Photos are analysed the same way in both modes and their records do not change.

**What is analysed.** For each item the worker asks Immich for the asset (`GET /api/assets/{id}`: type, duration,
checksum), one request per item: a client that knows its photos are photos says so with `"type": "IMAGE"` in the
item (Immich's name) and spares the request; the field is optional and anything else is looked up. For a video, frames every 5 s from 1 s on (many videos open on black or a fade); a video longer than
150 s has them spread over its length so it never gets more than 30. A video under about 1.2 s gets its preview
only. Immich's preview is always analysed too: Immich's face boxes are relative to it, so faces (smile, eyes open,
focus, person ids) are measured on the preview only.

**How frames are read.** ffmpeg seeks straight into Immich's playback stream (`/api/assets/{id}/video/playback`,
which serves HTTP Range) and decodes one frame per point, so a long video is not downloaded whole: about 6 MB per
frame on a 20 Mbit/s phone video (the file's index plus one group of pictures), against the whole file otherwise.
Frames come from the video stream with the most frames, never a cover picture: a phone's motion-photo clip (the
hidden video half of a live photo) also carries its still as a one-frame video stream with more pixels, which ffmpeg
would pick on its own. Frames are JPEGs about the size of Immich's preview (1440 px on the longer side), HDR videos (PQ, HLG) tone-mapped
to SDR when the worker's ffmpeg has the `zscale` filter (a warning in the log otherwise). The worker's Immich key
also needs `asset.view` for the playback stream (already in the list of the README). The key reaches ffmpeg as a
command-line argument, so other processes on the GPU machine can see it: run the worker under its own user, or on a
machine of its own.

**Frames are shared by jobs.** They are kept in `WORKER_DIR/slidesong-worker/frames/`, one folder per video and
version of it (Immich's checksum), so a client's `/tag` job and its `/score` job of the same videos extract them
once. Only a complete extraction is kept: frames missing for any reason (a read Immich or the network cut short
can look like a time with no frame) are tried again by the next job. Folders unused for 6 h are deleted, and the oldest ones while the cache holds more than
`WORKER_FRAME_CACHE_MB` (2048 MB by default; a 30-frame video takes about 3–4 MB); the frames of the running job
are never deleted.

**When `deep` cannot be honoured** the worker analyses videos as `fast` and says why in its log:
- it has no Immich key of its own (it fetches through Slidesong: `images_url` + `token`); Slidesong only asks for
  `fast`, so it serves no frames;
- the analyser's manifest does not say `local_images`;
- ffmpeg or ffprobe is not on the PATH.

`GET /health` says `video_modes: ["fast", "deep"]` and `video_deep` (the worker has its own Immich key, ffmpeg and ffprobe);
`scorer_info.local_images` / `tagger_info.local_images` say whether each analyser reads frames.

A video ffmpeg cannot read, or in which it finds no frame at any sampled time, is analysed on its preview, with one
`warning: ` line in the worker's log saying which. A video
Immich does not describe (the asset lookup fails: the key needs `asset.read`) is analysed as `fast`, with one line
in the log per job saying how many and why.

**Progress and cancel.** Taking the frames counts as the first 30 % of the job (by videos), the analysers the rest
(by output lines over every analysed image, so a video is still one item of the result). Cancelling the job stops
ffmpeg and the analyser at once.

### A video's record (`deep`)

Fields added to every video analysed `deep` (an image's record never has them, and a record without them is a
photo or a video analysed `fast`):

| Field | Meaning |
|---|---|
| `video_mode` | `"deep"` |
| `video_frames` | images analysed: the preview plus the frames read (1 when only the preview was: a very short video, or one ffmpeg could not read) |

**Scorer**: `aesthetic`, `sharp`, `bright`, `clip_hi` and `clip_lo` are the **median** over every analysed image,
the preview included: it describes the whole video, is not pulled down by a few black or shaken frames, and stays
comparable with a photo's score (the best of 30 frames would rank every video above the photos). Also:

| Field | Meaning |
|---|---|
| `aesthetic_best` | the `aesthetic` of the best-looking analysed image |
| `best_at` | seconds into the video of that image; `0` when it is the preview |

`faces` (and `v`, and any other field a scorer writes) are the preview's. The scorer's `version` does not change
with the video mode: a `fast` record of a video is as valid as before, and a client that wants it analysed deep
asks again with `deep` (telling the two apart by `video_mode`).

**Tagger**: the preview's tags, plus those seen on the frames: a sensitive tag (`shirtless`, `swimwear`,
`bikini`, `swim`, `sunbathe`, `diaper`, `bath`, `belly`) when it is on any frame, since the warning would rather
have one too many; any other tag when it is on at least 2 of the analysed images (a tag on one frame only is often
a mistake of the model). In the order they first appear.
