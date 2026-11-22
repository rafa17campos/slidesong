"""Video rendering: executes an edit plan (plan.py): camera moves (zoom, pan, tilt), diptychs, blurred background
as a fallback, and the transitions chosen by the plan (cut, fade, push, dips, flash, zoom, slide, wipe, whip,
iris, blur, light leak), plus the title."""
import io
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
from . import immich
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from . import config

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

FPS = 30         # previews, shot snippets and the per-shot clips of the export
FINAL_FPS = 60   # final videos: slow zooms and pans look much smoother
SIZES = {"preview": (640, 360), "final": (1920, 1080), "final2k": (2560, 1440), "final4k": (3840, 2160)}
XFADE = 0.45          # crossfade between shots, in seconds
FADE_IN, FADE_OUT = 0.8, 1.8
# slidesong/fonts; an older copy of the GPU worker may still have them where the first interface kept them
FONT_DIR = next((d for d in (Path(__file__).resolve().parent / "fonts",
                             Path(__file__).resolve().parent.parent / "static" / "fonts") if d.is_dir()),
                Path(__file__).resolve().parent / "fonts")


def _open(data):
    return Image.open(io.BytesIO(data))


_SRGB = None


def to_srgb(im):
    """Convert an image with an embedded colour profile (Display P3 from phones, Adobe RGB...) to sRGB, which is
    what video uses; reading P3 values as if they were sRGB made colours look dull."""
    global _SRGB
    prof = im.info.get("icc_profile")
    if not prof:
        return im.convert("RGB")
    try:
        from PIL import ImageCms
        if _SRGB is None:
            _SRGB = ImageCms.createProfile("sRGB")
        src = ImageCms.ImageCmsProfile(io.BytesIO(prof))
        if "srgb" in ImageCms.getProfileDescription(src).lower().replace(" ", ""):
            return im.convert("RGB")
        return ImageCms.profileToProfile(im.convert("RGB"), src, _SRGB, outputMode="RGB",
                                         renderingIntent=ImageCms.Intent.PERCEPTUAL)
    except Exception:
        return im.convert("RGB")


def load_image(meta, need_px, use_original=True):
    """Return an oriented RGB uint8 array (fetched from the Immich API). need_px = desired long side."""
    im = None
    pv = immich.fetch(meta["id"], "preview")
    if use_original:
        got = immich.fetch(meta["id"], "original")
        if got:
            try:
                im = _open(got[0])
                if im.format == "JPEG":
                    im.draft("RGB", (need_px, need_px))
                icc = im.info.get("icc_profile")
                im = ImageOps.exif_transpose(im)
                if icc:
                    im.info["icc_profile"] = icc
                im = to_srgb(im)
                # orientation must match the preview (face boxes are relative to it)
                if pv:
                    pw, ph = _open(pv[0]).size
                    if (pw > ph) != (im.width > im.height) and abs(pw - ph) > 10:
                        im = None
            except Exception:
                im = None
    if im is None:
        if not pv:
            raise RuntimeError(f"Can't read photo {meta['id']}")
        im = _open(pv[0]).convert("RGB")
    scale = need_px / max(im.size)
    if scale < 1:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    return np.asarray(im)


MAX_MAG, REF_W = 1.15, 1920  # never magnify the original photo more than this, measured at 1080p (pixelation)


def _src_k(photo, img):
    """Original pixels per loaded pixel: images are loaded smaller than the original, the limit is about the
    original's resolution."""
    m = getattr(photo, "meta", None) or {}
    w, h = m.get("w"), m.get("h")
    return max(1.0, max(w, h) / max(img.shape[:2])) if w and h else 1.0


def face_box(meta):
    """Union of the selected people's faces (or all faces) in relative coords, or None."""
    fl = meta.get("faces") or []
    sel = [f["box"] for f in fl if f.get("selected")] or [f["box"] for f in fl]
    if not sel:
        return None
    return (min(b[0] for b in sel), min(b[1] for b in sel), max(b[2] for b in sel), max(b[3] for b in sel))


