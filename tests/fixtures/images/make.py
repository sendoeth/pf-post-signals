"""Writes the step 18 fixture images (deterministic): a candle chart, a crop of it scaled down, and
an unrelated chart. Run with the .venv python (pillow + numpy)."""
import os
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


def chart(seed, w=600, h=400, label=True, grid=50):
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (w, h), (20, 22, 28))
    d = ImageDraw.Draw(im)
    for y in range(40, h, grid):
        d.line([(0, y), (w, y)], fill=(40, 44, 52))
    p = 200.0
    for i in range(70):
        o = p
        p = max(30.0, min(h - 30.0, p + rng.normal(0, 14)))
        x = 10 + i * 8
        col = (38, 166, 154) if p < o else (239, 83, 80)
        d.line([(x + 2, min(o, p) - rng.integers(2, 12)), (x + 2, max(o, p) + rng.integers(2, 12))], fill=col)
        d.rectangle([x, min(o, p), x + 4, max(o, p) + 1], fill=col)
    if label:
        d.rectangle([520, 300, 590, 318], fill=(239, 83, 80))
        d.text((150, 330), "6.8900", fill=(255, 255, 255))
        d.polygon([(165, 315), (170, 322), (160, 322)], fill=(255, 255, 255))
    return im


if __name__ == "__main__":
    a = chart(7)
    a.save(os.path.join(HERE, "chart.png"))
    a.crop((100, 60, 330, 345)).resize((172, 214), Image.BILINEAR).save(os.path.join(HERE, "crop.png"))   # candles + the label, scaled 0.75
    chart(99, label=False, grid=37).save(os.path.join(HERE, "other.png"))
    print("written")
