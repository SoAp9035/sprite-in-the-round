#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy>=1.22", "pillow>=9.1"]
# ///
"""Render a sprite-stack slice sheet so you can check it, and export it.

A slice sheet is one row of equal slices, the ground slice on the left. Each slice is a top-down
picture of one 1-px layer with the object's front facing down (+y), on a transparent background.
An animated stack has one such row per frame (--frames N), all the same size, first frame on top.

usage: stack.py SLICES.png (--count N | --slice-width W) [--frames F] [options]

writes (next to the sheet unless -o):
  NAME_preview.png    always: 8 turns of the stack, then flat views (front, side, back, top) of
                      the volume to compare with the source art; with frames, then one row of
                      8 turns per frame
  NAME.glb            static sheet: coloured surface mesh, Y up, front +Z, 16 art pixels per metre
                      (--ppm N, or --height M to make the mesh M metres tall)
  NAME.obj            the same mesh as OBJ + NAME.mtl + NAME_palette.png (unless --no-obj)
  NAME_dirsN.png      --dirs N: N facings, frame i faces i*360/N deg clockwise from right
                      (8 per row; with frames, one row per facing and one column per frame)
  NAME_turntable.gif  --gif (with frames, it plays the animation while turning)
  NAME_viewer.html    --viewer: self-contained, drag to turn, plays frames
  NAME.vox            --vox: MagicaVoxel model (max 256 per side); NAME_fK.vox per frame
  --all = --dirs 16 --gif --viewer --vox

examples:
  stack.py car_slices.png --count 15
  stack.py car_slices.png --count 15 --outline '#14182e' --all
  stack.py cat_walk_slices.png --count 18 --frames 4 --fps 8 --gif --viewer

Prints one JSON object on stdout: sizes, files and warnings worth acting on.
Exit codes: 0 ok, 2 bad arguments.
"""
import argparse, base64, io, json, math, os, struct, sys

import numpy as np
from PIL import Image

SHX, SHY, SHADOW_A = 0.5, 0.5, 70   # cast shadow per layer (px right, px down), shadow alpha
EPS = 1e-6
HERE = os.path.dirname(os.path.abspath(__file__))


def fail(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(2)


def rnd(v):  # round half up, same as JS Math.floor(v + .5)
    return int(math.floor(v + 0.5))


def hexrgb(s):
    s = s.lstrip("#")
    if len(s) != 6:
        fail(f"colour must be #rrggbb, got {s!r}")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def dilate4(m):
    o = m.copy()
    o[1:] |= m[:-1]; o[:-1] |= m[1:]; o[:, 1:] |= m[:, :-1]; o[:, :-1] |= m[:, 1:]
    return o


def render(vol, deg, squash=0.75, spacing=1.0, outline=None, shadow=False):
    """Draw the stack turned by deg (clockwise on screen; 0 = front facing down/toward the
    camera). Every slice is turned about its centre with nearest-neighbour sampling, squashed
    vertically, then lifted round(z * spacing) px. Same canvas size for every angle."""
    H, D, W = vol.shape[:3]
    pad, diag = 2, int(math.ceil(math.hypot(W, D))) + 2
    gh = max(1, int(math.ceil(diag * squash)))
    lift = rnd((H - 1) * spacing)
    shx = int(math.ceil(H * SHX)) if shadow else 0
    shy = int(math.ceil(H * SHY * squash)) if shadow else 0
    cw, ch = diag + 2 * pad + shx, gh + lift + 2 * pad + shy
    cx = pad + (diag - W) // 2 + W / 2
    a = math.radians(deg)
    cs, sn = math.cos(a), math.sin(a)
    PX, PY = np.meshgrid(np.arange(cw) + 0.5 - cx, (np.arange(gh) + 0.5 - gh / 2) / squash)
    sx = np.floor(PX * cs + PY * sn + W / 2 + EPS).astype(int)
    sy = np.floor(-PX * sn + PY * cs + D / 2 + EPS).astype(int)
    valid = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < D)
    sx, sy = np.clip(sx, 0, W - 1), np.clip(sy, 0, D - 1)
    base = ch - pad - shy - gh
    img = np.zeros((ch, cw, 4), np.uint8)
    shad = np.zeros((ch, cw), bool)
    for z in range(H):
        layer = vol[z][sy, sx]
        m = valid & (layer[..., 3] > 0)
        if not m.any():
            continue
        r0 = base - rnd(z * spacing)
        img[r0:r0 + gh][m] = layer[m]
        if shadow:
            ox, oy = rnd(z * SHX), rnd(z * SHY * squash)
            shad[base + oy:base + oy + gh, ox:] |= m[:, :cw - ox]
    obj = img[..., 3] > 0
    if outline is not None:
        img[dilate4(obj) & ~obj] = (*outline, 255)
    if shadow:
        img[shad & (img[..., 3] == 0)] = (0, 0, 0, SHADOW_A)
    return img


