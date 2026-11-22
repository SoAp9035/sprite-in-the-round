"""Small building blocks for sprite-stack volumes. Import it from your own build script:

    import sys; sys.path.insert(0, "scripts")      # path to this folder
    from voxlib import *

A volume is a numpy array vol[z, y, x, 4] (uint8 RGBA, alpha 0 or 255):
  z = 0 is the ground layer, +y is the object's FRONT (down in a top-down slice),
  x runs left to right as you look at the front.
A view is an RGBA picture as drawn (row 0 = top of the picture).

Each function is short on purpose: read it, copy it, change it. Needs numpy and Pillow.
"""
import numpy as np
from PIL import Image, PngImagePlugin

__all__ = ["load", "save", "save_sheet", "load_sheet", "hexrgb", "rgbhex", "crop", "fit", "strip_outline",
           "strip_edge", "shared_palette", "near", "edge_distance", "show", "blank", "coords", "paint", "place",
           "trim", "carve", "stack_views", "part_rows", "sculpt", "facing", "decal", "lathe", "inflate", "extrude",
           "dome", "heightmap", "shade", "exposed_top"]


# ------------------------------------------------------------------ files
def load(path):
    """RGBA array with hard alpha (>=128 -> 255, else 0, and transparent pixels zeroed)."""
    a = np.array(Image.open(path).convert("RGBA"))
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    a[a[..., 3] == 0] = 0
    return a


def save(img, path, text=None):
    info = None
    if text:
        info = PngImagePlugin.PngInfo()
        for k, v in text.items():
            info.add_text(k, str(v))
    Image.fromarray(np.ascontiguousarray(img, np.uint8)).save(path, pnginfo=info)


def save_sheet(vol, path, outline=None):
    """The slice sheet: one row of slices, ground slice on the left (what engines and stack.py read).
    A list of equal-sized volumes (animation frames) gives one row per frame, first frame on top.
    The slice count, frame count, and optional outline colour are stored in the PNG, so stack.py
    reads them automatically."""
    vols = list(vol) if isinstance(vol, (list, tuple)) else [vol]
    sheet = np.concatenate([np.concatenate(list(v), axis=1) for v in vols], axis=0)
    meta = {"slices": vols[0].shape[0], "frames": len(vols)}
    if outline is not None:
        meta["outline"] = outline if isinstance(outline, str) else rgbhex(outline)
    save(sheet, path, meta)


def load_sheet(path, count=None, frames=None):
    """Volume from a slice sheet; with frames > 1, a list of volumes, one per row. count and
    frames default to what save_sheet stored in the PNG."""
    with Image.open(path) as im:
        stored = {k: int(v) for k, v in im.info.items() if k in ("slices", "frames") and str(v).isdigit()}
    count = count or stored.get("slices")
    frames = frames or stored.get("frames", 1)
    if not count:
        raise ValueError(f"{path} doesn't store its slice count: pass count")
    s = load(path)
    w, h = s.shape[1] // count, s.shape[0] // frames
    vols = [np.stack([s[f * h:(f + 1) * h, i * w:(i + 1) * w] for i in range(count)]) for f in range(frames)]
    return vols if frames > 1 else vols[0]


def hexrgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def rgbhex(rgb):
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb[:3])


# ------------------------------------------------------------------ 2D
def crop(img):
    """Tight crop to the opaque pixels."""
    ys, xs = np.nonzero(img[..., 3])
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else img


def fit(img, w, h):
    """Nearest-neighbour resize: keeps hard pixels."""
    if img.shape[1] == w and img.shape[0] == h:
        return img
    return np.array(Image.fromarray(img).resize((w, h), Image.NEAREST))


def _shift(a, axis, s):
    """out[i] = a[i + s] along axis; zero/False outside."""
    if s == 0:
        return a.copy()
    out = np.zeros_like(a)
    src, dst = [slice(None)] * a.ndim, [slice(None)] * a.ndim
    if s > 0:
        src[axis], dst[axis] = slice(s, None), slice(None, -s)
    else:
        src[axis], dst[axis] = slice(None, s), slice(-s, None)
    out[tuple(dst)] = a[tuple(src)]
    return out


def _near_any(px, colours, tol):
    """True where an (..., >=3) pixel array is within tol of any of the colours."""
    hit = np.zeros(px.shape[:-1], bool)
    for c in colours:
        rgb = np.array(hexrgb(c) if isinstance(c, str) else tuple(c)[:3])
        hit |= np.abs(px[..., :3].astype(int) - rgb).max(-1) <= tol
    return hit


