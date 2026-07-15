"""Generate minimal PWA icons (monogram on solid background). Run once."""
from PIL import Image, ImageDraw, ImageFont
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "icons")
os.makedirs(OUT_DIR, exist_ok=True)

BG = (11, 61, 46)      # dark green
FG = (255, 255, 255)

def make_icon(size, path):
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)
    text = "OX"
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.42))
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), text, fill=FG, font=font)
    img.save(path)

make_icon(192, os.path.join(OUT_DIR, "icon-192.png"))
make_icon(512, os.path.join(OUT_DIR, "icon-512.png"))
print("Icons written to", OUT_DIR)