def elevations(vol):
    """Flat views of the volume, drawn like a model sheet: front, side (front to the LEFT), back, top."""
    occ = vol[..., 3] > 0
    H, D, W = occ.shape

    def first(axis, from_end):
        o = np.flip(occ, axis) if from_end else occ
        idx = o.argmax(axis)
        hit = o.any(axis)
        if from_end:
            idx = occ.shape[axis] - 1 - idx
        return idx, hit

    out = []
    i, hit = first(1, True)                                  # front: nearest +y voxel, [z, x]
    z, x = np.indices((H, W))
    out.append(np.where(hit[..., None], vol[z, i, x], 0)[::-1])
    i, hit = first(2, True)                                  # side from +x: [z, y], front on the left
    z, y = np.indices((H, D))
    out.append(np.where(hit[..., None], vol[z, y, i], 0)[::-1, ::-1])
    i, hit = first(1, False)                                 # back: nearest -y voxel, mirrored
    z, x = np.indices((H, W))
    out.append(np.where(hit[..., None], vol[z, i, x], 0)[::-1, ::-1])
    i, hit = first(0, True)                                  # top: highest voxel, [y, x]
    y, x = np.indices((D, W))
    out.append(np.where(hit[..., None], vol[i, y, x], 0))
    return [o.astype(np.uint8) for o in out]


def on_bg(img, bg):
    a = img[..., 3:4] / 255.0
    return (img[..., :3] * a + np.array(bg) * (1 - a)).astype(np.uint8)


def upscale(rgb, k):
    return rgb.repeat(k, 0).repeat(k, 1)