def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def _blur_bg(img, W, H):
    ih, iw = img.shape[:2]
    s = max(W / iw, H / ih)
    bg = cv2.resize(img, (max(W, round(iw * s)), max(H, round(ih * s))), interpolation=cv2.INTER_AREA)
    y0, x0 = (bg.shape[0] - H) // 2, (bg.shape[1] - W) // 2
    bg = bg[y0:y0 + H, x0:x0 + W]
    bg = cv2.GaussianBlur(cv2.resize(bg, (max(1, W // 4), max(1, H // 4))), (0, 0), max(2, W // 160))
    return (cv2.resize(bg, (W, H)) * 0.5).astype(np.uint8)


class Photo:
    """A photo plus its layout facts (aspect from the small preview, faces from Immich)."""

    def __init__(self, asset_id, meta, use_original):
        self.id, self.meta, self.use_original = asset_id, {**meta, "id": asset_id}, use_original
        if meta.get("aspect"):  # computed by the planner
            self.aspect = meta["aspect"]
        else:
            pv = immich.fetch(asset_id, "preview")
            w, h = _open(pv[0]).size if pv else (meta.get("w") or 4, meta.get("h") or 3)
            self.aspect = w / h
        self.box = face_box(meta)
        self._img = None

    def image(self, px):
        if self._img is None:
            self._img = cv2.cvtColor(load_image(self.meta, px, self.use_original), cv2.COLOR_RGB2BGR)
        return self._img

    @property
    def portrait(self):
        return self.aspect < 0.95

    def tilt_fits(self, A):
        """Can a full-width crop with aspect A show all the faces (with some margin)?"""
        if not self.box or not self.portrait:
            return False
        crop_h_rel = self.aspect / A  # crop height relative to the image height
        return (self.box[3] - self.box[1]) <= 0.8 * crop_h_rel


class Cover:
    """Photo filling a W x H area with a camera move. motion: in | out | pan_lr | pan_rl | tilt_down | tilt_up."""

    ZOOM_RATE, ZOOM_MIN, ZOOM_MAX = 0.07, 0.12, 0.35  # zoom shots: ~7 % per second of shot, between 12 and 35 %
    FACE_RATE, FACE_MIN, FACE_MAX = 0.10, 0.18, 0.50  # with faces the camera goes closer to them

    def __init__(self, photo, W, H, motion, px, amp=1.0, dur=None, res=None, cap=True):
        self.W, self.H, self.motion, self.amp = W, H, motion, amp
        res = REF_W / W if res is None else res          # output pixels -> 1080p-equivalent pixels
        self.img = photo.image(px)
        ih, iw = self.img.shape[:2]
        self.iw, self.ih = iw, ih
        A = W / H
        self.cw, self.ch = (ih * A, ih) if iw / ih > A else (iw, iw / A)
        b = self.box = photo.box
        self.fx, self.fy = ((b[0] + b[2]) / 2 * iw, (b[1] + b[3]) / 2 * ih) if b else (iw / 2, ih * 0.42)
        # how far the camera moves: at a steady speed (a long shot moves more instead of crawling), scaled by the
        # project's motion style; without a duration (diptych halves) the old fixed 18 %
        rate, lo, hi = (self.FACE_RATE, self.FACE_MIN, self.FACE_MAX) if b else (self.ZOOM_RATE, self.ZOOM_MIN, self.ZOOM_MAX)
        zoom = 0.18 if dur is None else min(hi, max(lo, rate * dur))
        zmax = 1 + zoom * amp
        if b:  # never zoom in so far that faces get cropped (they fill at most 85 % of the view)
            bw, bh = (b[2] - b[0]) * iw, (b[3] - b[1]) * ih
            zmax = max(1.04, min(zmax, 0.85 * self.cw / max(bw, 1), 0.85 * self.ch / max(bh, 1)))
        # ... nor so far that the original photo gets magnified past MAX_MAG (pixelation)
        zres = MAX_MAG * _src_k(photo, self.img) / (res * W / self.cw)
        self.limited = zres < zmax - 1e-3
        self.zmax = max(1.0, min(zmax, zres)) if cap else zmax   # the user's own amount may go past it

    def _view(self, z, cx, cy):
        cw, ch = self.cw / z, self.ch / z
        cx = min(max(cx, cw / 2), self.iw - cw / 2)
        cy = min(max(cy, ch / 2), self.ih - ch / 2)
        return cw, ch, cx, cy

    def frame(self, u):
        e = ease(u)
        m, zm = self.motion, self.zmax
        if m in ("in", "out"):
            t = e if m == "in" else 1 - e
            z = 1 + (zm - 1) * t
            cx = self.iw / 2 * (1 - t) + self.fx * t
            cy = self.ih / 2 * (1 - t) + self.fy * t
            if self.ch < self.ih:  # taller image cropped to 16:9: keep faces in
                cy = self.fy
        elif m in ("pan_lr", "pan_rl"):
            z = min(zm, 1 + 0.15 * self.amp)
            cw = self.cw / z
            lo, hi = cw / 2, self.iw - cw / 2
            mid, half = (lo + hi) / 2, (hi - lo) / 2 * min(1.0, self.amp)  # calm: a shorter pan
            lo, hi = mid - half, mid + half
            if self.box:  # keep the faces inside the frame during the whole pan
                lo = max(lo, self.box[2] * self.iw - cw * 0.95 + cw / 2)
                hi = min(hi, self.box[0] * self.iw + cw * 0.95 - cw / 2)
                if lo > hi:
                    lo = hi = self.fx
            t = e if m == "pan_lr" else 1 - e
            cx = lo + (hi - lo) * t
            cy = self.fy
        else:  # tilt: full-width crop of a portrait gliding onto the faces from a little above or below
            z = min(1.0 + 0.05 * e * self.amp, self.zmax)
            ch = self.ch / z
            faces = self.fy
            # room above the faces? then come down onto them, else come up from below. Decided once from the
            # unzoomed crop (as plan.tilt_dir does): deciding per frame flipped mid-shot when the faces sat right
            # at the limit, and the camera jumped to the other side and came back.
            up = (self.box[1] * self.ih if self.box else self.ih / 2) > self.ch * 0.4
            start = faces - 0.35 * self.ch * self.amp if up else faces + 0.35 * self.ch * self.amp
            cy = start + (faces - start) * e
            cx = self.iw / 2
        cw, ch, cx, cy = self._view(z, cx, cy)
        s = self.W / cw
        M = np.float32([[s, 0, -(cx - cw / 2) * s], [0, s, -(cy - ch / 2) * s]])
        interp = cv2.INTER_AREA if s < 0.7 else cv2.INTER_LINEAR
        return cv2.warpAffine(self.img, M, (self.W, self.H), flags=interp, borderMode=cv2.BORDER_REFLECT)


class Contain:
    """Whole photo over its own blurred background, drifting slightly."""

    START, RATE = 0.90, 0.035  # starts at 90 % of the screen; grows ~3.5 %/s, never past the screen edges

    def __init__(self, photo, W, H, px, zoom_in=True, amp=1.0, dur=None, res=None, cap=True):
        self.W, self.H = W, H
        res = REF_W / W if res is None else res
        self.img = photo.image(px)
        ih, iw = self.img.shape[:2]
        self.iw, self.ih = iw, ih
        self._bg = None  # built on the first frame (planning only needs the numbers)
        self.s0 = min(H / ih, W / iw) * self.START
        # a whole photo must stay whole: the zoom stops just short of the screen edges (it used to grow past them
        # and crop the bottom); at a steady speed like the zoom shots, scaled by the motion style
        grow = (0.07 if dur is None else self.RATE * dur) * amp
        zz = 1 + min(grow, 1 / self.START - 1 - 0.005)
        zres = MAX_MAG * _src_k(photo, self.img) / (res * self.s0)   # pixelation limit
        self.limited = zres < zz - 1e-3
        if cap:
            zz = max(1.0, min(zz, zres))
        self.z = (1.0, zz) if zoom_in else (zz, 1.0)
        self.fy = ((photo.box[1] + photo.box[3]) / 2) if photo.box else 0.42

    @property
    def bg(self):
        if self._bg is None:
            self._bg = _blur_bg(self.img, self.W, self.H)
        return self._bg

    def frame(self, u):
        e = ease(u)
        z = self.z[0] + (self.z[1] - self.z[0]) * e
        s = self.s0 * z
        dw, dh = self.iw * s, self.ih * s
        ox = (self.W - dw) / 2
        oy = (self.H - dh) / 2 + (0.5 - self.fy) * max(0.0, dh - self.H)
        out = self.bg.copy()
        cv2.warpAffine(self.img, np.float32([[s, 0, ox], [0, s, oy]]), (self.W, self.H), dst=out,
                       flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
        return out


def _over(dst, spr, x, y):
    """Alpha-blend a BGRA sprite onto dst with its top-left corner at (x, y), clipped to dst."""
    H, W = dst.shape[:2]
    h, w = spr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.float32) / 255.0
    dst[y0:y1, x0:x1] = (dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a).astype(np.uint8)


def _over_scaled(dst, spr, z, cx, cy):
    """Alpha-blend a BGRA sprite scaled by z and centred at (cx, cy) with sub-pixel precision: resizing to whole
    pixels and rounding the position each frame made slowly growing prints wobble back and forth."""
    H, W = dst.shape[:2]
    h, w = spr.shape[:2]
    tx, ty = cx - z * w / 2, cy - z * h / 2
    x0, y0 = max(0, int(np.floor(tx))), max(0, int(np.floor(ty)))
    x1, y1 = min(W, int(np.ceil(tx + z * w)) + 1), min(H, int(np.ceil(ty + z * h)) + 1)
    if x0 >= x1 or y0 >= y1:
        return
    M = np.float32([[z, 0, tx - x0], [0, z, ty - y0]])
    s = cv2.warpAffine(spr, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(0, 0, 0, 0))
    a = s[..., 3:4].astype(np.float32) / 255.0
    dst[y0:y1, x0:x1] = (dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a).astype(np.uint8)


def _tilt_angle(key):
    """A small, fixed tilt per photo (-4..4 degrees, never straight)."""
    n = sum(ord(c) for c in key)
    return (1.5 + (n % 5) * 0.6) * (1 if n % 2 else -1)


def _hand_font(size):
    """Handwriting font for the captions on prints (Caveat, OFL); the rounded title font as a fallback."""
    for name in ("Caveat.ttf", "Fredoka.ttf"):
        f = FONT_DIR / name
        if f.exists():
            font = ImageFont.truetype(str(f), size)
            try:
                font.set_variation_by_axes([600])
            except Exception:
                pass
            return font
    return ImageFont.load_default(size)


def _over_affine(dst, spr, angle, z, cx, cy):
    """Alpha-blend a BGRA sprite rotated by angle (degrees), scaled by z and centred at (cx, cy), sub-pixel."""
    H, W = dst.shape[:2]
    h, w = spr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, z)
    M[0, 2] += cx - w / 2
    M[1, 2] += cy - h / 2
    corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], np.float32) @ M.T
    x0, y0 = max(0, int(np.floor(corners[:, 0].min()))), max(0, int(np.floor(corners[:, 1].min())))
    x1, y1 = min(W, int(np.ceil(corners[:, 0].max())) + 1), min(H, int(np.ceil(corners[:, 1].max())) + 1)
    if x0 >= x1 or y0 >= y1:
        return
    M[0, 2] -= x0
    M[1, 2] -= y0
    s = cv2.warpAffine(spr, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(0, 0, 0, 0))
    a = s[..., 3:4].astype(np.float32) / 255.0
    dst[y0:y1, x0:x1] = (dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a).astype(np.uint8)


def _vignette(img):
    """Darken the edges a little (prints on a table stand out)."""
    H, W = img.shape[:2]
    yy, xx = np.ogrid[:H, :W]
    r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
    k = (1 - 0.35 * np.clip(r - 0.35, 0, 1)).astype(np.float32)[..., None]
    return (img * k).astype(np.uint8)


class Polaroid:
    """One or two photos as instant prints over the first photo's blurred, vignetted background. Thin white
    frame with a wider bottom edge holding a handwritten caption; a fixed, opposite tilt per print; the prints
    come slowly closer and drift apart; the second one drops onto the table at t_split (from above right,
    turning and settling)."""

    BORDER, BOTTOM = 0.03, 0.12       # side/top border and bottom edge, as a share of the print height

    def __init__(self, photos, W, H, px, t0, t_split, t1, amp=1.0, captions=None):
        self.W, self.H, self.t0, self.ts, self.t1, self.amp = W, H, t0, t_split, t1, amp
        self.bg = _vignette(_blur_bg(photos[0].image(px), W, H))
        pair = len(photos) > 1
        captions = list(captions or []) + [""] * len(photos)
        self.sprites = [self._print(ph, 0.78 if pair else 0.90, captions[n]) for n, ph in enumerate(photos)]
        a0 = abs(_tilt_angle(photos[0].id))
        if pair:  # opposite tilts, the second a bit lower; just touching, so no caption gets covered
            self.layout = [(0.335, 0.5, a0), (0.665, 0.52, -abs(_tilt_angle(photos[1].id)))]
        else:
            self.layout = [(0.5, 0.5, _tilt_angle(photos[0].id))]

    def _print(self, photo, height, caption):
        img = photo.image(int(max(self.W, self.H) * 0.9))
        ih, iw = img.shape[:2]
        ch = int(self.H * height)                         # print height
        b, bottom = int(ch * self.BORDER), int(ch * self.BOTTOM)
        ph_h = ch - b - bottom
        ph_w = int(ph_h * iw / ih)
        if ph_w > self.W * (0.44 if height < 0.85 else 0.8):  # wide photos: limit the width instead
            ph_w = int(self.W * (0.44 if height < 0.85 else 0.8))
            ph_h = int(ph_w * ih / iw)
            ch = ph_h + b + bottom
        cw = ph_w + 2 * b
        card = Image.new("RGBA", (cw, ch), (244, 241, 236, 255))      # warm white (RGB)
        rgb = cv2.cvtColor(cv2.resize(img, (ph_w, ph_h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        card.paste(Image.fromarray(rgb), (b, b))
        if caption:
            size = int(bottom * 0.62)
            font = _hand_font(size)
            d = ImageDraw.Draw(card)
            while size > 10 and d.textlength(caption, font=font) > cw - 2 * b:
                size -= 2
                font = _hand_font(size)
            tw = d.textlength(caption, font=font)
            d.text(((cw - tw) / 2, b + ph_h + (bottom - size) / 2 - size * 0.12), caption, font=font,
                   fill=(70, 62, 55, 255))
        card = cv2.cvtColor(np.asarray(card), cv2.COLOR_RGBA2BGRA)
        m = int(ch * 0.06)                                   # room for the shadow
        canvas = np.zeros((ch + 2 * m, cw + 2 * m, 4), np.uint8)
        sh = np.zeros(canvas.shape[:2], np.float32)
        dx, dy = int(ch * 0.01), int(ch * 0.018)
        sh[m + dy:m + dy + ch, m + dx:m + dx + cw] = 1.0
        sh = cv2.GaussianBlur(sh, (0, 0), ch * 0.018) * 0.55
        canvas[..., 3] = (sh * 255).astype(np.uint8)        # soft black shadow
        _over_bgra(canvas, card, m, m)
        return canvas

    def frame_at(self, t):
        u = min(1.0, max(0.0, (t - self.t0) / max(0.1, self.t1 - self.t0)))
        e = ease(u)
        z = 1.0 + 0.045 * self.amp * e                     # the prints come slowly closer...
        out = self.bg.copy()
        n_prints = len(self.sprites)
        for n, (spr, (px_, py_, ang)) in enumerate(zip(self.sprites, self.layout)):
            drift = (0.012 * self.amp * e) * (-1 if n == 0 else 1) if n_prints > 1 else 0.0  # ...and drift apart
            cx, cy, a, zz = (px_ + drift) * self.W, py_ * self.H, ang, z
            if n_prints == 1:
                a = ang * (1 - 0.3 * e)                     # a single print straightens a little
            if n == 1:  # the second print drops onto the table
                t_in = min(self.ts, self.t0 + 0.8)
                if t < t_in - 0.35:
                    continue
                q = min(1.0, (t - (t_in - 0.35)) / 0.75)
                q = 1 - (1 - q) ** 3                       # ease out
                cx += (1 - q) * self.W * 0.30
                cy -= (1 - q) * self.H * 0.55
                a += (1 - q) * 14
                zz *= 1 + 0.12 * (1 - q)
            _over_affine(out, spr, a, zz, cx, cy)
        return out


def _over_bgra(dst, src, x, y):
    """Composite a BGRA image onto a BGRA canvas (both alpha)."""
    h, w = src.shape[:2]
    d = dst[y:y + h, x:x + w].astype(np.float32) / 255.0
    s = src.astype(np.float32) / 255.0
    a = s[..., 3:4] + d[..., 3:4] * (1 - s[..., 3:4])
    rgb = (s[..., :3] * s[..., 3:4] + d[..., :3] * d[..., 3:4] * (1 - s[..., 3:4])) / np.maximum(a, 1e-6)
    dst[y:y + h, x:x + w] = (np.concatenate([rgb, a], -1) * 255).astype(np.uint8)


class FaceZoom:
    """A portrait going from the whole photo (over its blurred background) to its faces filling the screen, or
    back (to_face=False). The zoom is geometric (even to the eye) and the faces drift to the centre as it grows."""

    def __init__(self, photo, W, H, px, to_face=True, amp=1.0, res=None, cap=True):
        self.W, self.H, self.to_face = W, H, to_face
        res = REF_W / W if res is None else res
        self.img = photo.image(px)
        ih, iw = self.img.shape[:2]
        self._bg = None  # built on the first frame (planning only needs the numbers)
        self.s0 = min(H / ih, W / iw) * Contain.START          # the whole photo
        self.p0 = np.array([iw / 2, ih / 2])
        b = photo.box or [0.3, 0.2, 0.7, 0.5]
        bw, bh = (b[2] - b[0]) * iw, (b[3] - b[1]) * ih
        cover = max(W / iw, H / ih)                             # the photo just covering the screen
        face = min(0.5 * H / max(bh, 1), 0.85 * W / max(bw, 1), 0.85 * H / max(bh, 1))  # faces half the screen tall
        # the amount of movement goes from "just fill the screen" (0) to "faces half the screen" (1) and beyond,
        # never so close that the faces get cut
        s1 = cover * max(1.0, face / cover) ** max(0.0, amp)
        s1 = min(s1, max(cover, 0.85 * W / max(bw, 1), cover), max(cover, 0.85 * H / max(bh, 1)))
        sres = MAX_MAG * _src_k(photo, self.img) / res          # without magnifying the original past MAX_MAG
        self.limited = sres < s1 - 1e-6
        s1 = max(cover, min(s1, sres) if cap else s1)
        self.s1 = s1
        fx, fy = (b[0] + b[2]) / 2 * iw, (b[1] + b[3]) / 2 * ih
        self.p1 = np.array([min(max(fx, W / (2 * s1)), iw - W / (2 * s1)),
                            min(max(fy, H / (2 * s1)), ih - H / (2 * s1))])

    @property
    def bg(self):
        if self._bg is None:
            self._bg = _blur_bg(self.img, self.W, self.H)
        return self._bg

    def frame(self, u):
        e = ease(u) if self.to_face else 1 - ease(u)
        s = self.s0 * (self.s1 / self.s0) ** e
        w = (s - self.s0) / max(1e-9, self.s1 - self.s0)        # the faces reach the centre with the zoom
        p = self.p0 + (self.p1 - self.p0) * w
        out = self.bg.copy()
        M = np.float32([[s, 0, self.W / 2 - p[0] * s], [0, s, self.H / 2 - p[1] * s]])
        cv2.warpAffine(self.img, M, (self.W, self.H), dst=out, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
        return out


class Diptych:
    """Two portrait shots side by side: the first fills the left half; the second slides in on the right
    when its own shot starts. Only photos the user already reviewed are used."""

    GAP = 0.006

    def __init__(self, left, right, W, H, px, t0, t_split, t1, amp=1.0, res=None):
        g = max(2, int(W * self.GAP))
        self.W, self.H, self.g = W, H, g
        self.pw = (W - g) // 2
        res = REF_W / W if res is None else res
        self.left = Cover(left, self.pw, H, "in", px, amp, None, res)
        self.right = Cover(right, W - g - self.pw, H, "out", px, amp, None, res)
        self.bg = _blur_bg(left.image(px), W, H)
        self.t0, self.ts, self.t1 = t0, t_split, t1

    def frame_at(self, t):
        W, H, g, pw = self.W, self.H, self.g, self.pw
        out = self.bg.copy()
        out[:, :pw] = self.left.frame((t - self.t0) / (self.t1 - self.t0))
        # the second photo slides in shortly after the first, so the right half is never left empty for long
        t_in = min(self.ts, self.t0 + 0.8)
        if t >= t_in - 0.3:
            p = ease((t - (t_in - 0.3)) / 0.6)
            rw = W - g - pw
            panel = self.right.frame((t - t_in) / max(0.1, self.t1 - t_in))
            x = pw + g + int(round((1 - p) * (rw + g)))
            if x < W:
                out[:, x:] = panel[:, : W - x]
        return out


class VideoClip:
    """A segment of a video asset (muted), decoded on the fly by ffmpeg straight to the output size.
    Landscape clips fill the frame; portrait/square ones sit over their own blurred, darkened copy."""

    def __init__(self, asset_id, W, H, aspect, clip_start, shot_start, pre, length, fps=FPS):
        import tempfile
        self.W, self.H, self.fps = W, H, fps
        self.shot_start = shot_start
        self.tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        self.tmp.close()
        if not immich.video_to_file(asset_id, self.tmp.name):
            raise RuntimeError(f"Can't download video {asset_id}")
        self.t0 = max(0.0, clip_start - pre)  # clip time of the first decoded frame
        self.offset = clip_start - shot_start  # clip time = song time + offset
        if aspect >= 1.2:
            graph = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}[o]"
        else:
            blur = max(4, min(W, H) // 30)
            graph = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                     f"boxblur={blur}:3,eq=brightness=-0.18[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                     f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps}[o]")
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{self.t0:.3f}", "-t", f"{length + pre + 1.0:.3f}", "-i", self.tmp.name,
             "-filter_complex", graph, "-map", "[o]", "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.idx, self.last = -1, np.zeros((H, W, 3), np.uint8)

    def frame_at(self, t):
        want = max(0, int(round((t + self.offset - self.t0) * self.fps)))
        size = self.W * self.H * 3
        while self.idx < want and self.proc is not None:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:  # end of the clip: keep showing the last frame
                self.close_proc()
                break
            self.last = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
            self.idx += 1
        return self.last

    def close_proc(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self.proc = None

    def close(self):
        self.close_proc()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass


class ShotPlan:
    """One on-screen shot covering one or more song slots."""

    def __init__(self, start, end, make, kind, photos):
        self.start, self.end, self.make, self.kind, self.photos = start, end, make, kind, photos
        self.obj = None
        self.pre = self.post = 0.0  # overlap with neighbours for transitions

    def frame(self, t):
        if self.obj is None:
            self.obj = self.make()
        if isinstance(self.obj, (Diptych, VideoClip, Polaroid)):
            return self.obj.frame_at(t)
        a, b = self.start - self.pre, self.end + self.post
        return self.obj.frame((t - a) / max(1e-3, b - a))


def build_shots(plan, project, photos, W, H, px, fps=FPS):
    """Instantiate the shots of an edit plan (see plan.py)."""
    shots = []
    res = REF_W / W  # every effect measures magnification in 1080p-equivalent pixels
    for sp in plan["shots"]:
        ph = [photos[i] for i in sp["slots"] if i in photos]
        k = sp["kind"]
        cap = sp.get("move") is None  # automatic: never past the pixelation limit; the user's amount: as asked
        if k == "video":
            sp_ = sp
            make = lambda sp=sp_, sh_i=len(shots): VideoClip(
                project["slots"][sp["slots"][0]]["asset"], W, H, sp.get("aspect", 1.78), sp["clip_start"],
                sp["start"], shots[sh_i].pre, sp["end"] - sp["start"] + shots[sh_i].post, fps)
        elif k == "diptych":
            if sp.get("pair"):
                ph = ph + [photos[sp["pair"]]]
            make = lambda a=ph[0], b=ph[1], sp=sp: Diptych(a, b, W, H, px, sp["start"], sp["split"], sp["end"],
                                                           sp.get("amp", 1.0), res)
        elif k in ("polaroid", "polaroid_pair"):
            if sp.get("pair") and k == "polaroid_pair":
                ph = ph + [photos[sp["pair"]]]
            make = lambda ph=ph, sp=sp: Polaroid(ph, W, H, px, sp["start"], sp.get("split", sp["start"]), sp["end"],
                                                 sp.get("amp", 1.0), sp.get("captions"))
        elif k in ("whole_to_face", "face_to_whole"):
            make = lambda a=ph[0], tf=(k == "whole_to_face"), amp=sp.get("amp", 1.0), cap=cap: FaceZoom(a, W, H, px, tf, amp, res, cap)
        elif k.startswith("contain"):
            make = lambda a=ph[0], z=(k == "contain_in"), amp=sp.get("amp", 1.0), d=sp["end"] - sp["start"], cap=cap: \
                Contain(a, W, H, px, z, amp, d, res, cap)
        else:
            make = lambda a=ph[0], m=k, amp=sp.get("amp", 1.0), d=sp["end"] - sp["start"], cap=cap: Cover(a, W, H, m, px, amp, d, res, cap)
        shots.append(ShotPlan(sp["start"], sp["end"], make, k, ph))
    trans = []
    for k, bd in enumerate(plan["boundaries"]):
        d = float(bd.get("dur") or 0.0)
        kind = bd["kind"]
        trans.append((kind, d, bd.get("dir", "left")))
        if kind in OVERLAP_KINDS:
            shots[k].post = shots[k + 1].pre = d / 2
    return shots, trans


def _shift(img, dx, dy):
    """Translate an image by whole pixels (uncovered areas are black)."""
    H, W = img.shape[:2]
    out = np.zeros_like(img)
    xs, xd = (0, dx) if dx >= 0 else (-dx, 0)
    ys, yd = (0, dy) if dy >= 0 else (-dy, 0)
    w, h = W - abs(dx), H - abs(dy)
    if w > 0 and h > 0:
        out[yd:yd + h, xd:xd + w] = img[ys:ys + h, xs:xs + w]
    return out


def _zoomed(img, z):
    H, W = img.shape[:2]
    cw, ch = W / z, H / z
    M = np.float32([[z, 0, -(W - cw) / 2 * z], [0, z, -(H - ch) / 2 * z]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


_radial_cache = {}


def _radial(W, H):
    """Distance to the centre, 0 at the centre and 1 at the corners (cached per size)."""
    if (W, H) not in _radial_cache:
        yy, xx = np.ogrid[:H, :W]
        _radial_cache[(W, H)] = (np.hypot(xx - W / 2, yy - H / 2) / np.hypot(W / 2, H / 2)).astype(np.float32)
    return _radial_cache[(W, H)]


OVERLAP_KINDS = ("fade", "push", "dipwhite", "dipblack", "zoom", "slide", "wipe", "whip", "iris", "blur", "light")


def compose(kind, p, out_f, in_f, direction="left"):
    """Frame of a transition at progress p (0..1) between the outgoing and incoming frames."""
    H, W = out_f.shape[:2]
    if kind == "fade":
        return cv2.addWeighted(out_f, 1 - p, in_f, p, 0)
    if kind in ("dipwhite", "dipblack"):
        color = 255 if kind == "dipwhite" else 0
        base = out_f if p < 0.5 else in_f
        a = 1 - abs(p - 0.5) * 2  # 0 -> 1 -> 0
        return cv2.addWeighted(base, 1 - a, np.full_like(base, color), a, 0)
    if kind == "zoom":  # the outgoing shot rushes in while the next one appears
        z = 1 + 0.35 * ease(p)
        return cv2.addWeighted(_zoomed(out_f, z), 1 - ease(p), in_f, ease(p), 0)
    if kind == "push":
        e = ease(p)
        if direction in ("left", "right"):
            x = int(round(e * W)) * (1 if direction == "left" else -1)
            return np.maximum(_shift(out_f, -x, 0), _shift(in_f, (W if direction == "left" else -W) - x, 0))
        y = int(round(e * H)) * (1 if direction == "up" else -1)
        return np.maximum(_shift(out_f, 0, -y), _shift(in_f, 0, (H if direction == "up" else -H) - y))
    if kind == "slide":  # the next shot slides in over the still outgoing one
        e = ease(p)
        out = out_f.copy()
        if direction in ("left", "right"):
            x = int(round((1 - e) * W))
            if direction == "left":
                out[:, x:] = in_f[:, : W - x]
            else:
                out[:, : W - x] = in_f[:, x:]
        else:
            y = int(round((1 - e) * H))
            if direction == "up":
                out[y:] = in_f[: H - y]
            else:
                out[: H - y] = in_f[y:]
        return out
    if kind == "wipe":  # a soft edge sweeps across the frame
        e = ease(p)
        feather = 0.12
        horiz = direction in ("left", "right")
        ramp = np.linspace(0, 1, W if horiz else H, dtype=np.float32)
        if direction in ("left", "up"):
            ramp = ramp[::-1]
        m = np.clip((e * (1 + feather) - ramp) / feather, 0, 1)
        m = np.ascontiguousarray(np.broadcast_to(m[None, :] if horiz else m[:, None], (H, W)), dtype=np.float32)
        return cv2.blendLinear(out_f, in_f, np.float32(1) - m, m)
    if kind == "whip":  # fast camera whip: both shots fly sideways with motion blur
        e = ease(p)
        horiz = direction in ("left", "right")
        sgn = 1 if direction in ("left", "up") else -1
        L = W if horiz else H
        d = int(round(e * L)) * sgn
        if horiz:
            img = np.maximum(_shift(out_f, -d, 0), _shift(in_f, sgn * L - d, 0))
        else:
            img = np.maximum(_shift(out_f, 0, -d), _shift(in_f, 0, sgn * L - d))
        k = int(np.sin(np.pi * p) * L * 0.12) | 1
        if k > 1:
            img = cv2.blur(img, (k, 1) if horiz else (1, k))
        return img
    if kind == "iris":  # the next shot opens as a growing circle from the centre
        e = ease(p)
        m = np.clip((np.float32(e) * 1.1 - _radial(W, H)) / 0.08, 0, 1).astype(np.float32)
        return cv2.blendLinear(out_f, in_f, np.float32(1) - m, m)
    if kind == "blur":  # dreamy: both shots melt into a blur and the next one comes back into focus
        s = np.sin(np.pi * p) * W / 90
        a = cv2.addWeighted(out_f, 1 - ease(p), in_f, ease(p), 0)
        return cv2.GaussianBlur(a, (0, 0), s) if s > 0.5 else a
    if kind == "light":  # warm light leak sweeping across, like an old film
        e = ease(p)
        base = cv2.addWeighted(out_f, 1 - e, in_f, e, 0)
        w, h = max(8, W // 8), max(8, H // 8)  # the glow is smooth: compute it small and scale it up
        xx = np.linspace(-0.6, 1.6, w, dtype=np.float32)[None, :]
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        glow = np.exp(-((xx - p) ** 2) / 0.12 - (yy - 0.4) ** 2 / 0.8) * np.sin(np.pi * p)
        leak = cv2.resize(np.stack([glow * 60, glow * 160, glow * 255], -1).astype(np.uint8), (W, H),
                          interpolation=cv2.INTER_LINEAR)
        return cv2.subtract(np.full_like(base, 255), cv2.multiply(cv2.subtract(np.full_like(base, 255), base),
                                                                  cv2.subtract(np.full_like(base, 255), leak), scale=1 / 255))
    return in_f if p >= 0.5 else out_f


def video_codec_args(W, fps=FPS):
    if config.env("VCODEC") == "h264_nvenc":
        # bitrate cap grows with the frame size (2 Mb/s at 360p, 8 at 1080p, ~14 at 1440p, 32 at 4K) and with the
        # frame rate (x1.5 at 60 fps); finals (60 fps) also get a finer quality target
        rate = 2 if W < 1280 else max(8, round(8 * (W / 1920) ** 2))
        rate = round(rate * (1.5 if fps > 30 else 1))
        cq = "30" if W < 1280 else ("21" if fps > 30 else "24")
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", cq,
                "-b:v", "0", "-maxrate", f"{rate}M", "-bufsize", f"{2 * rate}M", "-profile:v", "high",
                *(["-level", "5.1"] if W > 2560 else [])]
    return ["-c:v", "libx264", "-preset", "medium" if W >= 1280 else "veryfast", "-crf", "20" if W >= 1280 else "26"]


def _font(size):
    font_path = FONT_DIR / "Fredoka.ttf"
    font = ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default(size)
    try:
        font.set_variation_by_axes([600, 100])
    except Exception:
        pass
    return font


def subtitle_overlay(text, W, H):
    """A lyric line as a subtitle band at the bottom: (BGR float band, alpha band, top row). Long lines wrap."""
    size = int(H * 0.058)
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    rows, cur = [], ""
    for w in text.split():  # greedy wrap to 86 % of the width
        t = f"{cur} {w}".strip()
        if cur and probe.textlength(t, font=font) > W * 0.86:
            rows.append(cur)
            cur = w
        else:
            cur = t
    rows.append(cur)
    line_h = int(size * 1.25)
    pad = int(size * 0.5)
    bh = line_h * len(rows) + 2 * pad
    ov = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    ds, d = ImageDraw.Draw(sh), ImageDraw.Draw(ov)
    for n, r in enumerate(rows):
        x, y = (W - probe.textlength(r, font=font)) / 2, pad + n * line_h
        ds.text((x, y), r, font=font, fill=(0, 0, 0, 220), stroke_width=max(2, size // 12), stroke_fill=(0, 0, 0, 220))
        d.text((x, y), r, font=font, fill=(255, 255, 255, 255))
    sh = sh.filter(ImageFilter.GaussianBlur(size * 0.08))
    ov = Image.alpha_composite(sh, ov)
    a = np.asarray(ov).astype(np.float32)
    y0 = int(H - bh - H * 0.035)
    return a[..., :3][..., ::-1].copy(), a[..., 3:4] / 255.0, y0


def title_overlay(text, W, H):
    if not text:
        return None
    size = int(H * 0.11)
    font = _font(size)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x, y = (W - tw) / 2 - bb[0], H * 0.80 - th - bb[1]
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + size * 0.04, y + size * 0.05), text, font=font, fill=(0, 0, 0, 170))
    sh = sh.filter(ImageFilter.GaussianBlur(size * 0.06))
    ov = Image.alpha_composite(sh, ov)
    d = ImageDraw.Draw(ov)
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    a = np.asarray(ov).astype(np.float32)
    rgb = a[..., :3][..., ::-1]  # BGR
    alpha = a[..., 3:4] / 255.0
    return rgb, alpha


def render(project, assets, song_path, out_path, size=(1920, 1080), progress=None, use_original=True, window=None,
           fps=FPS):
    """The whole video, or only window=(from, to) seconds of it (to preview one shot with its music)."""
    W, H = size
    FPS = fps  # noqa: N806 (the frame rate of this render)
    slots = [s for s in project["slots"] if s.get("asset") in assets]
    if not slots:
        raise RuntimeError("No photos assigned")
    dur = project["song"]["duration"]
    nframes = int(dur * FPS)
    title = title_overlay(project.get("title_overlay") or "", W, H)
    title_end = slots[0]["end"]
    subs = sorted(project.get("subs") or [], key=lambda x: x["start"])  # [{start, end, text}], chosen by the app
    sub_img = {}

    plan = project.get("plan")
    if not plan or not plan.get("shots"):
        raise RuntimeError("The edit plan is missing")
    photos = {i: Photo(project["slots"][i]["asset"], assets[project["slots"][i]["asset"]], use_original)
              for sp in plan["shots"] if sp["kind"] != "video" for i in sp["slots"]}
    # diptychs of one shot: the second photo of the same moment
    photos.update({sp["pair"]: Photo(sp["pair"], assets.get(sp["pair"]) or {}, use_original)
                   for sp in plan["shots"] if sp.get("pair")})
    px = int(max(W, H) * 1.6)
    shots, trans = build_shots(plan, project, photos, W, H, px, fps)
    bounds = [sh.end for sh in shots[:-1]]

    f0, f1 = 0, nframes
    audio_cut = []
    if window:
        f0, f1 = max(0, int(window[0] * FPS)), min(nframes, int(window[1] * FPS))
        audio_cut = ["-ss", f"{f0 / FPS:.3f}", "-t", f"{(f1 - f0) / FPS:.3f}"]
    tmp = Path(str(out_path) + ".part.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", *audio_cut, "-i", str(song_path), "-map", "0:v", "-map", "1:a", *video_codec_args(W, fps), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    k = 0
    try:
        for f in range(f0, f1):
            t = f / FPS
            while k + 1 < len(shots) and t >= shots[k].end:
                k += 1
                if k >= 2:  # free decoded images of shots we will not see again
                    if isinstance(shots[k - 2].obj, VideoClip):
                        shots[k - 2].obj.close()
                    shots[k - 2].obj = None
                    for ph in shots[k - 2].photos:
                        ph._img = None
            img = None
            # inside a transition window around the boundary before or after the current shot?
            flash = 0.0
            for j in (k - 1, k):
                if 0 <= j < len(bounds):
                    kind, d, direction = trans[j]
                    b0 = bounds[j]
                    if kind == "flash" and b0 <= t < b0 + d:
                        flash = 0.85 * (1 - (t - b0) / d) ** 2  # white flash right after a hard cut
                    elif kind not in ("cut", "flash") and d > 0 and b0 - d / 2 <= t < b0 + d / 2:
                        p = (t - (b0 - d / 2)) / d
                        img = compose(kind, p, shots[j].frame(t), shots[j + 1].frame(t), direction)
                        break
            if img is None:
                img = shots[k].frame(t)
            if flash > 0:
                img = cv2.addWeighted(img, 1 - flash, np.full_like(img, 255), flash, 0)
            if title is not None and t < title_end:
                fa = min(1.0, max(0.0, (t - 0.3) / 0.6)) * min(1.0, max(0.0, (title_end - 0.2 - t) / 0.6))
                if fa > 0:
                    rgb, alpha = title
                    a = alpha * fa
                    img = (img * (1 - a) + rgb * a).astype(np.uint8)
            for n, sb in enumerate(subs):  # lyric subtitles (only the band they cover is blended)
                if sb["start"] <= t < sb["end"]:
                    if n not in sub_img:
                        sub_img[n] = subtitle_overlay(sb["text"], W, H)
                    rgb, alpha, y0 = sub_img[n]
                    fa = min(1.0, (t - sb["start"]) / 0.2, (sb["end"] - t) / 0.25)
                    band = img[y0:y0 + rgb.shape[0]]
                    a = alpha * fa
                    img[y0:y0 + rgb.shape[0]] = (band * (1 - a) + rgb * a).astype(np.uint8)
                elif sb["start"] > t:
                    break
            g = min(1.0, t / FADE_IN, (dur - t) / FADE_OUT)
            if g < 1:
                img = (img * max(0.0, g)).astype(np.uint8)
            proc.stdin.write(np.ascontiguousarray(img).tobytes())
            if progress and f % 30 == 0:
                progress((f - f0) / max(1, f1 - f0))
        for sh in shots:
            if isinstance(sh.obj, VideoClip):
                sh.obj.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")
        tmp.replace(out_path)
    finally:
        if proc.poll() is None:
            proc.kill()
        tmp.unlink(missing_ok=True)
        for sh in shots:  # decoders of video clips (a cancelled render must not leave them running)
            if isinstance(sh.obj, VideoClip):
                sh.obj.close()
    return out_path


def render_clips(project, assets, out_dir, size=(1920, 1080), progress=None, use_original=True, handle=0.5):
    """One video file per shot of the plan, with its camera move and `handle` extra seconds before and after
    (so an editor can lay its own transitions over the cut). No audio, no title. Returns
    [{"file", "start", "end", "head", "tail", "kind", "slots"}]: head/tail = seconds of handle actually present."""
    W, H = size
    plan = project.get("plan")
    if not plan or not plan.get("shots"):
        raise RuntimeError("The edit plan is missing")
    dur = project["song"]["duration"]
    photos = {i: Photo(project["slots"][i]["asset"], assets[project["slots"][i]["asset"]], use_original)
              for sp in plan["shots"] if sp["kind"] != "video" for i in sp["slots"]}
    photos.update({sp["pair"]: Photo(sp["pair"], assets.get(sp["pair"]) or {}, use_original)
                   for sp in plan["shots"] if sp.get("pair")})
    px = int(max(W, H) * 1.6)
    shots, _ = build_shots(plan, project, photos, W, H, px)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = sum(sh.end - sh.start for sh in shots) + 2 * handle * len(shots)
    done, info = 0.0, []
    for n, (sh, sp) in enumerate(zip(shots, plan["shots"])):
        head, tail = min(handle, sh.start), min(handle, dur - sh.end)
        sh.pre, sh.post, sh.obj = head, tail, None  # the move spans the clip including its handles
        name = f"shot_{n + 1:03d}.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", *video_codec_args(W), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_dir / name)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        a, b = sh.start - head, sh.end + tail
        nf = int(round((b - a) * FPS))
        try:
            for f in range(nf):
                proc.stdin.write(np.ascontiguousarray(sh.frame(a + f / FPS)).tobytes())
                if progress and f % 30 == 0:
                    progress(min(1.0, (done + f / FPS) / total))
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg failed")
        finally:
            if proc.poll() is None:
                proc.kill()
        if isinstance(sh.obj, VideoClip):
            sh.obj.close()
        sh.obj = None
        for ph in sh.photos:
            ph._img = None
        done += b - a
        info.append({"file": name, "start": sh.start, "end": sh.end, "head": head, "tail": tail, "frames": nf,
                     "kind": sh.kind, "slots": sp["slots"]})
    return info


def motion_mag(kind, w, h, box, dur, amp, W=1920, H=1080):
    """Peak magnification of the original photo (1080p-equivalent pixels) for this shot with this amount of
    movement, without any limit. 1 = pixel for pixel; above MAX_MAG it starts to show, above 1.5 it pixelates."""
    class _P:
        id = "x"
        def __init__(self):
            self.box, self.meta = box, {"w": w, "h": h}
            self._img = np.zeros((max(8, int(200 * h / max(w, h))), max(8, int(200 * w / max(w, h))), 3), np.uint8)
        def image(self, px):
            return self._img
    ph = _P()
    k = _src_k(ph, ph._img)
    if kind in ("in", "out", "pan_lr", "pan_rl", "tilt"):
        c = Cover(ph, W, H, kind, 0, amp, dur, 1.0, cap=False)
        z = c.zmax if kind in ("in", "out") else min(c.zmax, 1 + 0.15 * amp) if kind.startswith("pan") else 1 + 0.05 * amp
        return W / c.cw * z / k
    if kind in ("whole_to_face", "face_to_whole"):
        return FaceZoom(ph, W, H, 0, True, amp, 1.0, cap=False).s1 / k
    if kind.startswith("contain"):
        c = Contain(ph, W, H, 0, True, amp, dur, 1.0, cap=False)
        return c.s0 * c.z[1] / k
    return 1.0


def motion_limited(kind, w, h, box, dur, amp, W=1920, H=1080):
    """Would this shot hit the pixelation limit at 1080p? For the review (cheap: a tiny stand-in image with the
    original's proportions and size). Returns (limited, share of the planned move actually done 0..1)."""
    class _P:
        id = "x"
        def __init__(self):
            self.box, self.meta = box, {"w": w, "h": h}
            self._img = np.zeros((max(8, int(200 * h / max(w, h))), max(8, int(200 * w / max(w, h))), 3), np.uint8)
        def image(self, px):
            return self._img
    try:
        if kind in ("in", "out", "pan_lr", "pan_rl", "tilt"):
            o = Cover(_P(), W, H, kind, 0, amp, dur, 1.0)
            free = Cover(_P(), W, H, kind, 0, amp, dur, 1e-9)
            share = (o.zmax - 1) / max(1e-9, free.zmax - 1)
        elif kind in ("whole_to_face", "face_to_whole"):
            o, free = FaceZoom(_P(), W, H, 0, True, amp, 1.0), FaceZoom(_P(), W, H, 0, True, amp, 1e-9)
            share = np.log(o.s1 / o.s0) / max(1e-9, np.log(free.s1 / free.s0))
        elif kind.startswith("contain"):
            o, free = Contain(_P(), W, H, 0, True, amp, dur, 1.0), Contain(_P(), W, H, 0, True, amp, dur, 1e-9)
            share = (o.z[1] - 1) / max(1e-9, free.z[1] - 1)
        else:
            return False, 1.0
        return bool(o.limited), float(max(0.0, min(1.0, share)))
    except Exception:
        return False, 1.0
