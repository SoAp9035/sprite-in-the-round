#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy>=1.22", "pillow>=9.1", "scipy>=1.7", "opencv-python-headless>=4.5"]
# ///
"""Recover native-resolution pixel art from an upscaled, screenshotted, compressed or AI-made image.

Finds how many image pixels one art pixel covers (integer or fractional, e.g. 6.84), samples the
middle of every cell, clears a flat or checkerboard background, and can split a sheet into its
separate drawings. An editor canvas inside a screenshot is found on its own, and small pieces
left at the canvas edge (frame lines, rulers) are dropped; if detection still struggles, crop to
the art (--crop) or give the known size (--size).

usage: pixel_grid.py IMAGE [-o OUT.png] [options]

examples:
  pixel_grid.py shot.png -o sprite.png                        # detect everything
  pixel_grid.py shot.png --crop 212,80,448,448 --size 64x64   # the canvas is known to be 64x64
  pixel_grid.py shot.png --pixel 7                            # one art pixel = 7 image pixels
  pixel_grid.py sheet.png -o views.png --split --ascii        # one PNG per drawing + text dump

Prints JSON on stdout and diagnostics on stderr. Read "notes" and "fit_error" (mean RGB error
when the sampled cells are enlarged again). "grid_candidates" gives both sizes when the input
could be native. Inspect fine details in OUT_check.png and the overlay named by "grid_check".
Exit codes: 0 ok, 2 bad arguments, 3 nothing left after background removal.
"""
import argparse, json, math, os, sys

import numpy as np
from PIL import Image

EPS = 1e-6


def note(*a):
    print(*a, file=sys.stderr)


def fail(msg, code=2):
    note("error: " + msg)
    sys.exit(code)


def _key(a):
    k = (a[..., 0].astype(np.uint32) << 16) | (a[..., 1].astype(np.uint32) << 8) | a[..., 2]
    return np.where(a[..., 3] < 128, np.uint32(1 << 24), k)


def _runs(a):
    """Lengths of same-colour runs along rows and columns (ignoring runs touching the border)."""
    out = []
    key = _key(a)
    for arr in (key, key.T):
        for row in arr:
            ch = np.flatnonzero(row[1:] != row[:-1]) + 1
            if len(ch) >= 2:
                out.append(np.diff(ch))
    return np.concatenate(out) if out else np.zeros(0, int)


def _profile(a, axis):
    """Summed colour change between neighbouring columns (axis=1) or rows (axis=0)."""
    f = a.astype(np.float32)
    f[..., :3] *= f[..., 3:4] / 255
    return np.abs(np.diff(f, axis=axis)).sum(-1).sum(1 - axis)


def _phase(G, p):
    """Offset of the grid with period p that puts the most edge energy on grid lines."""
    best, arg = -1.0, 0.0
    for phi in np.arange(0, p, 0.05 if p < 4 else 0.25):
        idx = np.floor(phi + np.arange(int(len(G) / p) + 2) * p + EPS).astype(int) - 1
        sc = G[idx[(idx >= 0) & (idx < len(G))]].sum()
        if sc > best:
            best, arg = sc, float(phi)
    return arg


def grid_exact(a):
    """Clean art scaled by a whole number: the gcd of all colour runs."""
    runs = _runs(a)
    if not len(runs):
        return 1.0, 0.0
    g = int(np.gcd.reduce(runs))
    return float(max(g, 1)), float((runs == 1).mean())


def grid_fractional(a):
    """Clean art scaled by a non-whole factor p: art pixels become runs of floor(p) or ceil(p), so
    the shortest common run brackets p. Pick the p (and offset) whose grid lines sit within half a
    pixel of nearly every colour edge, preferring the tightest fit. Returns (p, phx, phy) or None."""
    runs = _runs(a)
    if len(runs) < 4:
        return None
    vals, cnt = np.unique(runs, return_counts=True)
    common = vals[cnt >= 0.01 * len(runs)]
    if not len(common):
        return None
    m = int(common[0])
    edges = [np.flatnonzero(_profile(a, ax) > 0) + 1.0 for ax in (1, 0)]

    if any(not len(b) for b in edges):
        return None

    def best_phase(b, p, step):
        phi = np.arange(0, p, step)[:, None]
        r = np.abs((b[None] - phi + p / 2) % p - p / 2)
        fit = (r <= 0.5 + EPS).mean(1)
        score = fit - 0.05 * r.mean(1)                 # equal fits: prefer lines closest to the edges
        i = int(score.argmax())
        return float(score[i]), float(fit[i]), float(phi[i, 0])

    ps = []
    for b in edges:
        best = (-1.0, 0.0, 0.0)
        for p in np.arange(max(m - 0.05, 1.05), m + 1.05, 0.005):
            sc, fit, _ = best_phase(b, p, 0.05)
            if sc > best[0]:
                best = (sc, fit, float(p))
        if best[1] < 0.95:
            return None
        ps.append(best[2])
    p = round(sum(ps) / 2, 4)
    phx, phy = (best_phase(b, p, 0.01)[2] for b in edges)
    return p, phx, phy


