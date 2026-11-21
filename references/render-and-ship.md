# Rendering and shipping

## `scripts/stack.py`

```bash
uv run scripts/stack.py obj_slices.png [--count H] [--outline '#1a1c2c'] [--squash 0.75] [--spacing 1]
       [--frames F] [--fps 8] [--dirs 16] [--gif] [--viewer] [--vox] [--all] [--no-shadow] [--bg '#e9e5dd'] [-o OUTDIR]
```

| output | what |
|---|---|
| `NAME.glb` | A single nonempty pose exports as a solid mesh with a nearest-sampled embedded palette texture. Y is up and +Z faces forward. Scale is 16 art pixels per metre; `--height M` makes the mesh M metres tall and `--ppm N` sets the density. Material preview in Blender shows the unlit palette. Use an orthographic game camera and a low-resolution viewport for screen-sized pixels. |
| `NAME.obj` | The same mesh as Wavefront OBJ, with `NAME.mtl` and `NAME_palette.png` beside it (keep the three files together). For tools without glTF import. `--no-obj` skips it. |
| `NAME_preview.png` | always written. Rows 1–2: turns of 0, 45, … 315° (0° = front toward the camera); with `--frames`, one row of 8 turns per frame. Last row: flat front, side (front to the left), back and top views of the volume. |
| `NAME_dirsN.png` | N facings, 8 per row, transparent, no shadow. Facing i points i·360/N° **clockwise from right** (screen y down). With `--frames`: one row per facing, one column per frame. Cell size is in the JSON. |
| `NAME_turntable.gif` | 48 frames, on `--bg`, with shadow; with `--frames`, 96 frames that play the animation at `--fps` while turning |
| `NAME_viewer.html` | self-contained: Turntable, Slice scan and Exploded modes; Live 3D normal-map + AO cel lighting (Day/Sunset/Night, `Shift+drag` sun orbit, auto-emissive glow) toggleable against raw unlit voxels; 1-px outline, shadow, squash, spacing, zoom, animation playback, and 16-direction PNG export |
| `NAME.vox` | MagicaVoxel model, surface voxels only, at most 256 per side (`NAME_fK.vox` per frame). MagicaVoxel opens it directly; Blender and Godot need an importer add-on. |

Sheets written by `save_sheet` store their slice count, frame count, and optional `outline` colour in the PNG, so `--count`, `--frames`, and `--outline` (which defaults to `auto`, using the stored outline if present; pass `--outline none` to disable) are picked up automatically. The JSON also reports `warnings`: empty bottom or top slices, half-transparent pixels, stray parts not touching the body, 1-px-thin parts that blink in a turning stack, too many colours, and a too-tall stack. `assets/viewer.html` works standalone too: open it and drop or paste any slice sheet PNG (it reads stored `slices`, `frames` and `outline` metadata automatically).

## Exact render math (to reimplement or debug)

The renderer works backwards from each screen pixel to a slice pixel:

- **Canvas.** For a W×D slice, diag = ceil(√(W² + D²)) + 2. A slice draws into a box diag wide and gh = ceil(diag·squash) tall. The stack's canvas is that box plus round((H−1)·spacing) px of lift, plus padding.
- **Sampling.** For a screen pixel at offset (px, py) from the slice centre, with py already divided by squash:
  - sx = floor(px·cos t + py·sin t + W/2)
  - sy = floor(−px·sin t + py·cos t + D/2)

  t is the turn: positive turns are clockwise on screen.
- **Layer order.** Slice z is drawn round(z·spacing) px higher, with later slices drawn over earlier ones.
- **Outline.** Applied once to the finished image: every empty pixel 4-adjacent to the object gets the outline colour.
- **Shadow.** Slice z's coverage is offset (0.5·z, 0.5·z·squash) px, and transparent pixels under it get black at alpha 70.

`stack.py` and the viewer implement this identically, byte for byte.

## In a game engine

Use the [sprite-stacking integration guide](sprite-stacking-guide.md) for live drawing code, static and animated direction-sheet layouts, heading conventions and pixel-perfect viewport settings. Its verification checklist covers layer order, sorting, scale and rotation.

## Voxel models in and out

- **Out:** `--vox` writes MagicaVoxel's format: SIZE (W, D, H), XYZI with x right, y away from the viewer (our y flipped) and z up, and a 256-entry RGBA palette.
- **In:** if the user already has a voxel model, export its layers from the voxel editor as a slice sheet. Alternatively, parse the `.vox` chunks into `vol[z, y, x]`, flipping y so the front faces +y. Then render with `stack.py` as usual.
