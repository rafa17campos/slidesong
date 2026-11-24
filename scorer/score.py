"""Per-photo quality scores, run on the GPU worker in its own venv.

    python score.py input.json output.jsonl

input.json: {"immich_url", "immich_key"} or {"images_url": "http://slidesong-host:8096", "token"}, "items": [{"id": uuid, "faces": [{"box": [x1,y1,x2,y2], "name": str, "person_id": uuid|null}]}]}
output.jsonl: one JSON per photo as soon as it is done (the worker reads the line count for progress):
  aesthetic   aesthetic-predictor v2.5 (SigLIP), roughly 1..10
  sharp       Laplacian variance of the whole photo (log10), higher = sharper
  bright      mean luminance 0..1; clip_hi / clip_lo = fraction of blown / crushed pixels
  faces[]     per Immich face: smile 0..1, eyes_open 0..1, frontal (bool), yaw/pitch (deg), sharp (log10), found,
              focus: sharpness of the face itself (eyes/nose/mouth, same scale for every face); below ~1.8 the face
              looks soft. Only for faces at least 100 px wide (smaller ones always look soft). The older "sharp"
              includes the background around the face, so a sharp textured wall made a blurry face look sharp.
              A face under ORIGINAL_BELOW px wide in the preview is measured on the original photo: the preview
              blurs small faces, so their focus read soft and their expression was guessed from a few pixels.
              Only image originals are downloaded (never a video's), and only a crop around each small face is
              kept; when the original cannot be had, that face is measured on the preview as before.
              person_id: the Immich person the face is assigned to (lowercase UUID), null when it has none; left
              out when the input face did not say (an older client that sends faces without it).
"""
import io
import json
import math
import sys
import threading
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import httpx
import numpy as np
import pillow_heif
import torch
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

HERE = Path(__file__).resolve().parent
LANDMARKER = HERE / "face_landmarker.task"
LANDMARKER_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
                  "float16/latest/face_landmarker.task")
BATCH = 16
VERSION = 3
ORIGINAL_BELOW = 200
ORIGINALS_AT_ONCE = 2  # decoded originals in memory at the same time


def load_aesthetic():
    from aesthetic_predictor_v2_5 import convert_v2_5_from_siglip
    model, prep = convert_v2_5_from_siglip(low_cpu_mem_usage=True, trust_remote_code=True)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32  # Turing has no bfloat16
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return model.to(dtype).to(dev).eval(), prep, dtype, dev


def load_landmarker():
    if not LANDMARKER.exists():
        urllib.request.urlretrieve(LANDMARKER_URL, LANDMARKER)
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(LANDMARKER)),
                                        output_face_blendshapes=True, output_facial_transformation_matrixes=True,
                                        num_faces=1, running_mode=vision.RunningMode.IMAGE)
    return vision.FaceLandmarker.create_from_options(opts)


def lap_sharp(gray):
    return round(math.log10(cv2.Laplacian(gray, cv2.CV_64F).var() + 1.0), 3)


def face_focus(im, box):
    """Laplacian variance (log10) of the inner face, resized so the face box is 200 px wide. None if too small."""
    W, H = im.size
    x1, y1, x2, y2 = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    w, h = x2 - x1, y2 - y1
    if w < 100 or h < 100:
        return None
    inner = im.crop((int(x1 + .2 * w), int(y1 + .2 * h), int(x2 - .2 * w), int(y2 - .15 * h)))
    s = 200 / w
    g = np.asarray(inner.resize((max(8, int(inner.width * s)), max(8, int(inner.height * s))), Image.BICUBIC)
                   .convert("L"), dtype=np.float64)
    lap = g[1:-1, 1:-1] * -4 + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return round(float(np.log10(lap.var() + 1)), 3)


def face_scores(landmarker, rgb, box, name):
    import mediapipe as mp
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    cx, cy, s = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 1.8
    a, b = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
    crop = rgb[b:int(min(h, cy + s / 2)), a:int(min(w, cx + s / 2))]
    out = {"name": name, "box": box, "found": False}
    if crop.size == 0:
        return out
    if max(crop.shape[:2]) < 256:  # MediaPipe likes faces of a decent size
        f = 256 / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(cv2.resize(crop, (160, 160)), cv2.COLOR_RGB2GRAY)
    out["sharp"] = lap_sharp(g)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
    if not res.face_blendshapes:
        return out
    bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
    out["found"] = True
    out["smile"] = round((bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0)) / 2, 3)
    out["eyes_open"] = round(1 - max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)), 3)
    if res.facial_transformation_matrixes:
        R = np.array(res.facial_transformation_matrixes[0])[:3, :3]
        yaw = math.degrees(math.atan2(-R[2, 0], math.hypot(R[2, 1], R[2, 2])))
        pitch = math.degrees(math.atan2(R[2, 1], R[2, 2]))
        out["yaw"], out["pitch"] = round(yaw, 1), round(pitch, 1)
        out["frontal"] = abs(yaw) < 25 and abs(pitch) < 25
    return out



def person_id(face):
    """The input face's Immich person id in canonical lowercase form; None when unassigned or not a UUID."""
    pid = face.get("person_id")
    try:
        return str(uuid.UUID(str(pid))) if pid else None
    except ValueError:
        return None


