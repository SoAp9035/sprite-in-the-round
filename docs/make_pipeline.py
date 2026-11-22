#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy>=1.22", "pillow>=9.1"]
# ///
"""Draw docs/pipeline.gif, the README's pipeline banner, from the real car example.

It runs the skill's own steps on evals/files/car_top.png + car_side.png and shows each result:
input -> pixel_grid.py -> voxlib.py (exploding slices) -> stack.py (turning stack).

usage (from the repo root):
  uv run scripts/pixel_grid.py evals/files/car_top.png  -o out/car_top.png
  uv run scripts/pixel_grid.py evals/files/car_side.png -o out/car_side.png
  uv run docs/make_pipeline.py
"""
import math, os, sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from voxlib import load, carve, shade  # noqa: E402
from stack import render  # noqa: E402

BG, DOT = (14, 16, 28), (28, 32, 52)
PANEL, BORDER, BAR = (22, 26, 42), (48, 56, 90), (34, 40, 66)
TEXT, MUTED, ACCENT = (232, 234, 245), (128, 138, 180), (250, 220, 80)
OUTLINE, CHECK = (12, 12, 24), ((36, 40, 60), (46, 52, 76))
KEY = (255, 0, 255)  # transparent corners

FRAMES, MS = 48, 80
M, PW, PH, GAP, BARH = 15, 186, 291, 27, 27
W, H = 2 * M + 4 * PW + 3 * GAP, 2 * M + PH

FONT = {  # 3x5 pixel font, rows top to bottom
    "A": ".#. #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": ".## #.. #.. #.. .##",
    "D": "##. #.# #.# #.# ##.", "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..",
    "G": ".## #.. #.# #.# .##", "H": "#.# #.# ### #.# #.#", "I": "### .#. .#. .#. ###",
    "J": "..# ..# ..# #.# .#.", "K": "#.# #.# ##. #.# #.#", "L": "#.. #.. #.. #.. ###",
    "M": "#.# ### ### #.# #.#", "N": "##. #.# #.# #.# #.#", "O": ".#. #.# #.# #.# .#.",
    "P": "##. #.# ##. #.. #..", "Q": ".#. #.# #.# ##. .##", "R": "##. #.# ##. #.# #.#",
    "S": ".## #.. .#. ..# ##.", "T": "### .#. .#. .#. .#.", "U": "#.# #.# #.# #.# ###",
    "V": "#.# #.# #.# #.# .#.", "W": "#.# #.# ### ### #.#", "X": "#.# #.# .#. #.# #.#",
    "Y": "#.# #.# .#. .#. .#.", "Z": "### ..# .#. #.. ###", "0": "### #.# #.# #.# ###",
    "1": ".#. ##. .#. .#. ###", "2": "##. ..# .#. #.. ###", "3": "##. ..# .#. ..# ##.",
    "4": "#.# #.# ### ..# ..#", "5": "### #.. ##. ..# ##.", "6": ".## #.. ### #.# ###",
    "7": "### ..# .#. .#. .#.", "8": "### #.# ### #.# ###", "9": "### #.# ### ..# ##.",
    ".": "... ... ... ... .#.", "_": "... ... ... ... ###", "-": "... ... ### ... ...",
    "x": "... #.# .#. #.# ...", "+": "... .#. ### .#. ...", "/": "..# ..# .#. #.. #..",
    " ": "... ... ... ... ...",
}
FONT = {k: v.replace(" ", "") for k, v in FONT.items()}
assert all(len(v) == 15 for v in FONT.values())


