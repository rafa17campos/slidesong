"""Object/scene tags per photo with RAM++ (Recognize Anything Plus), run on the GPU worker in its own venv.

    python tag.py input.json output.jsonl

input.json: {"immich_url", "immich_key"} or {"images_url": "http://slidesong-host:8096", "token"}, plus "items": [{"id": uuid}]
output.jsonl: {"id": uuid, "tags": ["dog", "lawn", ...]} per photo (RAM++ default per-class thresholds).
"""
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import torch
from huggingface_hub import hf_hub_download
from PIL import Image, ImageOps

BATCH = 16



def _image_source(job):
    """(URL template with {id}, client) for each photo's preview: Immich itself when the worker has a key, else
    the Slidesong app (which goes to Immich for it)."""
    if job.get("immich_url"):
        return (job["immich_url"].rstrip("/") + "/api/assets/{id}/thumbnail?size=preview",
                httpx.Client(timeout=60, headers={"x-api-key": job["immich_key"]}))
    token = job.get("token", "")
    return (job["images_url"].rstrip("/") + "/api/assets/{id}/preview",
            httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"} if token else {}))

def main(inp, outp):
    from ram import get_transform
    from ram.models import ram_plus
    job = json.loads(Path(inp).read_text(encoding="utf-8"))
    base, client = _image_source(job)
    ckpt = hf_hub_download("xinyu1205/recognize-anything-plus-model", "ram_plus_swin_large_14m.pth")  # worker.TAGGER_MODEL
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = ram_plus(pretrained=ckpt, image_size=384, vit="swin_l").eval().to(dev)
    transform = get_transform(image_size=384)

    def fetch(it):
        r = client.get(base.format(id=it["id"]))
        if r.status_code != 200:
            return it, None
        return it, ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")

    items = job["items"]
    with open(outp, "w", encoding="utf-8") as fo, ThreadPoolExecutor(8) as pool:
        for k in range(0, len(items), BATCH):
            got = [x for x in pool.map(fetch, items[k:k + BATCH]) if x[1] is not None]
            if not got:
                continue
            batch = torch.stack([transform(im) for _, im in got]).to(dev)
            with torch.inference_mode():
                tags, _ = model.generate_tag(batch)
            for (it, _), t in zip(got, tags):
                fo.write(json.dumps({"id": it["id"], "tags": [x.strip() for x in t.split("|") if x.strip()]}) + "\n")
                fo.flush()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