def face_entry(scores, face, focus):
    """One faces[] entry of the record: the measured scores, the input box, the focus and (when the input carries
    it) the person id, last so the earlier keys keep their order."""
    out = {**scores, "box": face["box"], "focus": focus}
    if "person_id" in face:
        out["person_id"] = person_id(face)
    return out


def _image_source(job):
    """(preview URL template, original URL template, client), templates with {id}: Immich itself when the worker
    has a key, else the Slidesong app (which goes to Immich for it)."""
    if job.get("immich_url"):
        base = job["immich_url"].rstrip("/") + "/api/assets/{id}"
        return (base + "/thumbnail?size=preview", base + "/original",
                httpx.Client(timeout=120, headers={"x-api-key": job["immich_key"]}))
    token = job.get("token", "")
    base = job["images_url"].rstrip("/") + "/api/assets/{id}"
    return (base + "/preview", base + "/original",
            httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"} if token else {}))


def _small_face(im, face):
    return (face["box"][2] - face["box"][0]) * im.width < ORIGINAL_BELOW


_warned = set()


def warn_once(key, msg):
    """One line on stderr (the worker shows lines starting with "warning:" in its log)."""
    if key not in _warned:
        _warned.add(key)
        print("warning: " + msg, file=sys.stderr, flush=True)


def face_crops(orig, im, faces):
    """{face index: (crop, box relative to the crop)} for the small faces, cut from the original photo so the
    original itself can be let go at once (a 50 MP photo is 150 MB decoded). Each crop holds the face plus its
    own size on every side, more than face_scores and face_focus look at, so they measure the same pixels."""
    W, H = orig.size
    if abs(W / H - im.width / im.height) > 0.02 * im.width / im.height:
        return {}  # not the same framing as the preview (edited, or a RAW's embedded preview): stay on the preview
    out = {}
    for i, f in enumerate(faces):
        if not _small_face(im, f):
            continue
        x1, y1, x2, y2 = f["box"][0] * W, f["box"][1] * H, f["box"][2] * W, f["box"][3] * H
        cx, cy, s = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1)
        a, b = max(0, int(cx - s)), max(0, int(cy - s))
        c, d = min(W, math.ceil(cx + s)), min(H, math.ceil(cy + s))
        if c - a < 2 or d - b < 2:
            continue
        w, h = c - a, d - b
        out[i] = (orig.crop((a, b, c, d)), [(x1 - a) / w, (y1 - b) / h, (x2 - a) / w, (y2 - b) / h])
    return out


def main(inp, outp):
    job = json.loads(Path(inp).read_text(encoding="utf-8"))
    items = job["items"]
    preview_url, original_url, client = _image_source(job)
    model, prep, dtype, dev = load_aesthetic()
    landmarker = load_landmarker()
    originals = threading.Semaphore(ORIGINALS_AT_ONCE)

    def decode(data):
        try:
            return ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except Exception:  # not an image Pillow reads (RAW, damaged file, decompression bomb)
            return None

    def preview(it):
        r = client.get(preview_url.format(id=it["id"]))
        return decode(r.content) if r.status_code == 200 else None

    def original_crops(it, im, faces):
        with client.stream("GET", original_url.format(id=it["id"])) as r:
            if r.status_code in (401, 403):
                warn_once("denied", f"the original photos are not allowed (HTTP {r.status_code}): small faces are "
                          "measured on the preview. Give the worker's Immich key asset.download.")
                return {}
            # a video, or anything that is not a photo: do not download it at all
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
                return {}
            data = r.read()
        with originals:  # only a few decoded originals in memory at once
            orig = decode(data)
            del data
            return face_crops(orig, im, faces) if orig is not None else {}

    def fetch(it):
        try:
            im = preview(it)
        except httpx.HTTPError:
            im = None
        if im is None:
            return it, None, {}
        faces = it.get("faces", [])
        crops = {}
        if any(_small_face(im, f) for f in faces):
            try:
                crops = original_crops(it, im, faces)
            except httpx.HTTPError:
                pass  # the original is a bonus: its faces stay measured on the preview
        return it, im, crops

    lock = threading.Lock()
    with open(outp, "w", encoding="utf-8") as fo, ThreadPoolExecutor(8) as pool:
        for start in range(0, len(items), BATCH):
            got = [x for x in pool.map(fetch, items[start:start + BATCH]) if x[1] is not None]
            if not got:
                continue
            pv = prep(images=[im for _, im, _ in got], return_tensors="pt").pixel_values.to(dtype).to(dev)
            with torch.inference_mode():
                aes = model(pv).logits.squeeze(-1).float().cpu().numpy()
            for (it, im, crops), a in zip(got, aes):
                rgb = np.asarray(im)

                def face(i, f):
                    src, box = crops.get(i, (im, f["box"]))
                    return face_entry(face_scores(landmarker, rgb if src is im else np.asarray(src), box,
                                                  f.get("name") or ""), f, face_focus(src, box))

                small = cv2.resize(rgb, None, fx=768 / max(rgb.shape[:2]), fy=768 / max(rgb.shape[:2]),
                                   interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
                rec = {"id": it["id"], "v": VERSION, "aesthetic": round(float(a), 3), "sharp": lap_sharp(gray),
                       "bright": round(float(gray.mean() / 255), 3),
                       "clip_hi": round(float((gray > 250).mean()), 4), "clip_lo": round(float((gray < 5).mean()), 4),
                       "faces": [face(i, f) for i, f in enumerate(it.get("faces", []))]}
                with lock:
                    fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fo.flush()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
