"""Auto thumbnail: dramatic frame (Gemini's pick, sanity-checked) + big Thai title (Pillow + raqm shaping)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat
from .util import run, ts_to_sec
from .config import FONTS

def _frame(master, t, out):
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(master), "-frames:v", "1", "-q:v", "2", str(out)])
    return Image.open(out).convert("RGB")

def _score(img):
    g = img.convert("L"); bright = ImageStat.Stat(g).mean[0]
    edges = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).stddev[0]
    return edges - (40 if bright < 50 else 0) - (30 if bright > 215 else 0)

def pick_frame(master, analysis, workdir: Path):
    cands = []
    bt = analysis.get("best_thumbnail_time")
    if bt:
        cands.append((ts_to_sec(bt), 3))
    scenes = [s for s in analysis.get("scenes", []) if s.get("shot") not in ("title_card", "credits")]
    for s in sorted(scenes, key=lambda s: -(s.get("dramatic_score") or 0))[:4]:
        cands.append(((s["start_s"] + s["end_s"]) / 2, 0))
    best = None
    for k, (t, bonus) in enumerate(cands):
        img = _frame(master, t, workdir / f"thumbcand_{k}.jpg")
        sc = _score(img) + bonus * 5
        if best is None or sc > best[0]:
            best = (sc, img, t)
    return best[1], best[2]

def _fit_font(draw, text, path, max_w, start):
    size = start
    while size > 30:
        f = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)
        if draw.textlength(text, font=f, language="th") <= max_w:
            return f
        size -= 4
    return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)

def make(frame: Image.Image, title, title2, out: Path, aspect="16:9"):
    W, H = (1280, 720) if aspect == "16:9" else (1080, 1920)
    def cover(im, w, h):
        s = max(w / im.width, h / im.height)
        im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
        l = (im.width - w) // 2; t = (im.height - h) // 2
        return im.crop((l, t, l + w, t + h))
    if aspect == "16:9" or frame.width / frame.height < 1.0:
        img = cover(frame, W, H)
    else:
        # vertical cover from a wide frame: blurred fill + big centered picture (avoids a blurry 3x upscale crop)
        img = cover(frame, W, H).filter(ImageFilter.GaussianBlur(28))
        img = ImageEnhance.Brightness(img).enhance(0.75)
        fw = int(W * 1.18); fh = int(fw / 1.6)
        fg = cover(frame, fw, fh)
        img.paste(fg, ((W - fw) // 2, int(H * 0.30)))
    img = ImageEnhance.Contrast(img).enhance(1.15); img = ImageEnhance.Color(img).enhance(1.3)
    # bottom gradient for text legibility
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(max(0, (y - H * 0.45) / (H * 0.55)) * 210))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), grad.resize((W, H)))
    d = ImageDraw.Draw(img)
    big = _fit_font(d, title, FONTS / "Kanit-Black.ttf", W * 0.92, 150 if aspect == "16:9" else 140)
    y_title = int(H * (0.62 if aspect == "16:9" else 0.72))
    d.text((W // 2, y_title), title, font=big, fill=(255, 229, 0), stroke_width=max(6, big.size // 12),
           stroke_fill=(0, 0, 0), anchor="mm", language="th")
    if title2:
        sm = _fit_font(d, title2, FONTS / "Kanit-ExtraBold.ttf", W * 0.8, 70 if aspect == "16:9" else 76)
        bbox = d.textbbox((W // 2, y_title + int(big.size * 0.95)), title2, font=sm, anchor="mm", language="th")
        pad = 18
        d.rounded_rectangle((bbox[0] - pad, bbox[1] - pad // 2, bbox[2] + pad, bbox[3] + pad // 2), radius=12, fill=(210, 20, 30))
        d.text((W // 2, y_title + int(big.size * 0.95)), title2, font=sm, fill=(255, 255, 255), anchor="mm", language="th")
    img.save(out, quality=92)
    return out
