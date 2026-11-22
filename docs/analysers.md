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
  "version": 2,
  "script": "score.py",
  "face_focus": { "blurry": 1.6, "soft": 1.8 }
}
```
- `name` and `version` are the analyser's identity. The worker announces them (`GET /health`: `scorer_name`,
  `scorer_version`, `scorer_info`, `tagger_model`, `tagger_info`) and Slidesong keeps every record with its
  scorer's identity: records of another scorer, or of another version of it, do not count and the photos are
  scored again. Bump `version` whenever the meaning or scale of a field changes.
- `script`: run as `<folder>/.venv/bin/python <script> input.json output.jsonl` (`.venv\Scripts\python.exe` on
  Windows).
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
`Authorization: Bearer {token}`). Face boxes are relative (0..1) to the photo, with the person's name (empty when
unknown); the tagger gets no faces.

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

The reference scorer also writes `sharp`, `bright`, `clip_hi`, `clip_lo` and per face `yaw`, `pitch`, `sharp`:
kept, not used by the suggestions.

**Tagger**
```json
{ "id": "<asset id>", "tags": ["dog", "lawn", "swimwear"] }
```
Lower-case English nouns. Slidesong matches them with what each lyric line names (`slidesong/lexicon.py`, the
RAM++ tags of every concept) and warns about sensitive photos from these: `shirtless`, `swimwear`, `bikini`,
`swim`, `sunbathe`, `diaper`, `bath`, `belly`. A tagger with another vocabulary works, with fewer matches.