def strip_outline(img, dark=70, colour=None, tol=24):
    """Recolour the 1-px outline around a drawing with the colour just inside it, so it doesn't
    become streaks inside the stack. Returns (img, outline_rgb or None).
    By default the outline is the dark pixels on the silhouette. A light or coloured outline
    (glass, selective outlining) isn't dark: pass its colour, e.g. colour="#a2c3df".
    Redraw the outline once around the finished render instead (stack.py --outline)."""
    m = img[..., 3] > 0
    p = np.pad(m, 1)
    # 8 neighbours: in a concave corner (under a cap, beside a stem) the outline pixel touches the
    # outside only diagonally, and a 4-neighbour test would leave it as a dark speck in the stack
    edge = m & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
                 & p[:-2, :-2] & p[:-2, 2:] & p[2:, :-2] & p[2:, 2:])
    if colour is None:
        line = edge & (img[..., :3].astype(int).mean(-1) < dark)
    else:
        line = edge & _near_any(img, [colour], tol)
    if not line.any():
        return img, None
    colour = tuple(int(c) for c in np.median(img[line][:, :3], axis=0))
    out, todo = img.copy(), line.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        src = _shift(_shift(img, 0, dy), 1, dx)
        ok = todo & _shift(_shift(m & ~line, 0, dy), 1, dx)
        out[ok] = src[ok]
        todo &= ~ok
    return out, colour