def _period(G):
    """Pixel period of a noisy edge profile: autocorrelation, then a line fit through the strong
    edges (the strongest repeat can be a multiple of the pixel, e.g. x2.5 repeats every 5)."""
    n = len(G)
    if n < 12:
        return None
    g = G - G.mean()
    ac = np.correlate(g, g, "full")[n - 1:]
    ac = ac / (ac[0] + 1e-9)
    lim = min(n // 3, 128)
    pk = [l for l in range(2, lim - 1) if ac[l] > ac[l - 1] and ac[l] >= ac[l + 1] and ac[l] > 0.12]
    if not pk:
        return None
    best = max(ac[l] for l in pk)
    L = next(l for l in pk if ac[l] >= 0.6 * best)
    thr = np.percentile(G, 85)
    pos = np.array([i for i in range(1, n - 1) if G[i] > thr and G[i] >= G[i - 1] and G[i] >= G[i + 1]], float) + 1
    if len(pos) < 4:
        return float(L)
    for m in (1, 2, 3, 4):
        if L / m < 1.8:
            break
        k = np.round((pos - pos[0]) / (L / m))
        p, phi = np.polyfit(k, pos, 1)
        keep = np.abs(pos - (phi + k * p)) < 0.25 * p
        if keep.mean() >= 0.7:
            if keep.sum() >= 4:
                p, phi = np.polyfit(k[keep], pos[keep], 1)
            return float(p)
    return float(L)


def grid_noisy(a):
    px, py = _period(_profile(a, 1)), _period(_profile(a, 0))
    if not px and not py:
        return None
    if px and py and abs(px - py) / max(px, py) < 0.15:
        return (px + py) / 2
    return px or py


def refine(a, p0, axis, spread=0.15):
    """Best period and offset near p0 along one axis (1 = x, 0 = y): the grid whose cell centres,
    repeated over their cells, rebuild the image best. Fixes the few-percent error of grid_noisy."""
    f = a.astype(np.float32)
    f[..., :3] *= f[..., 3:4] / 255
    if axis == 0:
        f = f.transpose(1, 0, 2)
    f = f[::max(1, f.shape[0] // 96)]                     # ~96 lines are plenty
    n = f.shape[1]
    x = np.arange(n) + 0.5

    def err(p, phi):
        k = np.floor((x - phi) / p + EPS)
        c = np.clip(np.floor(phi + (k + 0.5) * p), 0, n - 1).astype(int)
        return float(np.abs(f[:, c] - f).mean())

    if spread == 0:  # Fixer's independent column and row counts already determine the pitch.
        offsets = np.arange(0, p0, max(0.1, p0 / 48)) if p0 > 1 else [0.0]
        return p0, float(min(offsets, key=lambda phi: err(p0, phi)))

    best = (np.inf, p0, 0.0)
    for p in np.arange(p0 * (1 - spread), p0 * (1 + spread), max(0.01, p0 * 0.004)):
        for phi in np.arange(0, p, 0.5):
            e = err(p, phi)
            if e < best[0]:
                best = (e, float(p), float(phi))
    e0, p, ph = best
    for p2 in np.arange(p - 0.02, p + 0.021, 0.002):        # finer pass around the winner
        for phi in np.arange(ph - 0.5, ph + 0.51, 0.05):
            e = err(p2, phi % p2)
            if e < best[0]:
                best = (e, float(p2), float(phi % p2))
    return best[1], best[2]


def centres(n, p, ph):
    """Pixel index of the middle of every whole-or-partial cell, and the cell numbers."""
    k = np.arange(math.floor(-ph / p) - 1, math.floor((n - ph) / p) + 2)
    c = ph + (k + 0.5) * p
    keep = (c >= 0) & (c < n)
    return np.floor(c[keep]).astype(int), k[keep]


def sample(a, px, py, phx, phy):
    """Median of the middle of every cell (robust to JPEG noise and soft cell edges)."""
    h, w = a.shape[:2]
    cy, ky = centres(h, py, phy)
    cx, kx = centres(w, px, phx)
    ry, rx = int(py * 0.25), int(px * 0.25)
    acc = [a[np.clip(cy + dy, 0, h - 1)][:, np.clip(cx + dx, 0, w - 1)]
           for dy in range(-ry, ry + 1) for dx in range(-rx, rx + 1)]
    return np.median(np.stack(acc), axis=0).astype(np.uint8), ky, kx


def _undo_linear_axis(values, count, axis):
    """Least-squares inverse of linear enlargement along one axis, with clamped ends."""
    from scipy.linalg import solveh_banded
    from scipy.sparse import csr_matrix

    lines = np.moveaxis(values, axis, 0)
    extent = len(lines)
    t = np.clip((np.arange(extent) + 0.5) * count / extent - 0.5, 0, count - 1)
    left = t.astype(int)
    frac = t - left
    # Each source sample mixes at most two adjacent native cells. The normal
    # equations consequently have just a diagonal and one off-diagonal.
    weights = np.column_stack((1 - frac, frac)).astype(np.float32)
    columns = np.column_stack((left, np.minimum(left + 1, count - 1)))
    basis = csr_matrix((weights.ravel(), columns.ravel(), np.arange(0, 2 * extent + 1, 2)),
                       shape=(extent, count))
    gram = basis.T @ basis
    band = np.zeros((2, count), np.float32)
    band[0], band[1, :-1] = gram.diagonal(), gram.diagonal(-1)
    fitted = solveh_banded(band, basis.T @ lines.reshape(extent, -1), lower=True)
    return np.moveaxis(fitted.reshape((count,) + lines.shape[1:]), 0, axis)


def restore_bilinear(src, native):
    """Recover cell colours only if bilinear enlargement explains the observed edges."""
    h, w = src.shape[:2]
    rows, cols = native.shape[:2]
    if min(rows, cols) < 2 or min(h / rows, w / cols) < 1.5:
        return None
    size = (cols, rows)
    centered = Image.fromarray(src).resize(size, Image.Resampling.NEAREST)
    def error(im, kernel):
        up = np.array(im.resize((w, h), kernel))
        return edge_loss(src, up)[0]

    nearest_loss = error(centered, Image.Resampling.NEAREST)
    if nearest_loss < 1:
        return None
    # With only two input samples per cell, neither sample hits its centre.
    # Judge those enlargements on the fitted pixels, below.
    if min(h / rows, w / cols) >= 3 and error(centered, Image.Resampling.BILINEAR) > 0.75 * nearest_loss:
        return None
    values = src.astype(np.float32)
    values[..., :3] *= values[..., 3:] / 255
    try:
        fitted = _undo_linear_axis(_undo_linear_axis(values, cols, 1), rows, 0)
    except ImportError:  # manual-size runs also work with just Pillow and NumPy
        return None
    fitted[..., :3] *= 255 / np.maximum(fitted[..., 3:], 1)
    rgba = np.clip(fitted.round(), 0, 255).astype(np.uint8)
    rgba[rgba[..., 3] < 128] = 0
    rgba[..., 3] = np.where(rgba[..., 3] >= 128, 255, 0)
    loss = error(Image.fromarray(rgba), Image.Resampling.BILINEAR)
    if loss <= min(3, 0.35 * nearest_loss):
        return rgba, loss
    return None


def rebuild(src, nat, px, py, phx, phy, ky, kx):
    """Map each source pixel back to its sampled cell, including clipped edge cells."""
    h, w = src.shape[:2]
    iy = np.clip(np.floor((np.arange(h) + 0.5 - phy) / py + EPS).astype(int) - ky[0], 0, nat.shape[0] - 1)
    ix = np.clip(np.floor((np.arange(w) + 0.5 - phx) / px + EPS).astype(int) - kx[0], 0, nat.shape[1] - 1)
    return nat[iy][:, ix]


def fit_error(src, nat, px, py, phx, phy, ky, kx):
    """Mean RGB difference over the visible source pixels."""
    up = rebuild(src, nat, px, py, phx, phy, ky, kx)
    m = src[..., 3] >= 128
    return float(np.abs(src[m, :3].astype(np.int16) - up[m, :3]).mean()) if m.any() else 0.0


def edge_loss(src, up):
    """Measure lost colour and silhouette detail without diluting it with flat background."""
    key = _key(src)
    edges = np.zeros(key.shape, bool)
    dx, dy = key[:, :-1] != key[:, 1:], key[:-1] != key[1:]
    edges[:, :-1] |= dx
    edges[:, 1:] |= dx
    edges[:-1] |= dy
    edges[1:] |= dy
    if not edges.any():
        return 0.0, 0.0
    diff = np.abs(src[edges].astype(np.int16) - up[edges])
    return float(np.maximum(diff[:, :3].mean(1), diff[:, 3]).mean()), float(diff.any(1).mean())


def profile_grid(src):
    p = grid_noisy(src)
    if p is not None and 1.5 < p <= min(src.shape[:2]):
        (px, phx), (py, phy) = refine(src, p, 1), refine(src, p, 0)
        if abs(px - py) / max(px, py) < 0.01:
            px = py = (px + py) / 2
        if 1 <= px <= src.shape[1] and 1 <= py <= src.shape[0]:
            return px, py, phx, phy, "noisy"
    return None


def fallback_grid(src, native_possible, notes):
    if not native_possible:
        grid = profile_grid(src)
        if grid:
            return grid
    notes.append("Grid unconfirmed. Kept the input size. Check fine detail or pass --size.")
    return 1.0, 1.0, 0.0, 0.0, "native"


def clean_grid(src, p, phx, phy):
    """Check that both axes actually share the inferred grid, including its offset."""
    for axis, phi in ((1, phx), (0, phy)):
        edges = np.flatnonzero(_profile(src, axis)) + 1
        line = np.rint((edges - phi) / p)
        residual = edges - (phi + line * p)
        if (np.abs(residual) > 0.5 + EPS).any() or (np.diff(line) == 0).any():
            return False
    return True


def native_or_fixer(src, grid, ncolors, rep):
    """Choose between identity and a proposed reduction using the detail it would lose."""
    px, py, phx, phy = grid
    h, w = src.shape[:2]
    nat, ky, kx = sample(src, *grid)
    loss, changed = edge_loss(src, rebuild(src, nat, *grid, ky, kx))
    rows, cols = nat.shape[:2]
    evidence = {"input_size": [w, h], "fixer_size": [cols, rows], "fixer_edge_error": round(loss, 2)}
    rep["grid_candidates"] = evidence
    rep["notes"].append(f"Input could be native ({w}x{h}). Inspect fine detail at the "
                        f"proposed {cols}x{rows} size. Use --size to try either size.")
    # Two close palette entries can still encode a distinct one-pixel detail.
    if loss <= 6 and (ncolors > 32 or changed <= 0.2) and (nat[..., 3] >= 128).any():
        return px, py, phx, phy, "fixer"

    # A bilinear upscale contains real ramps between cells. Test that image
    # formation model before interpreting its nearest-neighbour misfit as lost detail.
    if loss > 6:
        centered, _, _ = sample(src, px, py, 0, 0)
        smooth = Image.fromarray(centered).resize((w, h), Image.Resampling.BILINEAR)
        smooth_loss, _ = edge_loss(src, np.asarray(smooth))
        evidence["bilinear_edge_error"] = round(smooth_loss, 2)
        if smooth_loss <= min(10, 0.5 * loss) and (centered[..., 3] >= 128).any():
            return px, py, 0.0, 0.0, "fixer"
    return 1.0, 1.0, 0.0, 0.0, "native"


def has_fine_texture(src):
    """Frequent strong reversals one pixel apart indicate native detail, even in truecolour art."""
    energy = correlation = 0.0
    for axis in (0, 1):
        # Sample scanlines, keeping adjacent pixels along the measured axis.
        lines = np.moveaxis(src, axis, 1)
        lines = lines[::max(1, lines.shape[0] // 96)].astype(np.float32)
        delta = np.diff(lines, axis=1)
        energy += float(np.sum(delta * delta))
        correlation += float(np.sum(delta[:, 1:] * delta[:, :-1]))
    return correlation < -0.25 * energy


def detect_grid(src, rep):
    h, w = src.shape[:2]
    g, ones = grid_exact(src)
    if 2 <= g <= min(w, h):
        phx, phy = (_phase(_profile(src, axis), g) for axis in (1, 0))
        if clean_grid(src, g, phx, phy):
            return g, g, phx, phy, "exact"

    ncolors = len(np.unique(_key(src)))
    if ncolors == 1:
        return fallback_grid(src, True, rep["notes"])
    native_possible = ncolors <= 256 and ones >= 0.02
    if ncolors <= 256 and not native_possible:
        fr = grid_fractional(src)
        if fr and 1.5 < fr[0] <= min(w, h) and not fr[0].is_integer() and clean_grid(src, *fr):
            p, phx, phy = fr
            return p, p, phx, phy, "fractional"

    # Use the detector within the same bounds as its upstream Python API.
    if min(h, w) < 16 or h * w > 4_000_000:
        rep["notes"].append("Canvas outside the damaged-grid detector's range (16 px per side, 4 MP maximum).")
        return fallback_grid(src, native_possible, rep["notes"])
    try:
        from pixelfixer import detect
        proposal = detect(src, low_memory=h * w > 1_000_000)
        cols, rows = proposal["cols"], proposal["rows"]
        if not (1 <= cols <= w and 1 <= rows <= h) or (cols, rows) == (w, h):
            raise ValueError("no smaller grid")
    except Exception as exc:  # upstream numerical and OpenCV failures vary by backend
        rep["notes"].append(f"Damaged-grid detector unavailable ({exc}). Used the original grid check.")
        return fallback_grid(src, native_possible, rep["notes"])

    # The counts describe the entire canvas. A fixed pitch keeps independent
    # X/Y scales and a phase search accommodates cropped or shifted exports.
    px, py = w / cols, h / rows
    _, phx = refine(src, px, 1, spread=0)
    _, phy = refine(src, py, 0, spread=0)
    if native_possible or (ncolors > 256 and ones >= 0.5 and has_fine_texture(src)):
        return native_or_fixer(src, (px, py, phx, phy), ncolors, rep)
    if max(cols, rows) >= 96:
        # On a long sheet a 1% pitch error drifts across a whole cell.
        # Compare the measured edge-profile grid if it agrees on the scale.
        other = profile_grid(src)
        if other and abs(other[0] / px - 1) < 0.05 and abs(other[1] / py - 1) < 0.05:
            def error(grid):
                nat, ky, kx = sample(src, *grid)
                return fit_error(src, nat, *grid, ky, kx)

            if error(other[:4]) < error((px, py, phx, phy)):
                return other
    return px, py, phx, phy, "fixer"


def grid_image(src, px, py, phx, phy, path):
    """The input with the detected grid as dotted magenta lines."""
    img = src[..., :3].astype(np.float32).copy()
    al = src[..., 3:4] / 255.0
    img = img * al + 200 * (1 - al)
    h, w = img.shape[:2]
    mag = np.array([255, 0, 255], np.float32)
    xs = np.arange(phx % px, w, px).astype(int)
    ys = np.arange(phy % py, h, py).astype(int)
    xs, ys = xs[xs < w], ys[ys < h]  # floating-point steps can land on the far boundary
    img[::2, xs] = img[::2, xs] * 0.4 + mag * 0.6
    img[ys, ::2] = img[ys, ::2] * 0.4 + mag * 0.6
    Image.fromarray(img.astype(np.uint8)).save(path)


def check_image(nat, path):
    """The result enlarged on the flat colour least like its palette, so leftovers stand out."""
    m = nat[..., 3] > 0
    pal = np.unique(nat[m][:, :3], axis=0).astype(int)
    cands = np.array([[0, 200, 80], [255, 0, 200], [0, 150, 255], [255, 220, 0], [255, 255, 255], [0, 0, 0]])
    bg = cands[np.argmax([np.abs(pal - c).max(1).min() for c in cands])]
    k = max(1, min(16, 640 // max(nat.shape[:2])))
    img = np.where(m[..., None], nat[..., :3], bg).astype(np.uint8)
    Image.fromarray(img.repeat(k, 0).repeat(k, 1)).save(path)


def dilate4(m):
    o = m.copy()
    o[1:] |= m[:-1]; o[:-1] |= m[1:]; o[:, 1:] |= m[:, :-1]; o[:, :-1] |= m[:, 1:]
    return o


def flood(cand, seed):
    """Grow seed through cand (4-neighbour). Fills whole runs at a time, rows then columns."""
    fill = seed & cand
    while True:
        prev = fill
        for t in (False, True):
            c, f = (cand.T, fill.T) if t else (cand, fill)
            start = c.copy()
            start[:, 1:] &= ~c[:, :-1]
            rid = np.cumsum(start.ravel()).reshape(c.shape) * c
            hit = np.zeros(int(rid.max()) + 1, bool)
            hit[rid[f & c]] = True
            hit[0] = False
            f = hit[rid]
            fill = f.T if t else f
        if (fill == prev).all():
            return fill


def _edge(m):
    e = np.zeros_like(m)
    e[0], e[-1], e[:, 0], e[:, -1] = True, True, True, True
    return e & m


def _clusters(px, tol=16):
    """Greedy colour groups, most common first: (colours, counts). JPEG noise joins its colour."""
    vals, cnt = np.unique(px // 4 * 4 + 2, axis=0, return_counts=True)
    cols, tot = [], []
    for i in np.argsort(-cnt):
        v = vals[i].astype(int)
        for j, c in enumerate(cols):
            if np.abs(c - v).max() <= tol:
                tot[j] += int(cnt[i])
                break
        else:
            cols.append(v)
            tot.append(int(cnt[i]))
    return cols, tot


def _border_lines(a):
    return a[0], a[-1], a[:, 0], a[:, -1]


def _alternates(a, c1, c2):
    """Check for steady alternation between two colours along the border."""
    short_axes = set()
    for side, line in enumerate(_border_lines(a)):
        px = line[:, :3].astype(int)
        lab = np.abs(px - c1).max(-1) <= np.abs(px - c2).max(-1)
        runs = np.diff(np.concatenate([[0], np.flatnonzero(lab[1:] != lab[:-1]) + 1, [len(lab)]]))
        inner = runs[1:-1]
        long_runs = inner[inner >= 3]  # Ignore JPEG flicker at tile seams.
        if len(long_runs) >= 3 and long_runs.std() <= 0.2 * long_runs.mean():
            return True
        # A small checkerboard can have just one or two whole tiles per side.
        # Require equally spaced transitions in both directions in that case.
        if (len(inner) in (1, 2) and inner.min() >= 3 and inner.std() <= 0.2 * inner.mean()
                and max(runs[0], runs[-1]) <= 1.2 * inner.mean()):
            short_axes.add(side // 2)
    return len(short_axes) == 2


def _flat_border_colour(a):
    """Identify an opaque flat backdrop by its corners and majority border colour."""
    if (a[..., 3] != 255).any():
        return None
    rgb = a[..., :3]
    colour = rgb[0, 0]
    if not (rgb[np.ix_([0, -1], [0, -1])] == colour).all():
        return None
    border = np.concatenate(_border_lines(rgb))
    same = (border == colour).all(1)
    if same.mean() <= 0.5:
        return None
    if not same.all():
        other, counts = np.unique(border[~same], axis=0, return_counts=True)
        if _alternates(a, colour.astype(int), other[counts.argmax()].astype(int)):
            return None
    return colour.astype(int)


def _border_colours(a):
    """The colour along the border, or the two colours of a checkerboard (an editor's greys, or
    any two colours laid out as a regular checkerboard behind the art)."""
    border = np.concatenate(_border_lines(a))[:, :3].astype(int)
    cols, tot = _clusters(border)
    bgs = [cols[0]]
    if len(cols) > 1 and tot[1] >= 0.25 * tot[0] and np.abs(cols[1] - cols[0]).max() <= 96:
        grey = lambda c: c.max() - c.min() < 24
        if (grey(cols[0]) and grey(cols[1])) or _alternates(a, cols[0], cols[1]):
            bgs.append(cols[1])
    return bgs


def _near(a, bgs, tol):
    m = a[..., 3] < 128
    for bg in bgs:
        m |= np.abs(a[..., :3].astype(int) - bg).max(-1) <= tol
    return m


def _desc(bgs):
    return ("checkerboard " if len(bgs) > 1 else "") + "/".join("#%02x%02x%02x" % tuple(int(v) for v in b) for b in bgs)


def _biggest_box(m):
    """Bounding box (x, y, w, h) of the largest connected part of m (labelled on a coarse grid)."""
    f = max(1, int(math.ceil(math.sqrt(m.size / 40000))))
    H, W = -(-m.shape[0] // f), -(-m.shape[1] // f)
    g = np.zeros((H * f, W * f), bool)
    g[:m.shape[0], :m.shape[1]] = m
    g = g.reshape(H, f, W, f).any((1, 3))
    seen, best = np.zeros_like(g), (0, None)
    for y0, x0 in zip(*np.nonzero(g)):
        if seen[y0, x0]:
            continue
        st, cells = [(y0, x0)], []
        seen[y0, x0] = True
        while st:
            y, x = st.pop()
            cells.append((y, x))
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < H and 0 <= xx < W and g[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    st.append((yy, xx))
        if len(cells) > best[0]:
            best = (len(cells), cells)
    if not best[1]:
        return None
    ys, xs = zip(*best[1])
    y0, y1 = min(ys) * f, min((max(ys) + 1) * f, m.shape[0])
    x0, x1 = min(xs) * f, min((max(xs) + 1) * f, m.shape[1])
    sub = m[y0:y1, x0:x1]
    yy, xx = np.nonzero(sub)
    return int(x0 + xx.min()), int(y0 + yy.min()), int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1)


def isolate(a, mode, tol):
    """Clear the background at full resolution, before looking for the grid, so a flat backdrop,
    an editor checkerboard or the UI around a canvas adds no edges of its own.
    Returns (img with alpha, description, canvas box or None)."""
    a = a.copy()
    if mode == "none":
        a[..., 3] = 255
        return a, "kept", None
    if mode == "auto" and (a[..., 3] < 128).any():
        m = a[..., 3] >= 128
        desc, box = "transparent", None
    else:
        bgs = _border_colours(a) if mode == "auto" else [np.array([int(mode.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)])]
        cand = _near(a, bgs, tol)
        m = ~flood(cand, _edge(cand))
        desc, box = _desc(bgs), None
        b = _biggest_box(m) if mode == "auto" and m.any() else None
        if b:
            x, y, w, h = b
            sub, inside = a[y:y + h, x:x + w], m[y:y + h, x:x + w]
            if w * h >= 0.04 * m.size and inside.mean() >= 0.9 and min(w, h) >= 16:
                bgs2 = _border_colours(sub)
                # A two-tone rectangular sprite also looks like a canvas. Require
                # an inner checkerboard or evidence of surrounding editor chrome.
                checker = len(bgs2) == 2 and _alternates(sub, *bgs2)
                inside_pixels = inside.sum()
                outside_pixels = m.sum() - inside_pixels
                chrome = (0 < outside_pixels < inside_pixels / 2
                          and _flat_border_colour(a) is None)
                cand2 = _near(sub, bgs2, tol)
                if (checker or chrome) and cand2.mean() >= 0.3:
                    m2 = ~flood(cand2, _edge(cand2))
                    if m2.any():
                        a, m, box = sub.copy(), m2, [x, y, w, h]
                        desc = f"{desc}, then canvas {_desc(bgs2)}"
    a[..., 3] = np.where(m, 255, 0)
    a[~m] = 0
    return a, desc, box


def parts(mask):
    """Connected parts of mask, diagonal neighbours included: (labels, sizes), labels 1..n."""
    lab = np.zeros(mask.shape, np.int32)
    H, W = mask.shape
    sizes = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if lab[y0, x0]:
            continue
        n = len(sizes) + 1
        lab[y0, x0] = n
        st, cnt = [(y0, x0)], 0
        while st:
            y, x = st.pop()
            cnt += 1
            for yy in (y - 1, y, y + 1):
                for xx in (x - 1, x, x + 1):
                    if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n
                        st.append((yy, xx))
        sizes.append(cnt)
    return lab, np.array(sizes, int)


def drop_parts(nat, mode, split):
    """Remove stray parts. auto: small parts near the image edge (frame lines, rulers, canvas
    borders); largest: everything but the biggest part. Returns notes for the report."""
    m = nat[..., 3] > 0
    if mode == "all" or m.size > 1024 * 1024:
        return {}, []
    lab, sizes = parts(m)
    if len(sizes) < 2:
        return {"count": int(len(sizes))}, []
    big = int(sizes.argmax()) + 1
    small = sizes < max(4, 0.02 * sizes.max())
    H, W = m.shape
    bm = lab == big
    if mode == "auto" and (bm[0].any() or bm[-1].any() or bm[:, 0].any() or bm[:, -1].any()):
        mode = "keep"                         # the art itself reaches the edge (a scene or a tight crop)
    drop = []
    for i in range(1, len(sizes) + 1):
        if mode == "largest":
            if i != big:
                drop.append(i)
            continue
        ys, xs = np.nonzero(lab == i)
        if mode == "auto" and small[i - 1] and (ys.min() <= 2 or xs.min() <= 2 or ys.max() >= H - 3 or xs.max() >= W - 3):
            drop.append(i)
    notes = []
    if drop:
        gone = np.isin(lab, drop)
        if mode == "auto":                    # frame pixels touching the drawing: same colour, same edge band
            band = np.zeros_like(m)
            band[:3], band[-3:], band[:, :3], band[:, -3:] = True, True, True, True
            for c in np.unique(nat[gone][:, :3], axis=0).astype(int):
                gone |= band & m & (np.abs(nat[..., :3].astype(int) - c).max(-1) <= 12)
        nat[gone] = 0
        notes.append(f"dropped {len(drop)} small part(s) ({int(gone.sum())} px) "
                     + ("other than the main drawing" if mode == "largest" else
                        "at the image edge: frame or canvas leftovers. --parts all keeps them"))
    rest = [i for i in range(1, len(sizes) + 1) if i not in drop and i != big]
    if rest and not split:
        notes.append(f"{len(rest)} more part(s) sit apart from the main drawing "
                     f"(sizes {sorted((int(sizes[i - 1]) for i in rest), reverse=True)[:6]}): "
                     "intended (sparkles, separate pieces) or leftovers? Check the _check.png; "
                     "--parts largest keeps only the main drawing")
    return {"count": int(len(sizes)), "dropped": len(drop)}, notes


def merge_close(nat, m, tol=12):
    """JPEG and blur leave many near-copies of every colour. Fold each colour into the most common
    colour within tol of it. Returns (colours before, colours after)."""
    vals, inv, cnt = np.unique(nat[m][:, :3], axis=0, return_inverse=True, return_counts=True)
    cents = np.zeros((len(vals), 3), int)
    owner, n = np.zeros(len(vals), int), 0
    for i in np.argsort(-cnt):
        v = vals[i].astype(int)
        if n:
            d = np.abs(cents[:n] - v).max(1)
            j = int(d.argmin())
            if d[j] <= tol:
                owner[i] = j
                continue
        cents[n], owner[i] = v, n
        n += 1
    nat[m, :3] = cents[owner[inv.reshape(-1)]].astype(np.uint8)
    return len(vals), n


def layout(boxes):
    """Rows and columns of the drawings, and the cell grid if they sit on a regular one (sprite
    sheets): (row per box, col per box, grid dict or None)."""
    n = len(boxes)
    row = np.array([b[5] for b in boxes])
    xc = np.array([b[0] + b[2] / 2 for b in boxes])
    order = np.argsort(xc)
    col = np.zeros(n, int)
    gap = 0.5 * np.median([b[2] for b in boxes])
    for a_, b_ in zip(order[:-1], order[1:]):
        col[b_] = col[a_] + (xc[b_] - xc[a_] > gap)
    nr, nc = int(row.max()) + 1, int(col.max()) + 1
    if len(set(zip(row, col))) < n or (min(nr, nc) < 2 and max(nr, nc) < 3):
        return row, col, None
    for k in (2, 3):                                  # sheet cells hold drawings of similar size
        v = np.array([b[k] for b in boxes], float)
        if v.max() > 2 * v.min():
            return row, col, None
    pitch, start = [], []
    for idx, centre, k in ((col, xc, nc), (row, np.array([b[1] + b[3] / 2 for b in boxes]), nr)):
        c = np.array([centre[idx == i].mean() for i in range(k)])
        if k == 1:
            pitch.append(None)
            start.append(0.0)
            continue
        dif = np.diff(c)
        p = float(np.median(dif))
        if p <= 0 or np.abs(dif - p).max() > max(2.0, 0.15 * p):
            return row, col, None
        pitch.append(p)
        start.append(float(c[0] - p / 2))
    return row, col, {"rows": nr, "cols": nc, "pitch": pitch, "start": start}


def drawings(mask, reach=4, min_share=0.15, small=0.25):
    """Separate drawings in reading order. A small part (under `small` of the biggest part: a
    sparkle, a detached hand, a dot of shadow) joins a part at least twice its size within `reach`
    px. Bigger parts never merge, however close: a character's side view has about half the pixels
    of its front view, and in a ring of directions the views nearly touch. Parts under min_share
    of the biggest are dropped as marks. Returns (boxes [x, y, w, h, px, row], marks dropped)."""
    lab, sizes = parts(mask)
    if not len(sizes):
        return [], 0
    H, W = mask.shape
    order = np.argsort(lab.ravel(), kind="stable")
    flat = lab.ravel()[order]
    cut = np.searchsorted(flat, np.arange(1, len(sizes) + 2))
    pix = [order[cut[i]:cut[i + 1]] for i in range(len(sizes))]       # flat indices per part
    owner = np.arange(len(sizes) + 1)
    size = np.concatenate([[0], sizes]).astype(int)

    def find(l):
        while owner[l] != l:
            l = owner[l]
        return l
    for i in np.argsort(sizes, kind="stable"):
        l = i + 1
        ys, xs = np.divmod(pix[i], W)
        y0, y1 = max(ys.min() - reach, 0), min(ys.max() + reach + 1, H)
        x0, x1 = max(xs.min() - reach, 0), min(xs.max() + reach + 1, W)
        sub = lab[y0:y1, x0:x1]
        g = sub == l
        for _ in range(reach):
            g = g | np.pad(g, 1)[2:, 1:-1] | np.pad(g, 1)[:-2, 1:-1]
            g = g | np.pad(g, 1)[1:-1, 2:] | np.pad(g, 1)[1:-1, :-2]
        me = find(l)
        if size[me] >= small * sizes.max():
            continue
        cand = {find(int(c)) for c in np.unique(sub[g & (sub > 0)])} - {me}
        cand = [c for c in cand if size[c] >= 2 * size[me]]
        if cand:
            t = max(cand, key=lambda c: size[c])
            owner[me] = t
            size[t] += size[me]
            size[me] = 0
    groups = {}
    for i in range(len(sizes)):
        groups.setdefault(find(i + 1), []).append(pix[i])
    boxes = []
    for g in groups.values():
        ys, xs = np.divmod(np.concatenate(g), W)
        boxes.append([int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1), len(ys)])
    big = max(b[4] for b in boxes)
    keep = [b for b in boxes if b[4] >= min_share * big]
    keep.sort(key=lambda b: b[1] + b[3] / 2)
    rows, cur, bottom = [], [], -1
    for b in keep:
        if cur and b[1] + b[3] / 2 > bottom:
            rows.append(cur); cur = []
        cur.append(b)
        bottom = max(bottom, b[1] + b[3]) if len(cur) > 1 else b[1] + b[3]
    rows.append(cur)
    return [b + [i] for i, r in enumerate(rows) for b in sorted(r, key=lambda b: b[0])], len(boxes) - len(keep)


def ascii_dump(a):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%&*+=?"
    keys, rows = {}, []
    for r in a:
        s = ""
        for p in r:
            if p[3] == 0:
                s += "."
                continue
            k = "#%02x%02x%02x" % tuple(p[:3])
            keys.setdefault(k, chars[len(keys) % len(chars)])
            s += keys[k]
        rows.append(s)
    return {"legend": {v: k for k, v in keys.items()}, "rows": rows}


def _orthographic_fit(sizes):
    """Return (labels_dict, best_err_or_None) for 2-4 drawings of one object."""
    n = len(sizes)
    if not 2 <= n <= 4:
        return {}, None
    hs = [h for _, h in sizes]
    if min(hs) >= 0.9 * max(hs) and all(h >= 1.2 * w for w, h in sizes):
        return {i: "front, back or side" for i in range(n)}, None
    lg = lambda a, b: abs(math.log(max(a, 1) / max(b, 1)))

    def err(t, s):
        (tw, th), (sw, sh) = sizes[t], sizes[s]
        rest = [sizes[i] for i in range(n) if i not in (t, s)]
        e = lg(th, sw)
        if rest:
            e += sum(lg(tw, fw) + lg(sh, fh) for fw, fh in rest) / len(rest)
        return e

    pairs = [(t, s) for t in range(n) for s in range(n) if t != s]
    best = min(err(t, s) for t, s in pairs)
    t, s = next(p for p in pairs if err(*p) <= best + 0.1)
    return {i: "top" if i == t else "side" if i == s else "front or back" for i in range(n)}, best


def guess_views(sizes):
    """Label 2-4 loose drawings of one object as top / side / front-back from their (w, h) sizes.
    A model sheet's views must agree: the top view's length (height) is the side view's width,
    the top view's width is the front's width, and the side view's height is the front's height.
    Picking by aspect ratio alone ("tallest is the top") fails for tall props such as trees and
    towers, whose side view is the tallest drawing. Reading order wins near-ties.
    Drawings that are all tall and about one height are a standing figure seen from several
    directions (a character's front, back and sides): no top view to find, so they are all
    labelled "front, back or side" and the face decides."""
    return _orthographic_fit(sizes)[0]


def _is_model_sheet(sizes, guess, err):
    """True when 2-4 drawings match orthographic model-sheet proportions (e.g. a 1x4 or 2x2 sheet
    with distinct top/side/front dimensions), rather than identical animation frames."""
    if not (2 <= len(sizes) <= 4) or err is None or err > 0.15 or "top" not in guess.values():
        return False
    ws = [w for w, _ in sizes]
    hs = [h for _, h in sizes]
    return max(ws) > 1.06 * min(ws) or max(hs) > 1.06 * min(hs)


def _cell_ranges(src, px, py, phx, phy, ky, kx):
    """Max per-channel RGB span inside each sampled cell (high on blurred/mixed silhouette edges)."""
    h, w = src.shape[:2]
    ny, nx = len(ky), len(kx)
    out = np.zeros((ny, nx), np.int16)
    rgb = src[..., :3].astype(np.int16)
    y0 = np.clip(np.floor(phy + ky * py).astype(int), 0, h - 1)
    y1 = np.clip(np.ceil(phy + (ky + 1) * py).astype(int), 1, h)
    x0 = np.clip(np.floor(phx + kx * px).astype(int), 0, w - 1)
    x1 = np.clip(np.ceil(phx + (kx + 1) * px).astype(int), 1, w)
    for r in range(ny):
        if y1[r] <= y0[r]:
            continue
        strip = rgb[y0[r]:y1[r]]
        for c in range(nx):
            if x1[c] <= x0[c]:
                continue
            patch = strip[:, x0[c]:x1[c]]
            out[r, c] = int((patch.max((0, 1)) - patch.min((0, 1))).max())
    return out


def _peel_halo(nat, src, flat_bg, px, py, phx, phy, ky, kx):
    """Peel 1-px semi-blended backdrop fringe on noisy/soft flat-background inputs so light-grey
    JPEG/bilinear halos cannot shield dark outlines from strip_outline(). Never eats genuine dark
    outlines on dark backgrounds (requires high-contrast inward neighbor along the B->Q segment)."""
    bg = np.asarray(flat_bg, np.float32)
    ranges = _cell_ranges(src, px, py, phx, phy, ky, kx) if (px > 1 or py > 1) else np.zeros(nat.shape[:2], np.int16)
    H, W = nat.shape[:2]
    total = 0
    for _ in range(2):
        m = nat[..., 3] >= 128
        if not m.any():
            break
        p = np.pad(m, 1)
        outer = m & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
        inner = m & ~outer
        rgb = nat[..., :3].astype(np.float32)
        peel = np.zeros_like(m)
        for y, x in zip(*np.nonzero(outer)):
            col = rgb[y, x]
            d_bg = float(np.abs(col - bg).max())
            # Collect opaque 4-neighbours, preferring strictly inward pixels over fellow edge pixels
            nbs = [(yy, xx) for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1))
                   if 0 <= yy < H and 0 <= xx < W and m[yy, xx]]
            in_nbs = [(yy, xx) for yy, xx in nbs if inner[yy, xx]]
            cand_nbs = in_nbs or nbs
            if not cand_nbs:
                if d_bg <= 24:
                    peel[y, x] = True
                continue
            if d_bg > 24 and ranges[y, x] < 32:
                continue
            best_hit = False
            for yy, xx in cand_nbs:
                v = rgb[yy, xx] - bg
                if float(np.abs(v).max()) < 48:
                    continue
                v2 = float(np.dot(v, v))
                t = float(np.dot(col - bg, v)) / v2
                if -0.1 <= t <= 0.55:
                    proj = bg + min(max(t, 0.0), 1.0) * v
                    if float(np.abs(col - proj).max()) <= 18:
                        best_hit = True
                        break
            if best_hit or (len(nbs) <= 1 and d_bg <= 24):
                peel[y, x] = True
        if not peel.any():
            break
        nat[peel] = 0
        total += int(peel.sum())
    return total


def _recover_split_view(sub_raw, flat_bg, px0, py0, phx0, phy0, x0, y0, bg_mode, bg_tol, user_bg_tol):
    """Re-fit the pixel grid on one cropped drawing from a noisy multi-view sheet, so per-view
    scale/phase drift in AI-generated sheets does not smear details or create edge halos.
    Returns (tight_nat, local_err, global_crop_err, restored) or None."""
    sub_iso, _, _ = isolate(sub_raw, bg_mode, bg_tol)
    sub_src = sub_raw if flat_bg is not None else sub_iso
    sh, sw = sub_src.shape[:2]
    if min(sh, sw) < 8:
        return None
    # Apples-to-apples baseline: the global sheet grid evaluated on this exact crop
    gphx, gphy = (phx0 - x0) % px0, (phy0 - y0) % py0
    gnat, gky, gkx = sample(sub_src, px0, py0, gphx, gphy)
    gerr = fit_error(sub_src, gnat, px0, py0, gphx, gphy, gky, gkx)
    # Candidate 1: global pitch with per-view phase alignment (zero pitch-shrinkage bias)
    _, pphx = refine(sub_src, px0, 1, spread=0)
    _, pphy = refine(sub_src, py0, 0, spread=0)
    pnat, pky, pkx = sample(sub_src, px0, py0, pphx, pphy)
    perr = fit_error(sub_src, pnat, px0, py0, pphx, pphy, pky, pkx)
    lpx, lpy, lphx, lphy, lnat, lky, lkx, lerr = px0, py0, pphx, pphy, pnat, pky, pkx, perr
    if gerr <= perr:
        lphx, lphy, lnat, lky, lkx, lerr = gphx, gphy, gnat, gky, gkx, gerr
    # Candidate 2: unbiased per-view pitch from pixelfixer + phase alignment, when near sheet pitch
    if min(sh, sw) >= 16 and sh * sw <= 1_000_000:
        try:
            from pixelfixer import detect
            prop = detect(sub_src, low_memory=False)
            c, r = prop["cols"], prop["rows"]
            if 1 <= c < sw and 1 <= r < sh:
                fpx, fpy = sw / c, sh / r
                if 0.82 <= fpx / px0 <= 1.22 and 0.82 <= fpy / py0 <= 1.22:
                    _, fphx = refine(sub_src, fpx, 1, spread=0)
                    _, fphy = refine(sub_src, fpy, 0, spread=0)
                    fnat, fky, fkx = sample(sub_src, fpx, fpy, fphx, fphy)
                    ferr = fit_error(sub_src, fnat, fpx, fpy, fphx, fphy, fky, fkx)
                    if ferr <= 1.15 * min(gerr, perr):
                        lpx, lpy, lphx, lphy, lnat, lky, lkx, lerr = fpx, fpy, fphx, fphy, fnat, fky, fkx, ferr
        except Exception:
            pass
    restored = False
    if lerr > 0:
        ref = sub_raw if bg_mode == "auto" and flat_bg is None else sub_src
        bilin = restore_bilinear(ref, lnat)
        if bilin is not None:
            lnat, _ = bilin
            lpy, lpx = sh / lnat.shape[0], sw / lnat.shape[1]
            lphx = lphy = 0.0
            lky, lkx = np.arange(lnat.shape[0]), np.arange(lnat.shape[1])
            lerr = fit_error(sub_src, lnat, lpx, lpy, lphx, lphy, lky, lkx)
            restored = True
    if flat_bg is not None:
        tol = user_bg_tol if user_bg_tol is not None else (1 if restored else 8)
        if restored:
            bg_px = _near(lnat, [flat_bg], tol)
        else:
            cy, _ = centres(sh, lpy, lphy)
            cx, _ = centres(sw, lpx, lphx)
            bg_px = _near(sub_src[cy][:, cx], [flat_bg], tol)
        lnat[..., 3][flood(bg_px, _edge(bg_px))] = 0
        if not restored and user_bg_tol is None:
            _peel_halo(lnat, sub_src, flat_bg, lpx, lpy, lphx, lphy, lky, lkx)
    lnat[..., 3] = np.where(lnat[..., 3] >= 128, 255, 0)
    lnat[lnat[..., 3] == 0] = 0
    ys, xs = np.nonzero(lnat[..., 3] > 0)
    if not len(ys):
        return None
    tight = lnat[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight, lerr, gerr, restored


def _safe_view_crops(boxes, raw_shape, px, py, phx, phy, kx0, ky0):
    """Full-res bounding boxes for each split drawing, expanded by ~1.5 art px for backdrop context
    while clamped halfway to neighbouring drawings so crops never overlap another view."""
    H, W = raw_shape[:2]
    rects = []
    for b in boxes:
        x0 = phx + (b[0] + kx0) * px
        y0 = phy + (b[1] + ky0) * py
        x1 = phx + (b[0] + b[2] + kx0) * px
        y1 = phy + (b[1] + b[3] + ky0) * py
        rects.append([x0, y0, x1, y1])
    crops = []
    mx, my = max(2.0, 1.5 * px), max(2.0, 1.5 * py)
    for i, (x0, y0, x1, y1) in enumerate(rects):
        lx, rx, ty, by = max(0.0, x0 - mx), min(float(W), x1 + mx), max(0.0, y0 - my), min(float(H), y1 + my)
        for j, (ox0, oy0, ox1, oy1) in enumerate(rects):
            if i == j:
                continue
            if oy1 > y0 and oy0 < y1:                    # horizontally adjacent
                if ox1 <= x0:
                    lx = max(lx, (ox1 + x0) / 2)
                elif ox0 >= x1:
                    rx = min(rx, (x1 + ox0) / 2)
            if ox1 > x0 and ox0 < x1:                    # vertically adjacent
                if oy1 <= y0:
                    ty = max(ty, (oy1 + y0) / 2)
                elif oy0 >= y1:
                    by = min(by, (y1 + oy0) / 2)
        crops.append((int(math.floor(lx)), int(math.floor(ty)), int(math.ceil(rx)), int(math.ceil(by))))
    return crops


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("image")
    ap.add_argument("-o", "--out", help="output PNG (default: ./<name>_native.png)")
    ap.add_argument("--crop", help="X,Y,W,H in input pixels: cut to the art before anything else")
    ap.add_argument("--pixel", help="image px per art px, e.g. 7 or 6.84 or 7,6.9 for x,y (default: detect)")
    ap.add_argument("--size", help="WxH in art pixels of the region used (after --crop / canvas), e.g. 64x64")
    ap.add_argument("--bg", default="auto", help="auto | none | #rrggbb (default auto: transparency, "
                                                 "else the border colour or an editor checkerboard)")
    ap.add_argument("--bg-tol", type=int, help="override the background colour tolerance (0-255)")
    ap.add_argument("--colors", type=int, default=0,
                    help="reduce to N colours (default: reduce noisy palettes above 48 colours to 32)")
    ap.add_argument("--parts", default="auto", choices=["auto", "all", "largest"],
                    help="stray parts: auto drops small ones at the image edge (frame lines); "
                         "largest keeps only the biggest drawing; all keeps everything (auto)")
    ap.add_argument("--split", action="store_true", help="also write each separate drawing as OUT_1.png ...")
    ap.add_argument("--ascii", action="store_true", help="include a text dump of the result (up to 128x128)")
    a = ap.parse_args()

    if not os.path.isfile(a.image):
        fail(f"no such file: {a.image}")
    src = np.array(Image.open(a.image).convert("RGBA"))
    rep = {"input": a.image, "input_size": [src.shape[1], src.shape[0]], "notes": []}
    if a.crop:
        try:
            x, y, w, h = (int(float(v)) for v in a.crop.split(","))
        except ValueError:
            fail("--crop takes X,Y,W,H, e.g. --crop 212,80,448,448")
        src = src[max(y, 0):y + h, max(x, 0):x + w]
        if src.size == 0:
            fail(f"--crop {a.crop} is outside the {rep['input_size'][0]}x{rep['input_size'][1]} image")
        rep["crop"] = [x, y, src.shape[1], src.shape[0]]
    ox, oy = (rep["crop"][0], rep["crop"][1]) if a.crop else (0, 0)

    raw = src
    bg_tol = 28 if a.bg_tol is None else a.bg_tol
    src, rep["background"], box = isolate(src, a.bg, bg_tol)
    flat_bg = _flat_border_colour(raw) if a.bg == "auto" and box is None else None
    if flat_bg is not None:
        # The original colours still contain the grid evidence in blurred edges.
        src = raw
        rep["background"] = _desc([flat_bg])
    if box:
        raw = raw[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
        rep["canvas"] = [box[0] + ox, box[1] + oy, box[2], box[3]]
        rep["notes"].append("found a canvas inside the image and used only that (see 'canvas', input pixels)")
    if not (src[..., 3] > 0).any():
        fail("nothing left after background removal; try --bg none or a lower --bg-tol", 3)

    h, w = src.shape[:2]
    if a.size:
        try:
            nw, nh = (int(v) for v in a.size.lower().split("x"))
        except ValueError:
            fail("--size takes WxH, e.g. --size 64x64")
        if not (1 <= nw <= w and 1 <= nh <= h):
            fail("--size must be positive and fit inside the canvas")
        px, py, phx, phy, method = w / nw, h / nh, 0.0, 0.0, "size"
    elif a.pixel:
        try:
            vals = [float(v) for v in a.pixel.split(",")]
        except ValueError:
            fail("--pixel takes a number, or X,Y numbers, e.g. --pixel 7 or --pixel 7,6.9")
        if len(vals) not in (1, 2) or not all(math.isfinite(v) and v >= 1 for v in vals):
            fail("--pixel takes one or two finite numbers of at least 1")
        px, py = vals[0], vals[-1]
        if px > w or py > h:
            fail("--pixel exceeds the canvas size")
        G1, G0 = _profile(src, 1), _profile(src, 0)
        phx, phy, method = _phase(G1, px) if px > 1 else 0.0, _phase(G0, py) if py > 1 else 0.0, "given"
    else:
        px, py, phx, phy, method = detect_grid(src, rep)

    if min(px, py) < 1:
        fail(f"pixel size {px:.3g},{py:.3g} is below 1; --size is larger than the image?")
    if px > 1 or py > 1:
        nat, ky, kx = sample(src, px, py, phx, phy)
        err = fit_error(src, nat, px, py, phx, phy, ky, kx)
    else:
        nat, err = src.copy(), 0.0
        ky, kx = np.arange(h), np.arange(w)
    if method in ("size", "given", "noisy", "fixer") and err > 0:
        reference = raw if rep["background"] == "transparent" else src
        restored = restore_bilinear(reference, nat)
        if restored is not None:
            nat, loss = restored
            py, px = h / nat.shape[0], w / nat.shape[1]
            phx = phy = 0.0
            ky, kx = np.arange(nat.shape[0]), np.arange(nat.shape[1])
            err = fit_error(src, nat, px, py, phx, phy, ky, kx)
            rep["bilinear_edge_error"] = round(loss, 2)
            rep["notes"].append("Recovered cell colours by fitting a bilinear enlargement to the input.")
    rep.update(method=method, pixel=[round(px, 3), round(py, 3)], phase=[round(phx, 2), round(phy, 2)],
               fit_error=round(err, 2))
    if err > 20 and "bilinear_edge_error" not in rep:
        rep["notes"].append("fit_error is high: the grid is probably wrong. Crop to the art (--crop), "
                            "or measure one art pixel and pass --pixel / --size. If the picture isn't "
                            "pixel art at all (smooth edges, gradients, a vector drawing), there is no "
                            "grid: choose the resolution yourself with --pixel N (N x N image px become "
                            "one art px; --pixel 1 keeps every pixel). Pick N so the object is about "
                            "16-96 px on its longest side.")

    restored_colours = "bilinear_edge_error" in rep
    if flat_bg is not None:
        tolerance = a.bg_tol
        if tolerance is None:
            # Exact matches protect close palette colours in clean art. Blurred or
            # compressed resizes leave a halo a few levels off the backdrop round every
            # drawing, and halos join drawings that nearly touch (a ring of directions).
            tolerance = 0 if method in ("native", "exact", "fractional") or err == 0 else 8
        # A verified fit has unmixed the backdrop from the edge colours.
        # Otherwise take a centre sample to limit bleed from nearby cells.
        if restored_colours:
            bg_pixels = _near(nat, [flat_bg], tolerance if a.bg_tol is not None else 1)
        else:
            cy, _ = centres(h, py, phy)
            cx, _ = centres(w, px, phx)
            bg_pixels = _near(src[cy][:, cx], [flat_bg], tolerance)
        nat[..., 3][flood(bg_pixels, _edge(bg_pixels))] = 0
        if not restored_colours and a.bg_tol is None and method in ("fixer", "noisy") and err > 0:
            peeled = _peel_halo(nat, src, flat_bg, px, py, phx, phy, ky, kx)
            if peeled:
                rep["notes"].append(f"peeled {peeled} anti-aliased backdrop halo pixel(s) around the silhouette")

    nat[..., 3] = np.where(nat[..., 3] >= 128, 255, 0)
    nat[nat[..., 3] == 0] = 0
    if not (nat[..., 3] > 0).any():
        fail("nothing left after background removal; try --bg none or a lower --bg-tol", 3)
    rep["parts"], more = drop_parts(nat, a.parts, a.split)
    rep["notes"] += more
    m = nat[..., 3] > 0
    ncol = len(np.unique(nat[m][:, :3], axis=0))
    if not a.colors and (restored_colours or method in ("fixer", "noisy")):
        before, ncol = merge_close(nat, m, tol=2 if restored_colours else 12)
        if ncol < before:
            rep["notes"].append(f"merged near-identical colours: {before} -> {ncol}")
    preserve_palette = restored_colours or method in ("exact", "fractional", "native") or err == 0
    target = a.colors or (32 if ncol > 48 and not preserve_palette else 0)
    if target and ncol > target:
        q = Image.fromarray(nat[m][:, :3][None]).quantize(target, method=Image.Quantize.MEDIANCUT,
                                                          dither=Image.Dither.NONE).convert("RGB")
        nat[m, :3] = np.array(q)[0]
        rep["notes"].append(f"reduced {ncol} colours to {target}")
        ncol = target
    rep["colors"] = ncol
    ys, xs = np.nonzero(m)
    rep["art_bbox"] = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
    rep["native_size"] = [nat.shape[1], nat.shape[0]]

    out = a.out or os.path.splitext(os.path.basename(a.image))[0] + "_native.png"
    stem = os.path.splitext(out)[0]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Image.fromarray(nat).save(out)
    rep["out"] = os.path.abspath(out)
    if px > 1 or py > 1:
        grid_image(raw, px, py, phx, phy, stem + "_grid.png")
        rep["grid_check"] = os.path.abspath(stem + "_grid.png")
    check_image(nat, stem + "_check.png")
    rep["check"] = os.path.abspath(stem + "_check.png")

    if a.split:
        boxes, dropped = drawings(m)
        rep["drawings"] = []
        row, col, grid = layout(boxes) if boxes else ([], [], None)
        sizes0 = [(b[2], b[3]) for b in boxes]
        guess, g_err = _orthographic_fit(sizes0) if 2 <= len(boxes) <= 4 else ({}, None)
        if grid and _is_model_sheet(sizes0, guess, g_err):
            grid = None                                   # 1x4 / 2x2 model sheet, not an animation grid
        refined_views = None
        if (not a.size and not a.pixel and not grid and method in ("fixer", "noisy")
                and err > 1.5 and 2 <= len(boxes) <= 8 and (px > 1.5 or py > 1.5)):
            crops = _safe_view_crops(boxes, raw.shape, px, py, phx, phy, int(kx[0]), int(ky[0]))
            res = [_recover_split_view(raw[y0:y1, x0:x1], flat_bg, px, py, phx, phy, x0, y0, a.bg, bg_tol, a.bg_tol)
                   for x0, y0, x1, y1 in crops]
            if all(r is not None for r in res):
                mean_local = sum(r[1] for r in res) / len(res)
                mean_global = sum(r[2] for r in res) / len(res)
                if mean_local < mean_global or any(r[3] for r in res):
                    refined_views = [r[0] for r in res]
                    # Harmonize near-duplicate JPEG colours across the refined split views
                    all_restored = all(r[3] for r in res)
                    if not a.colors:
                        tol_m = 2 if all_restored else 12
                        for rv in refined_views:
                            rm = rv[..., 3] > 0
                            if rm.any():
                                merge_close(rv, rm, tol=tol_m)
                    all_px = np.concatenate([rv[rv[..., 3] > 0][:, :3] for rv in refined_views])
                    ucol = len(np.unique(all_px, axis=0))
                    vtarget = a.colors or (32 if ucol > 48 and not all_restored else 0)
                    if vtarget and ucol > vtarget:
                        q = Image.fromarray(all_px[None]).quantize(vtarget, method=Image.Quantize.MEDIANCUT,
                                                                   dither=Image.Dither.NONE)
                        pal = np.array(q.getpalette()[:vtarget * 3]).reshape(-1, 3)
                        for rv in refined_views:
                            rm = rv[..., 3] > 0
                            if rm.any():
                                rv[rm, :3] = pal[((rv[rm, None, :3].astype(int) - pal[None]) ** 2).sum(-1).argmin(-1)]
                    rep["notes"].append(f"refined each split view's grid independently (mean crop fit_error {mean_global:.2f} -> {mean_local:.2f})")
                    rsizes = [(rv.shape[1], rv.shape[0]) for rv in refined_views]
                    guess, _ = _orthographic_fit(rsizes) if 2 <= len(rsizes) <= 4 else ({}, None)
        for i, b in enumerate(boxes, 1):
            x, y, w_, h_ = b[:4]
            f = f"{stem}_{i}.png"
            view_img = refined_views[i - 1] if refined_views is not None else nat[y:y + h_, x:x + w_]
            Image.fromarray(view_img).save(f)
            vw, vh = (view_img.shape[1], view_img.shape[0])
            d = {"file": os.path.abspath(f), "bbox": [x, y, vw, vh], "row": int(row[i - 1]) + 1,
                 "col": int(col[i - 1]) + 1}
            if i - 1 in guess:
                d["view_guess"] = guess[i - 1]
            rep["drawings"].append(d)
        if grid:
            # one box per cell, the same size and at the same place in every cell, so frames cut
            # from it keep their registration (walk bob, a tail swinging past the body's box)
            cx = lambda c: 0 if grid["pitch"][0] is None else int(round(grid["start"][0] + c * grid["pitch"][0]))
            cy = lambda r: 0 if grid["pitch"][1] is None else int(round(grid["start"][1] + r * grid["pitch"][1]))
            rel = [(b[0] - cx(c), b[1] - cy(r), b[0] + b[2] - cx(c), b[1] + b[3] - cy(r))
                   for b, r, c in zip(boxes, row, col)]
            L, T = min(v[0] for v in rel), min(v[1] for v in rel)
            R, B = max(v[2] for v in rel), max(v[3] for v in rel)
            pad = np.zeros((nat.shape[0] + 2 * (B - T), nat.shape[1] + 2 * (R - L), 4), np.uint8)
            oy_, ox_ = B - T, R - L
            pad[oy_:oy_ + nat.shape[0], ox_:ox_ + nat.shape[1]] = nat
            for d, r, c in zip(rep["drawings"], row, col):
                x0, y0 = cx(c) + L + ox_, cy(r) + T + oy_
                f = f"{stem}_r{r + 1}c{c + 1}.png"
                Image.fromarray(pad[y0:y0 + B - T, x0:x0 + R - L]).save(f)
                d["cell_file"] = os.path.abspath(f)
            rep["grid"] = {"rows": grid["rows"], "cols": grid["cols"], "cell_size": [R - L, B - T],
                           "note": "a regular sheet: rows are often directions and columns animation "
                                   "frames (or the other way round). Each cell_file is cut at the same "
                                   "place in its cell, so frames stay lined up; use them for animation."}
        if guess:
            if all(g == "front, back or side" for g in guess.values()):
                rep["notes"].append("view_guess: tall drawings of one height are direction views of a "
                                    "standing figure; tell front, back and sides apart by the face")
            else:
                rep["notes"].append("view_guess pairs drawings by matching sizes (top length = side length, "
                                    "top width = front width, side height = front height); confirm it by "
                                    "the drawings' features before carving")
        if dropped:
            rep["notes"].append(f"ignored {dropped} small marks (labels, specks)")
    if a.ascii:
        if max(nat.shape[:2]) > 128:
            rep["notes"].append("ascii skipped: larger than 128 px")
        else:
            rep["ascii"] = ascii_dump(nat)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