def write_vox(path, vol):
    H, D, W = vol.shape[:3]
    if max(H, D, W) > 256:
        return False
    occ = vol[..., 3] > 0
    inner = occ.copy()
    for ax in range(3):
        for s in (1, -1):
            sh = np.zeros_like(occ)
            src, dst = [slice(None)] * 3, [slice(None)] * 3
            src[ax], dst[ax] = (slice(1, None), slice(None, -1)) if s > 0 else (slice(None, -1), slice(1, None))
            sh[tuple(dst)] = occ[tuple(src)]
            inner &= sh
    zs, ys, xs = np.nonzero(occ & ~inner)          # surface only: hidden voxels add nothing
    cols = vol[zs, ys, xs, :3]
    pal, inv = np.unique(cols, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    if len(pal) > 255:
        q = Image.fromarray(cols[None]).quantize(255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        inv = np.array(q)[0].astype(int)
        pal = np.array(q.getpalette()[:765]).reshape(-1, 3)
    # MagicaVoxel: x right, y away from the viewer, z up. Our +y is the front, so flip y.
    xyzi = np.stack([xs, D - 1 - ys, zs, inv + 1], 1).astype(np.uint8).tobytes()
    rgba = np.zeros((256, 4), np.uint8)
    rgba[:len(pal), :3] = pal
    rgba[:len(pal), 3] = 255
    chunk = lambda tag, body: tag + struct.pack("<ii", len(body), 0) + body
    kids = (chunk(b"SIZE", struct.pack("<iii", W, D, H))
            + chunk(b"XYZI", struct.pack("<i", len(zs)) + xyzi)
            + chunk(b"RGBA", rgba.tobytes()))
    with open(path, "wb") as f:
        f.write(b"VOX " + struct.pack("<i", 150) + b"MAIN" + struct.pack("<ii", 0, len(kids)) + kids)
    return True


def all_warnings(vols, sheet_alpha):
    """Warnings for every frame; a message that holds for only some frames names them."""
    if len(vols) == 1:
        return warnings_for(vols[0], sheet_alpha)
    seen = {}
    for i, v in enumerate(vols):
        for w in warnings_for(v, None):
            if "slice(s) are empty" not in w:        # a walk bob leaves some frames' top layer empty
                seen.setdefault(w, []).append(i)
    union = np.max(np.stack(vols), axis=0)
    for w in warnings_for(union, None):
        if "slice(s) are empty" in w:
            seen.setdefault(w.replace("slice(s) are empty", "slice(s) are empty in every frame"), list(range(len(vols))))
    out = [w if len(f) == len(vols) else f"frame {', '.join(map(str, f))}: {w}" for w, f in seen.items()]
    soft = ((sheet_alpha > 0) & (sheet_alpha < 255)).mean()
    if soft > 0:
        out.append(f"{soft:.1%} of pixels are half-transparent; slices need alpha 0 or 255 (treated as >=128 solid)")
    return out


def thin_runs(occ, min_run=3):
    """Slice ranges (first, last) holding a part with no 2x2 block (a 1-px post, rope, antenna or
    rail) for at least min_run slices in a row. Turned slices are sampled once per screen pixel,
    so such a part falls between samples at some angles and blinks in and out as the stack turns."""
    flags = []
    for s in occ:
        b = s[:-1, :-1] & s[1:, :-1] & s[:-1, 1:] & s[1:, 1:]
        block = np.zeros_like(s)
        for dy in (0, 1):
            for dx in (0, 1):
                block[dy:dy + b.shape[0], dx:dx + b.shape[1]] |= b
        if not (s & ~block).any():
            flags.append(False)
            continue
        big = s.size
        lab = np.where(s, np.arange(big).reshape(s.shape), big)
        while True:                                   # 4-connected parts by min-label propagation
            new = lab.copy()
            new[1:] = np.minimum(new[1:], lab[:-1]); new[:-1] = np.minimum(new[:-1], lab[1:])
            new[:, 1:] = np.minimum(new[:, 1:], lab[:, :-1]); new[:, :-1] = np.minimum(new[:, :-1], lab[:, 1:])
            new = np.where(s, new, big)
            if (new == lab).all():
                break
            lab = new
        flags.append(bool(np.setdiff1d(np.unique(lab[s]), np.unique(lab[s & block])).size))
    runs, start = [], None
    for z, t in enumerate(flags + [False]):
        if t and start is None:
            start = z
        elif not t and start is not None:
            if z - start >= min_run:
                runs.append((start, z - 1))
            start = None
    return runs


def warnings_for(vol, sheet_alpha):
    H, D, W = vol.shape[:3]
    occ = vol[..., 3] > 0
    w = []
    filled = np.flatnonzero(occ.any((1, 2)))
    if not len(filled):
        return ["the sheet is empty"]
    if filled[0] > 0:
        w.append(f"the bottom {filled[0]} slice(s) are empty, so the object floats; drop them")
    if filled[-1] < H - 1:
        w.append(f"the top {H - 1 - filled[-1]} slice(s) are empty; drop them")
    soft = ((sheet_alpha > 0) & (sheet_alpha < 255)).mean() if sheet_alpha is not None else 0
    if soft > 0:
        w.append(f"{soft:.1%} of pixels are half-transparent; slices need alpha 0 or 255 (treated as >=128 solid)")
    # parts that do not touch the main body (6-neighbour connectivity)
    lab = np.where(occ, np.arange(occ.size).reshape(occ.shape), occ.size)
    for _ in range(4 * (H + D + W)):
        new = lab.copy()
        for ax in range(3):
            for s in (1, -1):
                r = np.roll(lab, s, ax)
                idx = [slice(None)] * 3
                idx[ax] = 0 if s > 0 else -1
                r[tuple(idx)] = occ.size
                new = np.minimum(new, r)
        new = np.where(occ, new, occ.size)
        if (new == lab).all():
            break
        lab = new
    ids, cnt = np.unique(lab[occ], return_counts=True)
    if len(ids) > 1:
        w.append(f"{len(ids) - 1} part(s) ({int(cnt.sum() - cnt.max())} voxels) don't touch the main body; "
                 "fine if intended (separate pieces), otherwise stray voxels")
    for z0, z1 in thin_runs(occ):
        w.append(f"slices {z0}-{z1} hold a 1-px-thin part (post, rope, antenna): fine in the GLB/OBJ, "
                 "but it blinks in and out as a sprite stack turns; make it 2 px thick for stacks")
    ncol = len(np.unique(vol[occ][:, :3], axis=0))
    if ncol > 160:
        w.append(f"{ncol} colours: soft gradients and noise smear when turned; use a small palette "
                 "(and banded shading) instead")
    if H > 3 * max(D, W):
        w.append(f"{H} layers on a {W}x{D} footprint: very tall; check the height scale")
    if H == 1:
        w.append("only one slice: nothing to stack")
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("sheet")
    ap.add_argument("--count", type=int, help="number of slices in the row (sheets from voxlib.save_sheet "
                                              "store it, so it can be left out)")
    ap.add_argument("--slice-width", type=int, help="width of one slice (instead of --count)")
    ap.add_argument("--frames", type=int, help="animation frames: rows in the sheet, first on top "
                                               "(default: stored in the sheet, else 1)")
    ap.add_argument("--fps", type=float, default=8, help="animation speed in the gif and viewer (8)")
    ap.add_argument("-o", "--out", help="output folder (default: the sheet's folder)")
    ap.add_argument("--name", help="output name (default: sheet name without _slices)")
    ap.add_argument("--squash", type=float, default=0.75, help="vertical scale: 1 = straight down (0.75)")
    ap.add_argument("--spacing", type=float, default=1.0, help="screen px between slices (1)")
    ap.add_argument("--outline", default="auto",
                    help="auto | none | #rrggbb: 1-px outline round the finished stack "
                         "(auto uses the sheet's stored outline if any)")
    ap.add_argument("--no-shadow", action="store_true", help="no drop shadow in preview/gif/viewer")
    ap.add_argument("--bg", default="#e9e5dd", help="background of preview/gif/viewer")
    ap.add_argument("--dirs", type=int, default=0, help="write an N-direction sheet (8, 16, 32 ...)")
    ap.add_argument("--gif", action="store_true", help="write a 48-frame turntable GIF")
    ap.add_argument("--viewer", action="store_true", help="write a drag-to-turn HTML viewer")
    ap.add_argument("--vox", action="store_true", help="write a MagicaVoxel .vox")
    ap.add_argument("--no-obj", action="store_true", help="skip the .obj/.mtl/_palette.png next to the .glb")
    ap.add_argument("--height", type=float, help="mesh height in metres, e.g. 1.6 for a person "
                                                 "(default: 16 art pixels per metre)")
    ap.add_argument("--ppm", type=float, default=16, help="art pixels per metre in the mesh (16); "
                                                          "keep one value across a set of props")
    ap.add_argument("--all", action="store_true", help="--dirs 16 --gif --viewer --vox")
    ap.add_argument("--scale", type=int, default=0, help="preview/gif pixel scale (auto: preview about 1600 px wide)")
    a = ap.parse_args()

    if not os.path.isfile(a.sheet):
        fail(f"no such file: {a.sheet}")
    im = Image.open(a.sheet)
    meta = {k: int(im.info[k]) for k in ("slices", "frames") if str(im.info.get(k, "")).isdigit()}
    stored_outline = str(im.info.get("outline", "")).strip()
    if stored_outline and not (stored_outline.startswith("#") and len(stored_outline) == 7):
        stored_outline = ""
    sheet = np.array(im.convert("RGBA"))
    sh_, sw = sheet.shape[:2]
    if (a.height is not None and a.height <= 0) or a.ppm <= 0:
        fail("--height and --ppm must be positive")
    if a.count and meta.get("slices") and a.count != meta["slices"]:
        fail(f"--count {a.count} disagrees with the sheet, which says it holds {meta['slices']} slices "
             "(stored by save_sheet); drop --count or fix it")
    if a.frames and meta.get("frames") and a.frames != meta["frames"]:
        fail(f"--frames {a.frames} disagrees with the sheet, which says it holds {meta['frames']} frames "
             "(stored by save_sheet); drop --frames or fix it")
    a.count = a.count or (None if a.slice_width else meta.get("slices"))
    a.frames = a.frames or meta.get("frames") or 1
    if a.count:
        if sw % a.count:
            fail(f"sheet is {sw} px wide, not divisible by --count {a.count}")
        W = sw // a.count
    elif a.slice_width:
        if sw % a.slice_width:
            fail(f"sheet is {sw} px wide, not divisible by --slice-width {a.slice_width}")
        W = a.slice_width
    else:
        fail(f"--count N (slices in the row) or --slice-width W is required; the sheet is {sw}x{sh_} px")
    F = max(1, a.frames)
    if sh_ % F:
        fail(f"sheet is {sh_} px tall, not divisible by --frames {F}")
    H, D = sw // W, sh_ // F
    alpha = sheet[..., 3].copy()
    sheet[..., 3] = np.where(alpha >= 128, 255, 0)
    sheet[sheet[..., 3] == 0] = 0
    vols = [np.stack([sheet[f * D:(f + 1) * D, z * W:(z + 1) * W] for z in range(H)]) for f in range(F)]
    vol = vols[0]
    if a.all:
        a.dirs, a.gif, a.viewer, a.vox = a.dirs or 16, True, True, True
    if a.outline == "auto":
        outline_str = stored_outline or "none"
    elif a.outline in ("none", "", None):
        outline_str = "none"
    else:
        outline_str = a.outline if a.outline.startswith("#") else "#" + a.outline
    outline = None if outline_str == "none" else hexrgb(outline_str)
    bg = hexrgb(a.bg)
    shadow = not a.no_shadow

    name = a.name or os.path.splitext(os.path.basename(a.sheet))[0].removesuffix("_slices")
    out = a.out or os.path.dirname(os.path.abspath(a.sheet))
    os.makedirs(out, exist_ok=True)
    f = lambda s: os.path.join(out, name + s)
    files = {}

    # preview: turns on top (2 rows of 4; with frames, one row of 8 per frame), flat views below
    shown = min(F, 12)
    turns = [[on_bg(render(vols[fi], d, a.squash, a.spacing, outline, shadow), bg) for d in range(0, 360, 45)]
             for fi in range(shown)]
    ch, cw = turns[0][0].shape[:2]
    per, nrow = (4, 2) if F == 1 else (8, shown)
    flats = [on_bg(e, bg) for e in elevations(vol)]
    gap = 3
    fw = sum(e.shape[1] + gap for e in flats)
    width = max(per * cw, fw)
    fk = max(1, min(3, width // fw))                     # flat views as big as the row allows
    flats = [upscale(e, fk) for e in flats]
    fh = max(e.shape[0] for e in flats)
    canvas = np.zeros((nrow * ch + gap + fh + 2, width, 3), np.uint8) + np.array(bg, np.uint8)
    for fi, cells in enumerate(turns):
        for i, c in enumerate(cells):
            y, x = (fi + i // per) * ch, (i % per) * cw
            canvas[y:y + ch, x:x + cw] = c
    canvas[nrow * ch + 1] = (np.array(bg) * 0.8).astype(np.uint8)
    x = 0
    for e in flats:
        canvas[nrow * ch + gap:nrow * ch + gap + e.shape[0], x:x + e.shape[1]] = e
        x += e.shape[1] + gap * fk
    k = a.scale or max(1, min(10, round(1600 / width)))          # about 1600 px wide
    Image.fromarray(upscale(canvas, k)).save(f("_preview.png"))
    files["preview"] = os.path.abspath(f("_preview.png"))

    rep = {"sheet": os.path.abspath(a.sheet), "slices": H, "slice_size": [W, D], "size_WxDxH": [W, D, H],
           "voxels": int((vol[..., 3] > 0).sum()),
           "render": {"squash": a.squash, "spacing": a.spacing, "outline": outline_str},
           "preview_layout": ("rows 1-2: turned 0,45,...,315 deg clockwise (0 = front toward the camera); "
                              f"row 3: flat front, side (front to the left), back, top, drawn {fk}x" if F == 1 else
                              f"one row per frame (first {shown} of {F}): turned 0,45,...,315 deg clockwise "
                              "(0 = front toward the camera); last row: flat front, side (front to the left), "
                              f"back, top of frame 0, drawn {fk}x")}
    if F > 1:
        rep["frames"] = F

    if F == 1 and rep["voxels"]:
        from glb import write_glb, write_obj
        from voxlib import trim
        mesh_h, mesh_d, mesh_w = trim(vol).shape[:3]
        ppm = mesh_h / a.height if a.height else a.ppm
        write_glb(f(".glb"), vol, ppm)
        files["glb"] = os.path.abspath(f(".glb"))
        if not a.no_obj:
            files["obj"] = [os.path.abspath(p) for p in write_obj(f(".obj"), vol, ppm)]
        rep["mesh_size_m"] = [round(v / ppm, 3) for v in (mesh_w, mesh_d, mesh_h)]
        rep["pixels_per_metre"] = round(ppm, 3)

    if a.dirs:
        # cells[i]: facing i; one cell per animation frame
        cells = [[render(v, i * 360 / a.dirs - 90, a.squash, a.spacing, outline) for v in vols]
                 for i in range(a.dirs)]                # facing: clockwise from +x (right) on screen
        fh_, fw_ = cells[0][0].shape[:2]
        if F == 1:
            per = min(a.dirs, 8)
            rows = math.ceil(a.dirs / per)
            spot = lambda i, k: ((i // per), (i % per))
        else:
            per, rows = F, a.dirs
            spot = lambda i, k: (i, k)
        grid = np.zeros((rows * fh_, per * fw_, 4), np.uint8)
        for i in range(a.dirs):
            for k, fr in enumerate(cells[i]):
                r, c = spot(i, k)
                grid[r * fh_:(r + 1) * fh_, c * fw_:(c + 1) * fw_] = fr
        Image.fromarray(grid).save(f(f"_dirs{a.dirs}.png"))
        files["dirs"] = os.path.abspath(f(f"_dirs{a.dirs}.png"))
        rep["dirs"] = {"count": a.dirs, "frame_size": [fw_, fh_], "per_row": per,
                       "facing": "facing i points i*360/N deg clockwise from right; "
                                 "i = round(atan2(vy, vx) / (2*pi) * N) mod N (screen y down)",
                       "layout": "cell i (8 per row) is facing i" if F == 1 else
                                 "row i is facing i; column k is animation frame k"}
    if a.gif:
        kg = a.scale or max(1, min(8, 420 // max(cw, ch)))
        n = 48 if F == 1 else 96                      # slower turn while an animation plays
        frames = [Image.fromarray(upscale(on_bg(render(vols[int(i * 0.06 * a.fps) % F], i * 360 / n,
                                                       a.squash, a.spacing, outline, shadow), bg), kg))
                  .quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for i in range(n)]
        frames[0].save(f("_turntable.gif"), save_all=True, append_images=frames[1:], duration=60, loop=0, disposal=2)
        files["gif"] = os.path.abspath(f("_turntable.gif"))
    if a.viewer:
        tpl = os.path.join(HERE, "..", "assets", "viewer.html")
        if not os.path.isfile(tpl):
            fail(f"viewer template missing: {tpl}")
        buf = io.BytesIO()
        Image.fromarray(np.concatenate([np.concatenate(list(v), axis=1) for v in vols], axis=0)).save(buf, "PNG")
        cfg = {"name": name, "count": H, "frames": F, "fps": a.fps, "squash": a.squash, "spacing": a.spacing, "bg": a.bg,
               "outline": outline_str if outline else None, "shadow": shadow,
               "src": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}
        html = open(tpl, encoding="utf-8").read().replace("/*CONFIG*/null", json.dumps(cfg), 1)
        with open(f("_viewer.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        files["viewer"] = os.path.abspath(f("_viewer.html"))
    if a.vox:
        names = [f(".vox")] if F == 1 else [f(f"_f{k}.vox") for k in range(F)]
        if all(write_vox(p, v) for p, v in zip(names, vols)):
            files["vox"] = os.path.abspath(names[0]) if F == 1 else [os.path.abspath(p) for p in names]
        else:
            rep.setdefault("notes", []).append(".vox skipped: MagicaVoxel models are at most 256 per side")

    rep["files"] = files
    rep["warnings"] = all_warnings(vols, alpha)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