def strip_edge(img, width=2, colours=None, tol=24):
    """Recolour the band at both ends of every row with the first colour inside it: rim light,
    glass edges, the background seen through glass at the sides, outline leftovers.
    In a front view those pixels are seen edge-on. Lathe or inflate the view and they run round
    the sides as a wide stripe (see references/build-volume.md). Without `colours` the outer
    `width` px of each run go; with `colours` (list of '#rrggbb') only those colours go, up to
    `width` px deep. Strip only some rows by slicing: v[20:] = strip_edge(v[20:], 3)[0].
    Returns (img, rim_rgb): the colour removed most often, e.g. to pass as --outline."""
    out, a = img.copy(), img[..., 3] > 0
    removed = []
    for y in range(img.shape[0]):
        on = np.flatnonzero(a[y])
        for run in np.split(on, np.flatnonzero(np.diff(on) > 1) + 1) if len(on) else []:
            for seg in (run, run[::-1]):                       # left end, then right end
                k = min(width, (len(run) - 1) // 2)
                if colours is not None:
                    hit = _near_any(img[y, seg[:k]], colours, tol)
                    k = int(np.argmin(hit)) if not hit.all() else k
                if k:
                    removed.append(img[y, seg[:k], :3])
                    out[y, seg[:k]] = img[y, seg[k]]
    if not removed:
        return out, None
    vals, cnt = np.unique(np.concatenate(removed), axis=0, return_counts=True)
    return out, tuple(int(v) for v in vals[cnt.argmax()])


def shared_palette(imgs, n=24):
    """Map several pictures onto one shared palette of n colours, no dithering."""
    px = np.concatenate([v[v[..., 3] > 0][:, :3] for v in imgs])
    px = np.unique(px // 6 * 6 + 3, axis=0).astype(np.uint8)
    if len(px) <= n:
        return [v.copy() for v in imgs]
    q = Image.fromarray(px.reshape(1, -1, 3), "RGB").quantize(n, method=Image.Quantize.MEDIANCUT,
                                                               dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[:n * 3]).reshape(-1, 3)
    out = []
    for v in imgs:
        o = v.copy()
        o[..., :3] = pal[((v[..., None, :3].astype(int) - pal[None, None]) ** 2).sum(-1).argmin(-1)]
        o[o[..., 3] == 0] = 0
        out.append(o)
    return out


def near(img, colours, tol=24):
    """Mask of the opaque pixels (or voxels) within tol of any colour ('#rrggbb' or rgb), e.g.
    img[near(img, ["#929292"])] = 0 removes a drawn shadow, paint(vol, near(vol, ["#ffffff"]), "#cccccc")."""
    return (img[..., 3] > 0) & _near_any(img, colours, tol)


def edge_distance(mask):
    """Distance from each True pixel to the nearest False one (about 1 at the edge)."""
    pm = np.pad(mask, 1)
    near = np.zeros_like(pm)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near |= _shift(_shift(pm, 0, dy), 1, dx)
    ty, tx = np.nonzero(~pm & near)
    oy, ox = np.nonzero(pm)
    d = np.zeros(pm.shape, np.float32)
    for i in range(0, len(oy), 2048):
        a, b = oy[i:i + 2048, None], ox[i:i + 2048, None]
        d[oy[i:i + 2048], ox[i:i + 2048]] = np.sqrt(((a - ty) ** 2 + (b - tx) ** 2).min(1))
    return d[1:-1, 1:-1]


def show(img, chars=".abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%&*+=?"):
    """Text dump of a picture or one slice: '.' is empty, one letter per colour, legend first.
    Handy to read exact pixel positions before painting or cutting. Letters are given per call, so
    the same letter can mean different colours in two dumps: read the legend each time."""
    keys = {}
    rows = []
    for r in img:
        s = ""
        for p in r:
            if p[3] == 0:
                s += "."
                continue
            k = "#%02x%02x%02x" % tuple(p[:3])
            if k not in keys:
                keys[k] = chars[1 + len(keys) % (len(chars) - 1)]
            s += keys[k]
        rows.append(s)
    legend = " ".join(f"{v}={k}" for k, v in keys.items())
    if len(keys) > len(chars) - 1:
        legend = f"({len(keys)} colours: letters repeat, so reduce colours or show a crop) " + legend
    return legend + "\n" + "\n".join(rows)


# ------------------------------------------------------------------ volumes
def blank(H, D, W):
    """Empty volume: H layers, D deep (back to front), W wide."""
    return np.zeros((H, D, W, 4), np.uint8)


def coords(vol):
    """Z, Y, X index grids for writing shapes as boolean masks, e.g.
    Z, Y, X = coords(vol); paint(vol, (X - 8)**2 + (Y - 8)**2 <= 9, "#6b4226")"""
    return np.indices(vol.shape[:3])


def paint(vol, mask, colour):
    """Set the voxels in mask to a colour ('#rrggbb' or rgb tuple). Use colour=None to cut them out.
    Empty voxels in the mask become solid, which builds shapes; to only recolour, AND the mask
    with vol[..., 3] > 0."""
    if colour is None:
        vol[mask] = 0
    else:
        rgb = hexrgb(colour) if isinstance(colour, str) else tuple(colour)[:3]
        vol[mask] = (*rgb, 255)
    return vol


def place(dst, src, z=0, y=0, x=0):
    """Copy the solid voxels of src into dst with src[0, 0, 0] at (z, y, x); clipped to dst."""
    H, D, W = dst.shape[:3]
    z0, y0, x0 = max(z, 0), max(y, 0), max(x, 0)
    z1, y1, x1 = min(z + src.shape[0], H), min(y + src.shape[1], D), min(x + src.shape[2], W)
    if z1 <= z0 or y1 <= y0 or x1 <= x0:
        return dst
    s = src[z0 - z:z1 - z, y0 - y:y1 - y, x0 - x:x1 - x]
    d = dst[z0:z1, y0:y1, x0:x1]
    m = s[..., 3] > 0
    d[m] = s[m]
    return dst


def trim(vol):
    """Drop empty layers and empty margins (the stack turns around the centre of what is left).
    A list of equal-sized volumes (animation frames) is trimmed by one shared box, so the frames
    stay lined up; the ground layer stays wherever any frame touches it."""
    many = isinstance(vol, (list, tuple))
    occ = np.any([v[..., 3] > 0 for v in vol], axis=0) if many else vol[..., 3] > 0
    if not occ.any():
        return vol
    z, y, x = (np.flatnonzero(occ.any(axis=a)) for a in ((1, 2), (0, 2), (0, 1)))
    box = np.s_[z[0]:z[-1] + 1, y[0]:y[-1] + 1, x[0]:x[-1] + 1]
    return [v[box] for v in vol] if many else vol[box]


def _covered(occ):
    """True where something is higher up in the same column."""
    above = np.zeros_like(occ)
    above[:-1] = np.logical_or.accumulate(occ[::-1], axis=0)[::-1][1:]
    return above


def _grow(mask, r):
    """mask grown by r px inside each layer, corners included."""
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy or dx:
                out |= _shift(_shift(mask, 1, dy), 2, dx)
    return out


def exposed_top(vol):
    """True where nothing at all is above a voxel in its column (seen from straight above)."""
    occ = vol[..., 3] > 0
    return occ & ~_covered(occ)


def _fill_rows(v):
    """Every transparent pixel takes the colour of the nearest opaque pixel in its row."""
    out = v.copy()
    x = np.arange(v.shape[1])
    for r in range(v.shape[0]):
        on = np.flatnonzero(v[r, :, 3])
        if len(on):
            out[r] = v[r, on[np.abs(x[:, None] - on[None]).argmin(1)]]
    return out


def _stand(img, w, h):
    """img on a w x h canvas: standing on the bottom row, centred left to right."""
    out = np.zeros((h, w, 4), np.uint8)
    ih, iw = img.shape[:2]
    x0 = (w - iw) // 2
    out[h - ih:, x0:x0 + iw] = img
    return out


def _run_pos(occ, axis):
    """For every cell: offset from the middle of its run of True along axis, and half the run length."""
    o = np.moveaxis(occ, axis, -1)
    n = o.shape[-1]
    idx = np.arange(n)
    pad = np.zeros(o.shape[:-1] + (1,), bool)
    prev = np.concatenate([pad, o[..., :-1]], -1)
    nxt = np.concatenate([o[..., 1:], pad], -1)
    start = np.maximum.accumulate(np.where(o & ~prev, idx, -1), axis=-1)
    end = np.minimum.accumulate(np.where(o & ~nxt, idx, n)[..., ::-1], axis=-1)[..., ::-1]
    off = idx + 0.5 - (start + end + 1) / 2
    half = np.maximum((end - start + 1) / 2, 0.5)
    return np.moveaxis(off, -1, axis), np.moveaxis(half, -1, axis)


def carve(top=None, side=None, front=None, back=None, side2=None, wall=2, side_nose="left",
          top_nose="down", rounded=False, aligned=False):
    """Volume where all views agree (SpriteCook's four-view method).
    side: seen from the side, front pointing LEFT (side_nose="right" if it points right).
    side2: the other side as drawn, nose pointing the other way. Without it the far side shows
      `side` again, so decals read mirrored there.
    top: seen from above, front pointing DOWN (top_nose="up" if not). Optional.
    front / back: as seen from the front / from behind (the back is mirrored for you). Optional
      with a top view; without them the width at every height is the top view's width.
    Sizes: with a top view, views are cropped and scaled to it (height = side height * top length /
      side length). Without one, views keep their size and stand on one ground line, centred, so
      they must share one scale (sprite-sheet views do). aligned=True uses the views exactly as
      given, uncropped (cells cut from one sheet), so animation frames carved one by one line up.
    rounded: each layer's cross-section becomes the ellipse inside the box the views allow (bodies,
      heads, limbs) instead of a box; a number above 2 is boxier (superellipse power).
    Colours: top surfaces from the top view; the `wall` px of each layer next to open air, under
    something higher, from the view facing that way (same row). A 1-px step lip beside a higher
    layer (a nose, a windscreen, a cabin a pixel narrower at its roof) also takes the facing view,
    and hidden voxels continue the colour of the one above them.
    Without a top view, walls take the view facing their nearest open side and tops take the
    side view's colour at that spot, so check the tops (hair, backs, roofs) and repaint them."""
    if side is None:
        raise ValueError("carve needs a side view")
    if top is None and front is None and back is None:
        raise ValueError("carve needs a top view or a front/back view for the width")
    views = [top, side, front, back, side2]
    if not aligned:
        views = [crop(v) if v is not None else None for v in views]
    top, side, front, back, side2 = views
    if side_nose == "right":
        side = side[:, ::-1]
        side2 = side2[:, ::-1] if side2 is not None else None
    if top is not None and top_nose == "up":
        top = top[::-1, ::-1]
    if aligned:
        H, D = side.shape[:2]
        W = next(v.shape[1] for v in (front, back, top) if v is not None)
        want = {"side": (H, D), "side2": (H, D), "front": (H, W), "back": (H, W), "top": (D, W)}
        for k, v in zip(("top", "side", "front", "back", "side2"), (top, side, front, back, side2)):
            if v is not None and v.shape[:2] != want[k]:
                raise ValueError(f"aligned views must agree: {k} is {v.shape[1]}x{v.shape[0]}, "
                                 f"expected {want[k][1]}x{want[k][0]} (width x height)")
        put = lambda v, w: v
    elif top is not None:
        D, W = top.shape[:2]
        H = max(1, round(side.shape[0] * D / side.shape[1]))
        put = lambda v, w: fit(v, w, H)
    else:
        H = max(v.shape[0] for v in (side, front, back, side2) if v is not None)
        D = max(v.shape[1] for v in (side, side2) if v is not None)
        W = max(v.shape[1] for v in (front, back) if v is not None)
        put = lambda v, w: _stand(v, w, H)
    S = put(side, D)[::-1, ::-1]                                          # [z, y], front at +y
    S2 = put(side2, D)[::-1] if side2 is not None else None              # drawn nose right
    F = put(front, W)[::-1] if front is not None else None               # [z, x]
    B = put(back, W)[::-1, ::-1] if back is not None else None           # seen from behind: mirrored
    F, B = (F if F is not None else B), (B if B is not None else F)
    S2 = S2 if S2 is not None else S
    occ = np.broadcast_to(((S[..., 3] > 0) | (S2[..., 3] > 0))[:, :, None], (H, D, W)).copy()
    if F is not None:
        occ &= ((F[..., 3] > 0) | (B[..., 3] > 0))[:, None, :]
    if rounded:
        # Round the boxes the side and end views allow, before the top view cuts them: rounding a
        # shape that is already round (a disc base cut by a round top view) would erode it.
        p = 2.0 if rounded is True else float(rounded)
        ox, hx = _run_pos(occ, 2)
        oy, hy = _run_pos(occ, 1)
        occ &= (np.abs(ox) / hx) ** p + (np.abs(oy) / hy) ** p <= 1 + 1e-9
    if top is not None:
        occ &= (top[..., 3] > 0)[None]
    vol = np.zeros(occ.shape + (4,), np.uint8)
    if top is not None:
        vol[:] = top[None]
    reach = wall if top is not None else max(D, W)
    # distance to open air inside the layer, looking -x, +x, -y (back), +y (front)
    d = np.full((4,) + occ.shape, reach + 1, np.int16)
    for i, (ax, s) in enumerate(((2, -1), (2, 1), (1, -1), (1, 1))):
        for k in range(reach, 0, -1):
            d[i][~_shift(occ, ax, s * k)] = k
    face, near = d.argmin(0), d.min(0) <= reach
    covered = _covered(occ)
    walls = occ & near & covered
    Sf, S2f = _fill_rows(S), _fill_rows(S2)
    Sf = np.where((S[..., 3] > 0).any(1)[:, None, None], Sf, S2f)[:, :, None]
    S2f = np.where((S2[..., 3] > 0).any(1)[:, None, None], S2f, Sf[:, :, 0])[:, :, None]
    # Looking from +x, the object's front (+y) appears on the left of the drawing.
    left_wall, right_wall = (Sf, S2f) if side_nose == "right" else (S2f, Sf)
    if F is not None:
        Ff, Bf = _fill_rows(F), _fill_rows(B)
        Ff = np.where((F[..., 3] > 0).any(1)[:, None, None], Ff, Bf)
        Bf = np.where((B[..., 3] > 0).any(1)[:, None, None], Bf, Ff)
        srcs = (left_wall, right_wall, Bf[:, None], Ff[:, None])
    else:
        srcs = (left_wall, right_wall, Sf, Sf)
    for i, src in enumerate(srcs):
        m = walls & (face == i)
        vol[m] = np.broadcast_to(src, vol.shape)[m]
    if top is not None:
        # Step lips: a 1-px edge of a layer, open to the air and next to a higher layer (corners
        # too), belongs to a steep surface (a nose, a windscreen, a cabin a pixel narrower at the
        # roof), not to a top. Give it the facing view's colour: the top view put its colours on
        # every lip of a slope, a second row of headlights above the front view's, and rings of
        # body colour round a cabin. Only from a view drawn facing that way: without a front view
        # the top view knows better where the headlights sit across the nose.
        lip = occ & ~covered & (d.min(0) <= 1) & _grow(covered, 1)
        lip[-1] = False
        drawn = (True, True, back is not None, front is not None)
        for i, src in enumerate(srcs):
            m = lip & (face == i) & drawn[i]
            vol[m] = np.broadcast_to(src, vol.shape)[m]
        # Hidden voxels under a higher one continue its colour. A turned stack shows a pixel or
        # two of each layer behind the one above, and the top view's colour there striped walls.
        inner = occ & covered & ~walls & ~lip
        for z in range(occ.shape[0] - 2, -1, -1):
            m = inner[z] & occ[z + 1]
            vol[z][m] = vol[z + 1][m]
    if top is None:                    # tops: the nearer side view's colour (its top edge at that spot)
        up = occ & ~covered
        lr = np.arange(W)[None, None, :] < W / 2
        for src, m in ((left_wall, up & lr), (right_wall, up & ~lr)):
            vol[m] = np.broadcast_to(src, vol.shape)[m]
    vol[..., 3] = np.where(occ, 255, 0)
    vol[~occ] = 0
    return vol


def stack_views(top=None, side=None, front=None, back=None, side2=None, *, strip=True, dark=70,
                outline_colour=None, colors=32, shade_amount=0.2, cool=0.25, wall=2,
                side_nose="left", top_nose="down", rounded=False, aligned=False):
    """Batteries-included 2-to-5-view object pipeline: strip 1-px view outlines, harmonize views
    onto one shared palette, carve the volume, and shade walls in cool-shifted bands.
    Returns (vol, outline_hex_or_None). Pass `outline` to save_sheet(trim(vol), path, outline=outline)
    so stack.py restores the 1-px silhouette outline automatically in 2D previews and viewers.
    colors=0 keeps every original colour; shade_amount=0 skips wall shading."""
    items = [("top", top), ("side", side), ("front", front), ("back", back), ("side2", side2)]
    present = [(k, v) for k, v in items if v is not None]
    outlines = []
    if strip:
        stripped = []
        for k, v in present:
            sv, ol = strip_outline(v, dark=dark, colour=outline_colour)
            stripped.append((k, sv))
            if ol is not None:
                outlines.append(ol)
        present = stripped
    outline_hex = rgbhex(np.median(outlines, axis=0)) if outlines else None
    if colors and colors > 0 and len(present) > 1:
        quant = shared_palette([v for _, v in present], n=colors)
        present = [(k, q) for (k, _), q in zip(present, quant)]
    kwargs = dict(present)
    vol = carve(**kwargs, wall=wall, side_nose=side_nose, top_nose=top_nose,
                rounded=rounded, aligned=aligned)
    if shade_amount and shade_amount > 0:
        vol = shade(vol, amount=shade_amount, cool=cool)
    return vol, outline_hex


# ------------------------------------------------------------------ sculpt by parts (characters)
def _stand_view(v, w, h, name):
    """A view or mask standing on the ground of a w x h canvas, centred left to right."""
    v = np.asarray(v)
    if v.shape[0] > h or v.shape[1] > w:
        raise ValueError(f"the {name} view is {v.shape[1]}x{v.shape[0]}, larger than the volume's "
                         f"{w}x{h}: make the volume from the views' sizes")
    if v.ndim == 2:
        out = np.zeros((h, w), bool)
        x0 = (w - v.shape[1]) // 2
        out[h - v.shape[0]:, x0:x0 + v.shape[1]] = v
        return out
    return _stand(v, w, h)


def part_rows(vol, front, side, z=None, x=None, y=None):
    """A part's size layer by layer, read from a front and a side view: [(z, x0, x1, y0, y1), ...],
    inclusive spans in volume coordinates, for each layer both views cover. Feed it to sculpt.
    front, side: the drawings (RGBA) or boolean masks of the part's pixels in them, the side drawn
      nose LEFT. Like carve's views they stand on the ground (bottom row = layer 0), centred, so
      make vol = blank(tallest view's height, side width, front width).
    z=(lo, hi), x=(lo, hi), y=(lo, hi): keep only that range, inclusive (the head z=(23, 37), the
      left leg x=(0, 9)). Only the two ends of each row count, so a face inside the hair is fine,
      but print the list and fix layers where something else covers the part's edge."""
    H, D, W = vol.shape[:3]
    to_mask = lambda v: np.asarray(v)[..., 3] > 0 if np.asarray(v).ndim == 3 else np.asarray(v, bool)
    F = _stand_view(to_mask(front), W, H, "front")[::-1].copy()         # [z, x]
    S = _stand_view(to_mask(side), D, H, "side")[::-1, ::-1].copy()     # [z, y], front at +y
    for m, r in ((F, x), (S, y)):
        if r is not None:
            m[:, :max(r[0], 0)] = False
            m[:, r[1] + 1:] = False
    rows = []
    for k in range(H):
        if z is not None and not z[0] <= k <= z[1]:
            continue
        fx, sy = np.flatnonzero(F[k]), np.flatnonzero(S[k])
        if len(fx) and len(sy):
            rows.append((k, int(fx[0]), int(fx[-1]), int(sy[0]), int(sy[-1])))
    return rows


def sculpt(vol, rows, power=2.5):
    """Mask of a rounded part: rows is [(z, x0, x1, y0, y1), ...] from part_rows, or written by hand
    from show() dumps (inclusive spans, volume coordinates). Each layer becomes the superellipse
    inside its box: 2 is an ellipse, higher is boxier; 2.5 suits chunky pixel characters. List a
    layer twice for two parts side by side (legs). Then paint it: paint(vol, shirt, "#c6e3c3")."""
    H, D, W = vol.shape[:3]
    yy, xx = np.arange(D)[:, None], np.arange(W)[None, :]
    m = np.zeros((H, D, W), bool)
    for z, x0, x1, y0, y1 in rows:
        if 0 <= z < H:
            ex = np.abs(xx - (x0 + x1) / 2) / ((x1 - x0 + 1) / 2)
            ey = np.abs(yy - (y0 + y1) / 2) / ((y1 - y0 + 1) / 2)
            m[z] |= ex ** power + ey ** power <= 1 + 1e-9
    return m


_SIDES = {"front": (1, 1), "back": (1, -1), "right": (2, 1), "left": (2, -1), "top": (0, 1), "bottom": (0, -1)}


def facing(mask, side="front", depth=1):
    """The voxels of mask seen from one side: fewer than `depth` voxels of mask lie beyond them that
    way. side: front (+y), back, left / right as you look at the front (-x / +x), top, bottom.
    mask is a part (from sculpt) or a whole volume (vol[..., 3] > 0). Buttons go on
    facing(shirt, "front"), a print on facing(shirt, "back")."""
    axis, sign = _SIDES[side]
    m = mask.astype(np.int32)
    if sign > 0:
        beyond = np.flip(np.cumsum(np.flip(m, axis), axis), axis) - m
    else:
        beyond = np.cumsum(m, axis) - m
    return mask & (beyond < depth)


def decal(vol, view, where, side="front", colours=None, tol=24, depth=1, flat=None):
    """Copy a view's pixels onto the voxels of `where` that face that view, and nowhere else: the
    face, eyes, buttons, a logo, a print on the back. Unlike carve, nothing runs round the sides.
    view: front and back as drawn; top with the nose down. For side decals the input convention
      is nose LEFT on the left wall (-x), nose RIGHT on the right wall (+x). Flip an as-drawn
      orthographic profile horizontally before applying it to its visible wall.
    colours: only where the view is near these colours (the skin, the eyes, a logo), else
      wherever it is opaque.
    flat: paint this one colour there instead of copying the view's pixels: soft or noisy art
      gives a clean face, clean eyes. Returns the mask it painted.
    depth=2 keeps a decal on a strongly curved part from showing gaps when turned."""
    H, D, W = vol.shape[:3]
    if side in ("front", "back"):
        img = _stand_view(view, W, H, side)[::-1]                        # [z, x]
        img = (img[:, ::-1] if side == "back" else img)[:, None]
    elif side in ("left", "right"):
        img = _stand_view(view, D, H, side)[::-1]                        # [z, y]
        img = (img[:, ::-1] if side == "left" else img)[:, :, None]
    elif side == "top":
        img = _stand_view(view, W, D, side)[None]                        # [y, x]
    else:
        raise ValueError("side is front, back, left, right or top")
    img = np.broadcast_to(img, vol.shape)
    sel = facing(where & (vol[..., 3] > 0), side, depth) & (img[..., 3] > 0)
    if colours is not None:
        sel &= _near_any(img, colours, tol)
    if flat is not None:
        paint(vol, sel, flat)
    else:
        vol[sel] = img[sel]
    return sel


def lathe(front, top=None, axis=None, wrap=180, sides=None):
    """Spin a front (or side) view round a vertical axis: pots, trees, bottles, towers, lamps.
    A layer is solid at every radius the view covers at that height, so a gap in the view becomes
    a ring-shaped gap. Walls within `wrap` degrees of the front show the view's column in front of
    them; walls further round take the colour of the view's edge at that height. wrap=180 puts
    the picture all round (leaves, bark, barrel staves); wrap=60 keeps front-only details (labels,
    faces, doors, highlights) on the front.
    Each view column colours a whole chord of the disc, and the chord at the edge is about
    sqrt(radius) deep, so the art's outer columns turn into a wide stripe at 90 degrees. Strip
    edge bands first (strip_edge), and for a pattern all round pass `sides`: a picture (a side
    view, front to the left, or the view itself) for the walls within 30 degrees of each side.
    Top surfaces take `top`: a top view fitted to the footprint, a colour ('#rrggbb'), or by
    default the view's colour at that radius in the top row (often a highlight: check it).
    axis: column of the axis in the cropped view."""
    F = crop(front)
    if axis is not None:
        r = max(axis, F.shape[1] - 1 - axis)
        F = np.pad(F, ((0, 0), (round(r - axis), round(r - (F.shape[1] - 1 - axis))), (0, 0)))
    F = F[::-1]
    H, W = F.shape[:2]
    a = F[..., 3] > 0
    c = np.arange(W) - (W - 1) / 2
    off = 0.5 if W % 2 == 0 else 0.0
    cb = np.round(np.abs(c) - off).astype(int)                     # radius index of each column
    rb = np.round(np.hypot(c[:, None], c[None, :]) - off).astype(int)   # ... of each cell [y, x]
    nb = cb.max() + 1
    rb = np.minimum(rb, nb)                                         # index nb = outside
    ang = np.degrees(np.arctan2(np.abs(c)[None, :], c[:, None]))   # [y, x]: 0 = front, 90 = side
    facing = ang <= wrap
    vol = np.zeros((H, W, W, 4), np.uint8)
    ring = np.zeros((H, W, W, 4), np.uint8)
    for z in range(H):
        prof, pc = np.zeros(nb + 1, bool), np.zeros((nb + 1, 4), np.uint8)
        for x in np.flatnonzero(a[z]):
            prof[cb[x]], pc[cb[x]] = True, F[z, x]
        ring[z] = pc[rb]
        col = np.where((a[z][None, :] & facing)[..., None], F[z][None], ring[z])
        vol[z] = np.where(prof[rb][..., None], col, 0)
    if sides is not None:
        S = _fill_rows(fit(crop(sides), W, H)[::-1, ::-1])             # [z, y], front at +y
        lr = (np.abs(ang - 90) < 30)[None] & (vol[..., 3] > 0) & (S[..., 3] > 0)[:, :, None]
        vol[lr] = np.broadcast_to(S[:, :, None], vol.shape)[lr]
    up = exposed_top(vol)
    if isinstance(top, (str, tuple)):
        paint(vol, up, top)
    elif top is not None:
        T = fit(crop(top), W, W)
        T = np.where(T[..., 3:] > 0, T, ring.max(0))
        vol[up] = np.broadcast_to(T, vol.shape)[up]
    else:
        vol[up] = ring[up]
    vol[..., 3] = np.where(vol[..., 3] > 0, 255, 0)
    return vol


def inflate(front, depth=None):
    """Puff a front view up like a pillow: thick in the middle, thin at the edges and in thin
    parts. depth: thickest point in px (default: as thick as the widest part). The front picture
    goes straight through, so the back shows it mirrored: repaint the back half (y < depth/2)."""
    F = crop(front)[::-1]
    a = F[..., 3] > 0
    d = np.clip(edge_distance(a) - 0.5, 0, None)
    R = max(1.0, float(d.max()) if depth is None else depth / 2)
    half = np.floor(np.sqrt(np.clip(R * R - (R - np.minimum(d, R)) ** 2, 0, None)))
    K = int(np.ceil(R))
    yy = np.abs(np.arange(2 * K + 1) - K)
    occ = a[:, None, :] & (yy[None, :, None] <= half[:, None, :])
    return np.where(occ[..., None], F[:, None], 0).astype(np.uint8)


def extrude(front, depth):
    """A slab `depth` px thick: signs, coins, cards, doors, blades."""
    F = crop(front)[::-1]
    return np.repeat(F[:, None], int(depth), axis=1)


def dome(mask, peak):
    """Height per pixel that rises from the edge of mask to `peak` in the middle (for heightmap)."""
    d = np.clip(edge_distance(mask) - 0.5, 0, None)
    R = max(float(d.max()), 1.0)
    h = np.sqrt(np.clip(R * R - (R - np.minimum(d, R)) ** 2, 0, None)) / R * peak
    return np.where(mask, np.maximum(1, np.round(h)), 0).astype(int)


def heightmap(top, heights):
    """Raise a top-down picture into columns. heights: one number or an int array the shape of
    `top` (0 = nothing). Every column shows the top colour all the way down; run shade() after."""
    a = top[..., 3] > 0
    h = np.where(a, np.broadcast_to(np.asarray(heights), a.shape), 0).astype(int)
    occ = np.arange(max(int(h.max()), 1))[:, None, None] < h[None]
    return np.where(occ[..., None], top[None], 0).astype(np.uint8)


def shade(vol, amount=0.25, bands=3, cool=0.25):
    """Darken side walls, more near the ground, in a few flat steps so the palette stays small.
    Walls are what carve paints from the side views: voxels within 2 px of open air in their
    layer under something higher, and 1-px step lips next to a higher layer, so a slope shades
    as evenly as a wall. Tops keep their colour. amount 0.2-0.3 reads well; 0 = flat.
    cool > 0 shifts wall shadows slightly toward blue (pixel-art hue shifting) so whites and warm
    walls don't turn muddy grey; cool = 0 gives neutral RGB darkening."""
    occ = vol[..., 3] > 0
    H = vol.shape[0]
    edge = [occ & ~(_shift(occ, 1, k) & _shift(occ, 1, -k) & _shift(occ, 2, k) & _shift(occ, 2, -k))
            for k in (1, 2)]
    covered = _covered(occ)
    m = ((edge[0] | edge[1]) & covered) | (edge[0] & ~covered & _grow(covered, 1))
    low = 1 - np.arange(H) / max(H - 1, 1)                       # 1 at the ground, 0 at the top
    step = np.ceil(low * bands) / bands
    d = amount * (0.4 + step)
    shift = np.array([1.0 + 0.16 * cool, 1.0, 1.0 - 0.36 * cool], np.float32)
    f = (1.0 - d[:, None] * shift[None, :])[:, None, None, :]
    out = vol.copy()
    out[..., :3] = np.where(m[..., None], np.clip(vol[..., :3] * f, 0, 255), vol[..., :3]).astype(np.uint8)
    return out