def text(d, s, x, y, k, colour):
    for ch in s:
        g = FONT[ch if ch == "x" else ch.upper()]
        for i, c in enumerate(g):
            if c == "#":
                px, py = x + (i % 3) * k, y + (i // 3) * k
                d.rectangle([px, py, px + k - 1, py + k - 1], fill=colour)
        x += 4 * k


def text_w(s, k):
    return 4 * k * len(s) - k


def blit(canvas, rgba, x, y, k, blur=0):
    im = Image.fromarray(np.ascontiguousarray(rgba, np.uint8), "RGBA")
    im = im.resize((im.width * k, im.height * k), Image.NEAREST)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(im, (x, y))
    return im.size


def checker(d, box, s=6):
    x0, y0, x1, y1 = box
    for yy in range(y0, y1, s):
        for xx in range(x0, x1, s):
            c = CHECK[((xx - x0) // s + (yy - y0) // s) % 2]
            d.rectangle([xx, yy, min(xx + s, x1) - 1, min(yy + s, y1) - 1], fill=c)


def grid_over(d, x, y, w, h, k):
    for i in range(w + 1):
        d.line([x + i * k, y, x + i * k, y + h * k - 1], fill=BG)
    for j in range(h + 1):
        d.line([x, y + j * k, x + w * k - 1, y + j * k], fill=BG)


def eased(t):
    return t * t * (3 - 2 * t)


def explode(f):
    """Layer spacing over the loop: hold together, spread, hold apart, close again."""
    if f < 8: return 1.0
    if f < 20: return 1.0 + 5.0 * eased((f - 8) / 12)
    if f < 32: return 6.0
    if f < 44: return 6.0 - 5.0 * eased((f - 32) / 12)
    return 1.0


def main():
    out = os.path.join(ROOT, "out")
    top = load(os.path.join(out, "car_top.png"))
    side = load(os.path.join(out, "car_side.png"))
    vol = shade(carve(top=top, side=side))

    base = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(base)
    for yy in range(6, H, 12):
        for xx in range(6, W, 12):
            d.rectangle([xx, yy, xx + 2, yy + 2], fill=DOT)
    titles = ["1 INPUT", "2 PIXEL_GRID.PY", "3 VOXLIB.PY", "4 STACK.PY"]
    captions = ["SPRITE / SHEET / SHOT", "NATIVE 12x18 + 18x8", "8 SLICES", "GLB OBJ VOX GIF"]
    boxes = []
    for i in range(4):
        x0, y0 = M + i * (PW + GAP), M
        d.rectangle([x0, y0, x0 + PW - 1, y0 + PH - 1], fill=BORDER)
        d.rectangle([x0 + 3, y0 + 3, x0 + PW - 4, y0 + PH - 4], fill=PANEL)
        d.rectangle([x0 + 3, y0 + 3, x0 + PW - 4, y0 + BARH], fill=BAR)
        num, name = titles[i].split(" ", 1)
        text(d, num, x0 + 12, y0 + 10, 2, ACCENT)
        text(d, name, x0 + 12 + text_w(num + " ", 2) + 2, y0 + 10, 2, TEXT)
        cw = text_w(captions[i], 2)
        text(d, captions[i], x0 + (PW - cw) // 2, y0 + PH - 22, 2, MUTED)
        boxes.append((x0 + 9, y0 + BARH + 9, x0 + PW - 9, y0 + PH - 33))

    # 1: the input as it arrives (soft, on a transparent-looking background)
    k = 6
    tw, th = top.shape[1] * k, top.shape[0] * k
    sw, sh = side.shape[1] * k, side.shape[0] * k
    x0, y0, x1, y1 = boxes[0]
    gy = y0 + (y1 - y0 - th - 12 - sh) // 2
    checker(d, (x0 + 6, gy - 6, x1 - 6, gy + th + 12 + sh + 6))
    blit(base, top, x0 + (x1 - x0 - tw) // 2, gy, k, blur=1.6)
    blit(base, side, x0 + (x1 - x0 - sw) // 2, gy + th + 12, k, blur=1.6)
    soft = base.crop(boxes[0]).convert("RGB").quantize(48, dither=Image.Dither.NONE).convert("RGBA")
    base.paste(soft, boxes[0][:2])

    # 2: the recovered native pixels, one cell per art pixel
    x0, y0, x1, y1 = boxes[1]
    tx, sx = x0 + (x1 - x0 - tw) // 2, x0 + (x1 - x0 - sw) // 2
    blit(base, top, tx, gy, k)
    blit(base, side, sx, gy + th + 12, k)
    d = ImageDraw.Draw(base)
    grid_over(d, tx, gy, top.shape[1], top.shape[0], k)
    grid_over(d, sx, gy + th + 12, side.shape[1], side.shape[0], k)

    # rounded pixel corners
    for cx, cy, sxn, syn in [(0, 0, 1, 1), (W - 1, 0, -1, 1), (0, H - 1, 1, -1), (W - 1, H - 1, -1, -1)]:
        for dx, dy in [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1), (1, 1), (0, 2), (0, 3)]:
            base.putpixel((cx + sxn * dx, cy + syn * dy), KEY + (255,))

    frames = []
    for f in range(FRAMES):
        fr = base.copy()
        fd = ImageDraw.Draw(fr)

        # 3: the volume as horizontal layers, pulled apart and put back
        x0, y0, x1, y1 = boxes[2]
        img = render(vol, 90, squash=0.33, spacing=explode(f), outline=OUTLINE)
        k3 = 4
        w3, h3 = img.shape[1] * k3, img.shape[0] * k3
        blit(fr, img, x0 + (x1 - x0 - w3) // 2, y1 - h3, k3)

        # 4: the finished stack turning
        x0, y0, x1, y1 = boxes[3]
        img = render(vol, f * 360 / FRAMES, outline=OUTLINE, shadow=True)
        k4 = 5
        w4, h4 = img.shape[1] * k4, img.shape[0] * k4
        blit(fr, img, x0 + (x1 - x0 - w4) // 2, y0 + (y1 - y0 - h4) // 2, k4)

        # arrows with marching dots
        for i in range(3):
            ax = M + (i + 1) * PW + i * GAP
            ay = M + BARH + (PH - BARH) // 2 - 4
            for j in range(3):
                lit = (f // 4 - j) % 3 == 0
                fd.rectangle([ax + 3 + j * 6, ay + 3, ax + 5 + j * 6, ay + 5], fill=ACCENT if lit else BORDER)
            for r in range(3):
                fd.rectangle([ax + 18 + r * 3, ay - 3 + r * 3, ax + 20 + r * 3, ay + 11 - r * 3], fill=ACCENT)
        frames.append(fr.convert("RGB"))

    # one shared palette, KEY = transparent
    colours = set()
    for fr in frames:
        colours.update(c for _, c in fr.getcolors(W * H))
    colours = sorted(colours - {KEY})
    if len(colours) > 255:
        raise SystemExit(f"{len(colours)} colours, GIF allows 255 + transparency")
    pal = [KEY] + colours
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette([v for c in pal for v in c] + [0] * 3 * (256 - len(pal)))
    lut = {c: i for i, c in enumerate(pal)}
    ps = []
    for fr in frames:
        a = np.array(fr)
        idx = np.zeros(a.shape[:2], np.uint8)
        flat = a.reshape(-1, 3)
        keys = flat[:, 0].astype(np.int64) << 16 | flat[:, 1].astype(np.int64) << 8 | flat[:, 2]
        uniq, inv = np.unique(keys, return_inverse=True)
        m = np.array([lut[(int(u) >> 16, int(u) >> 8 & 255, int(u) & 255)] for u in uniq], np.uint8)
        idx = m[inv].reshape(a.shape[:2])
        p = Image.fromarray(idx, "P")
        p.putpalette(pal_img.getpalette())
        ps.append(p)
    path = os.path.join(ROOT, "docs", "pipeline.gif")
    ps[0].save(path, save_all=True, append_images=ps[1:], duration=MS, loop=0, transparency=0,
               disposal=1, optimize=False)
    print(path, f"{W}x{H}", f"{len(pal)} colours", f"{os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main()
