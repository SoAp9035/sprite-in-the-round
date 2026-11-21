# Sprite stacking and pixel-perfect integration guide

Self-contained technical reference for building sprite-stacked fake-3D pixel art, slicing orthographic views, integrating live stacks or direction sheets into a 2D game, and configuring pixel-perfect rendering so stacked sprites stay crisp on whole pixels.

Adapted for agent execution from SpriteCook's sprite stacking, pixel-perfect rendering, sprite-stack generator, and top-down tileset guides. Run commands from the skill directory. Use this guide with the bundled scripts (`scripts/pixel_grid.py`, `scripts/voxlib.py`, `scripts/stack.py`).

## 1. Core technique and geometry

Sprite stacking represents a 3D pixel-art object as a sequence of flat top-down horizontal slices—one slice per pixel of height—stored in a single horizontal strip:

- **Sheet layout:** One row of `count` equal-sized `w × h` slices. Slice `0` (ground layer) is on the left; slice `count - 1` (top layer) is on the right. Each slice faces **down (`+y`)**.
- **Stacking:** Draw slice `0` first, then each subsequent slice `z` lifted upward on screen by `round(z * spacing)` pixels. Later slices overwrite earlier ones.
- **Turning:** Rotate every slice around its own centre by the same angle `turn` (using nearest-neighbour sampling) *before* squashing and lifting. One small sheet covers all 360°.
- **Camera angle (`squash`):** Vertically scale each rotated slice by `squash` before lifting it.
  - `1.0` leaves the footprint at full height. Set `spacing = 0` as well for a straight-down projection.
  - `0.75` gives a slightly angled top-down camera showing more of the sides and wheels.
  - Below `~0.6`, roofs thin out and gaps appear unless `spacing` is reduced or slices are thickened.
- **Sorting:** Always Y-sort whole stacks against other world objects by their ground contact point (`pos.y`), never slice by slice; interleaving slices of different objects puts one object's slices inside another.
- **Position snapping:** Keep stack ground positions on whole game pixels. Fractional positions cause slices to blur or shimmer.

### Numbers that matter

- **Spacing:** `1` screen pixel per slice at the game's base pixel resolution (`lift = round(z * spacing)`).
- **Squash:** `0.75` default for angled top-down games.
- **Heading and velocity:** Because slices face `+y` (down), an object moving with velocity `v` uses:
  - `turn = atan2(v.y, v.x) - PI / 2` (i.e. `- 90°`).
  - **Reversing vehicles:** Drive `turn` from the object's **heading**, not raw velocity, or reversing will flip the sprite 180° backwards.
- **Reference dimensions** for a solid box of `count` slices, each `w × h` px (no outline or shadow; irregular objects are smaller):
  - `squash = 1.0`, `turn = 0`: `w` wide, `h + count - 1` tall. A 15-slice `24 × 43` box is `24 × 57`.
  - `squash = 0.75`, `turn = 0`: about `0.75 h + count` tall (`24 × 47` for that box).
  - `turn = 90°`: `h` wide (the slice length).
  - `spacing = 2.0`: `h + 2 (count - 1)` tall (pulled apart).
  - `spacing = 0.0`, `squash = 1.0`: flat (every slice in the same place, top slice covering the rest).
  - Viewing scale: a whole number of screen pixels per art pixel (`10×` for a small demo), so rotation steps stay crisp.
- **Height and the 3D mesh:** an orthographic camera tilted so the footprint shrinks to `squash` would show each layer `sqrt(1 - squash²)` px tall, 0.66 at 0.75. Sprite stacking draws 1 px per layer instead, so stacks look about 1.5 times taller than the same volume exported as GLB/OBJ. Use `spacing = sqrt(1 - squash²)` when a stack must match the mesh.

## 2. Integrating sprite stacking into a game project

When asked to add sprite stacking to an existing game:

1. **Inspect the project first.** Before writing code, check:
   - Engine, version, and language.
   - How sprites and tilemaps are currently drawn and Y-sorted.
   - Base pixel resolution, window/viewport scaling, and camera zoom.
   - Which objects should rotate freely (cars, turrets, characters) vs. stay static (trees, buildings, props).
2. **Fit into the existing pipeline.** Reuse the project's resolution, camera, and sorting layer rather than introducing a second rendering system.
3. **Acquire art (cheapest option first).** If an object has no slice sheet yet, select a source consistent with the requested asset:
   1. **Existing voxel model:** Export horizontal layers as a slice sheet from a voxel editor (such as MagicaVoxel `.vox`). Best when the object has complex holes, interiors, or overhangs.
   2. **Build/carve from views with this skill:** Use `scripts/pixel_grid.py` + `scripts/voxlib.py` + `scripts/stack.py` to carve from orthographic views (`top`, `side`, `front`, `back`), `lathe` round props (`top` + `side`, or `side` alone), or assemble from primitives (`references/build-volume.md`).
   3. **Draw or generate missing views:** Draw compact views as character grids (`references/making-views.md`), or—if an image-generation tool/MCP is available in the session—generate a 2×2 orthographic model sheet and clean it with `scripts/pixel_grid.py --split`.

## 3. Authoring and generating four orthographic views

### Layout and art rules

For boxy objects (cars, trucks, tanks, crates, chests, buildings), four strictly orthographic views at one shared scale produce clean slices:

- **Top view:** looking straight down, front pointing **down**. Its length equals the side view's length and its width equals the front view's width.
- **Side view:** profile facing **left**. Its height equals the front view's height. Identify views by these matching sizes and their features, not by aspect: a tree's side view is the tallest drawing. If drawn facing right, flip horizontally or pass `side_nose="right"`.
- **Front view:** facing the viewer.
- **Back view:** rear details (tail lights, exhaust, back of head), not a duplicate of the front.
- **Round objects** (trees, towers, barrels, pots, bottles): only a **top view** and **one side view** are needed (`lathe(side, top=top)`).

Use **bold 1 px dark outlines and solid flat fills** with stripes several pixels wide. Avoid asking an image generator for "flat colours with no outlines": without an outline anchor, generators tend to produce soft grey anti-aliased edges that smear once slices rotate and overlap.

### Tested 1×4 / 2×2 orthographic model-sheet prompt

Keep the layout and shading sentences intact and replace the subject description:

```text
Chunky pixel art orthographic model sheet of {subject description, e.g., one small blue 90s sports race car with a white center stripe, low and wide, dark windows, black tires} with rich 3-tone hue-shifted pixel shading (deep cool-shifted shadows, saturated midtones, bright warm top highlights along ridges and edges), bold 3-4px stripes/accents, and crisp specular pixels on glass. Four views in a clean 1x4 horizontal row (or 2x2 grid) on a completely flat solid white or pale gray background:
1. TOP view looking straight down at the roof, object pointing DOWN.
2. SIDE view, object pointing LEFT.
3. FRONT view.
4. BACK view.
Strictly orthographic: zero perspective, zero tilt, zero 3/4 angle. Identical scale across all four views so length, width, and height match pixel for pixel. Bold 1px dark outline around each view, solid flat color clusters, crisp internal panel shading, zero anti-aliasing, zero soft edges, zero cast ground shadows, zero grid lines, zero text, zero labels, generous empty space between views. Low-resolution chunky pixel art, each view about 36 pixels.
```

### When an AI sprite-generation tool/MCP is available

- Target pixel-art mode at roughly `32 × 32` per view (the reference car was generated with `gemini-3-pro-image` / Nano Banana Pro in pixel-art mode).
- When generating a full set of props or vehicles for one game, generate **one hero asset first** and pass it as a style/palette reference for the remaining objects so colour ramps, outline weight, and proportions stay consistent.
- Always recover the native grid with `uv run scripts/pixel_grid.py sheet.png -o views.png --split` before carving; generated images rarely sit on an exact 1:1 pixel grid.
- Inspect the extracted views before slicing: verify no perspective tilt (no roof visible in side view, no side wall visible in front view), verify matching length/width/height across views, and confirm the side view faces left.

## 4. Slicing from four orthographic views

### How visual-hull carving works

1. Inspect the numbered PNGs and the `drawings` row/column entries from `--split`. For the layout above, take top and side from the first row, front and back from the second. Check visible landmarks before assigning names. Relative sizes alone can misidentify a short, wide object.
2. Start with transparent RGBA views, threshold alpha at 128 and crop each view to its opaque bounds. If the silhouette has a dark border that would streak through the stack, use `strip_outline` selectively. Use `shared_palette` when the views need colour matching.
3. Use the top view to set footprint length and width. Scale the side proportionally to that length and fit the ends to the resulting width and height using nearest sampling. With the nose down in the top view, increasing volume y runs toward the nose. Reverse the columns of the left-facing side and the rear view to align them with y and x respectively.
4. At each height, intersect the top footprint with the corresponding side row and the union of the front and aligned rear rows. Use the bottom image row for ground level. Start with top-view colour throughout. Under a higher voxel, colour walls within two pixels of open air from the nearest face. The interior keeps its top colour. Apply optional shading after carving.

### Generate and inspect a stack locally

Save this as `build.py` in the skill directory with the four cleaned PNGs named as below. The bundled builder also supports partial views, a second side, rounded sections and aligned animation cells.

```python
# /// script
# dependencies = ["numpy", "pillow"]
# ///
import sys
sys.path.insert(0, "scripts")
from voxlib import load, save_sheet, stack_views, trim

top, side, front, back = (load(name + ".png") for name in ("top", "side", "front", "back"))
volume, outline = stack_views(top=top, side=side, front=front, back=back)
save_sheet(trim(volume), "object_slices.png", outline=outline)
```

```bash
uv run build.py
uv run scripts/stack.py object_slices.png --viewer --dirs 16
```

Compare the preview's flat views with the originals, especially the nose and any off-centre rear markings. Open `object_viewer.html` to inspect the rotation and layer spacing. Use `object_slices.png` for live stacking or `object_dirs16.png` for baked directions.

### Standalone four-view reference

For a port without the skill scripts, this function takes four tightly cropped uint8 RGBA arrays with binary alpha, oriented as drawn above. It returns the same ground-first volume layout as the bundled four-view carve with default settings. The bundled `carve` also gives a 1-px ledge under a narrower part (a cabin roof) the colour of that part, so the two can differ on such ledges.

```python
import numpy as np
from PIL import Image

def fit(view, width, height):
    return np.array(Image.fromarray(view).resize((width, height), Image.Resampling.NEAREST))

def wall_row(layer, y, x, side, front, back):
    length, width = layer.shape
    # Distance first, then carve's tie order for equally close faces.
    for step in (1, 2):
        for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            ny, nx = y + dy * step, x + dx * step
            if 0 <= ny < length and 0 <= nx < width and layer[ny, nx]:
                continue
            if dx:
                return side, y
            near, far = (front, back) if dy > 0 else (back, front)
            return (near if near[:, 3].any() else far), x
    return None

def views_to_slices(top, side, front, back):
    length, width = top.shape[:2]
    height = max(1, round(side.shape[0] * length / side.shape[1]))
    side = fit(side, length, height)[::-1, ::-1]  # z, y
    front = fit(front, width, height)[::-1]       # z, x
    back = fit(back, width, height)[::-1, ::-1]   # z, x

    footprint = top[..., 3] > 0
    profile = side[..., 3] > 0
    ends = (front[..., 3] > 0) | (back[..., 3] > 0)
    solid = footprint[None] & profile[:, :, None] & ends[:, None, :]
    volume = np.zeros((*solid.shape, 4), dtype=np.uint8)
    covered = np.zeros_like(footprint)
    for z in reversed(range(height)):
        layer = solid[z]
        volume[z, layer] = top[layer]
        for y, x in zip(*np.nonzero(layer & covered)):
            sample = wall_row(layer, y, x, side[z], front[z], back[z])
            if sample is not None:
                row, index = sample
                opaque = np.flatnonzero(row[:, 3])
                volume[z, y, x] = row[opaque[np.abs(opaque - index).argmin()]]
        covered |= layer
    return volume
```

To pack the result manually, save `Image.fromarray(np.concatenate(volume, axis=1))` as a PNG. Pass `--count` with `volume.shape[0]` to `stack.py` when reading this metadata-free sheet.

## 5. Rendering in a game engine

Choose between **live slice stacking** (smooth any-angle rotation, dynamic `squash`/`spacing`, 1 draw call per slice) and **baked direction sheets** (`stack.py --dirs N`: ordinary sprite sheet, zero stacking code, best for uniform pixel outlines or low draw-call budgets).

- **8 directions:** slow props, buildings, fixed orientations.
- **16–32 directions:** smoothly steering vehicles or characters without live stacking.
- **Static stacks (trees, rocks, crates):** render once at load time into an offscreen texture and draw as a plain sprite.

### Universal pseudocode (live stack)

```text
# sheet: one row of `count` slices, each w x h px, ground slice first
# pos: where the object's centre touches the ground, in whole screen px
function draw_stack(sheet, count, pos, turn, squash = 0.75, spacing = 1.0):
    w = sheet.width / count
    h = sheet.height
    rect = (-w / 2.0, -h / 2.0, w, h)          # slice drawn around its centre
    for z in 0 .. count - 1:
        transform = translate(pos)
                  * translate(0, -round(z * spacing))     # lift
                  * scale(1, squash)                      # camera height
                  * rotate(turn)                          # same turn for every slice
        draw_region(sheet, source = (z * w, 0, w, h), dest = rect, transform, filter = NEAREST)

# every frame, for each turning object:
if velocity != (0, 0): turn = atan2(velocity.y, velocity.x) - PI / 2
# A vehicle with an independent heading always uses turn = heading - PI / 2.
draw objects sorted by pos.y (ground point), each with draw_stack
```

For animated slice sheets (one row per animation frame), set `h = sheet.height / frames` and change the source rectangle to `(z * w, frame * h, w, h)`.

### Godot 4

Live slice stack (`Node2D`):

```gdscript
extends Node2D
## Sprite stacking: draws a row of flat slices on top of each other so they look like one 3D object.
## The sheet is one row of slices, the ground slice on the left. Keep the node on whole pixels.

@export var sheet: Texture2D
@export var slices := 15                    ## how many slices the sheet holds
@export var turn := 0.0                     ## radians; 0 draws the slices as they are in the sheet
@export_range(0.1, 1.0) var squash := 0.75  ## 1 leaves the footprint uncompressed
@export var spacing := 1.0                  ## screen px between one slice and the next

func _process(_delta: float) -> void:
	queue_redraw()

func _draw() -> void:
	if sheet == null or slices <= 0 or sheet.get_width() % slices != 0:
		return
	var w := float(sheet.get_width()) / slices
	var h := float(sheet.get_height())
	var rect := Rect2(-w / 2.0, -h / 2.0, w, h)
	var spin := Transform2D(turn, Vector2.ZERO)
	for z in slices:
		# turn the slice on the ground, flatten it for the camera, then lift it z slices up
		var lift := Transform2D(Vector2(1, 0), Vector2(0, squash), Vector2(0, -roundf(z * spacing)))
		draw_set_transform_matrix(lift * spin)
		draw_texture_rect_region(sheet, rect, Rect2(z * w, 0, w, h))
```

Single-pose baked direction sheet (`Sprite2D`, 8 frames per row, frame 0 facing right clockwise):

```gdscript
extends Sprite2D
## Shows the frame of a direction sheet that faces the way the object moves.
## Frame 0 faces right, then each frame turns clockwise, 8 frames per row.

@export var directions := 16

func _ready() -> void:
	hframes = mini(directions, 8)
	vframes = ceili(directions / 8.0)

func face(angle: float) -> void:
	# angle in radians, for example velocity.angle() or heading
	frame = posmod(roundi(angle / TAU * directions), directions)
```

For an animated direction export with F frames and N directions, use F columns and N rows. Set `frame = facing * F + anim_frame`.

For a single clean outline around a live Godot stack, render the stack into a `SubViewport` and apply a 4-neighbour outline shader to the viewport texture (or bake `--outline '#1a1c2c'` into a direction sheet).

### Other engines

- **Unity:** Either use a `SortingGroup` per object with ascending child `sortingOrder` (spin each slice around its centre, apply vertical squash in the parent axes, then lift by `round(z * spacing) / PPU` world units), or render all slices into a `RenderTexture` with point filtering and draw the composite once.
- **Web / HTML5 Canvas:** Render the game into an off-screen canvas at the base resolution with `ctx.imageSmoothingEnabled = false`, then set `imageSmoothingEnabled = false` on the destination context before the integer-scale blit. Use CSS `image-rendering: pixelated` if the canvas is also enlarged by CSS.
- **Phaser, Pygame, LÖVE, GameMaker, custom engines:** Loop `z = 0 .. count - 1`, rotating each slice around its centre with nearest-neighbour filtering, scaling Y by `squash`, and offsetting Y by `-round(z * spacing)`.

### Build a top-down ground tileset

Choose a tile side T in base-resolution pixels, usually 16 or 32. Draw or generate a single terrain material as a 15-piece corner autotile atlas on a 4 × 4 grid. For example, a 16 px tile uses a 64 × 64 px PNG. Keep the ground texture at the same pixel density as the object slices.

Import the PNG as an atlas with T × T cells. In the terrain rules, label each piece by which of its four corners contain ground. Four binary corners give 16 patterns. Map the 15 nonempty patterns to the matching artwork and leave the all-empty pattern blank. Use the artwork to identify each cell's pattern rather than assuming an atlas order. Paint a straight border, a bend, a hole and a small island to inspect the joins. Draw ground first, then Y-sort the stacks above it.

## 6. Pixel-perfect rendering setup

Sprite stacking depends on crisp, uniform pixels. When a game project renders pixel art incorrectly, it fails in three ways:

1. **Blurry:** Linear texture filtering, mipmaps, or lossy compression blend adjacent pixels.
2. **Lumpy:** Fractional window scaling (e.g. `352 px` stretched to `1920 px` = `5.45×`) or fractional camera zoom produces uneven 5- and 6-pixel-wide columns that crawl when the camera moves.
3. **Pasted together (mixels):** Sprites, tiles, particles, or UI drawn at different scales (e.g. a `2×` sprite or `2×` HUD over a `1×` tilemap) break pixel uniformity.

### The eight rules (and how sprite stacking fits them)

1. **Texture filter Nearest everywhere.** Disable mipmaps and lossy compression on all sprites and slice sheets.
2. **One base resolution, scaled by whole numbers only.** Fill leftover window area with black bars (or reveal slightly more world, never non-integer stretch).
3. **Snap camera and sprite/stack positions to whole game pixels** when drawing.
4. **One pixel size for everything.** Draw every sprite, tile, ground track, particle, and UI element at `1×` scale (negative flips `-1` are fine). Keep top-down ground tilesets (e.g., 16 px or 32 px 15-piece 4×4 autotile atlases) at the exact same pixel density as the stacked objects.
5. **No arbitrary runtime rotation of ordinary 2D pixel art** (only 90° steps or pre-drawn rotations)—*except* for sprite-stacked layers drawn inside the base-resolution viewport with nearest sampling, or baked direction sheets which avoid runtime rotation entirely.
6. **Pixel fonts at native size** with antialiasing disabled.
7. **Particles and effects on the same pixel grid** as sprites.
8. **Audit new assets for native pixel size** before importing.

### Base resolutions and integer scaling math

Choose a base resolution that divides common 16:9 monitors cleanly:

- **`384 × 216`:** exact `5×` on 1080p, exact `10×` on 4K, `6×` with `(128, 72)` px bars on 1440p, `3×` with `(107, 60)` px bars on `1366 × 768`.
- **`320 × 180`:** exact `6×` on 1080p, exact `8×` on 1440p, exact `12×` on 4K.

```python
def integer_scale(window_w, window_h, base_w, base_h):
    """Return (scale, left, top), or None if even 1x does not fit. Base sizes are positive."""
    scale = min(window_w // base_w, window_h // base_h)
    if scale < 1:
        return None
    return scale, (window_w - base_w * scale) // 2, (window_h - base_h * scale) // 2
```

If the function returns `None`, enforce a minimum window size or select a smaller base resolution. If the leftover width or height is odd, the right or bottom bar takes the extra pixel.

### Engine settings

**Godot 4 (`project.godot`, 4.2+):**

```ini
[display]

window/size/viewport_width=384
window/size/viewport_height=216
window/size/window_width_override=1920
window/size/window_height_override=1080
window/stretch/mode="viewport"
window/stretch/scale_mode="integer"

[rendering]

textures/canvas_textures/default_texture_filter=0
2d/snap/snap_2d_transforms_to_pixel=true
2d/snap/snap_2d_vertices_to_pixel=false
```

On import in Godot: set sprite textures to **Compress Mode: Lossless** and fonts to **Antialiasing: None**.

**Unity:**
- Per sprite: **Filter Mode: Point (no filter)**, **Compression: None**, **Generate Mip Maps: Off**, identical **Pixels Per Unit (PPU)** on every sprite and tileset.
- Camera: attach a **Pixel Perfect Camera** configured to the base resolution and matching PPU.
- Quality / URP: disable **Anti-aliasing**.

**Custom engine / web:**
- Render the entire scene (including stacked sprites and UI) into an off-screen render target of size `(base_w, base_h)`.
- Draw that target once onto the window at `(bar_x, bar_y)` scaled by `scale` with nearest sampling.

### Checking asset pixel size and auditing scenes

- **Native pixel size check:** A candidate integer block size is the GCD of all contiguous equal-colour pixel run lengths across every row and column (regular patterns can overestimate the original block size). Note that AI-generated or resampled art lacks a clean grid and will return `1` even when pixels look oversized—flag such files and recover their true grid with `scripts/pixel_grid.py` rather than resizing blindly.
- **Scene audit (Godot 4 `PixelAudit`):** Walk the scene tree at runtime and flag:
  - Project settings: default texture filter != Nearest, stretch mode != `viewport`, stretch scale mode != `integer`, or transform snapping off when relying on it for pixel alignment.
  - Any `CanvasItem` whose local `texture_filter` overrides Nearest (e.g. manually set to Linear).
  - Any `Sprite2D`, `AnimatedSprite2D`, or `TileMapLayer` whose `global_scale.abs()` is not `Vector2.ONE` (catches sprites scaled via a parent node, while allowing `-1` flips).
  - Any non-stacked sprite rotated by an angle not a multiple of 90° (exempt live stack nodes that perform per-slice drawing).
  - Any `Camera2D` whose `zoom` is not a whole number.
  - Any `Label` whose font is not a `FontFile` with `FONT_ANTIALIASING_NONE`.

## 7. Common pitfalls

| Pitfall | Cause | Fix |
|---|---|---|
| **Jitter on slow turns** | Nearest-neighbour rotation shifts pixels in discrete jumps, obvious on tiny sprites. | Compare baked directions or author more pixels of detail at the target art scale. Integer display zoom magnifies the same jumps. Optionally test RotSprite (scale slice `8×` via 3× Scale2x, rotate, sample centre pixel of each `8×8` block), but compare against nearest-neighbour—RotSprite rounds off small sprites. |
| **Blurry / smeared stack** | Soft anti-aliased edges, mid-tone gradients, or 1 px stripes in the source views. | Use bold 1 px outlines (stripped before slicing), flat colour fills, and stripes at least 2–3 px wide. |
| **Dark speckle inside the body** | Outlines drawn per slice or left baked into the slice sheet show through on diagonal angles. | Strip outlines before building slices; outline the finished stack once via offscreen buffer/`SubViewport` or baked direction sheet (`stack.py --outline '#1a1c2c'`). |
| **Filled-in holes or overhangs** | Orthographic 4-view intersection cannot represent concavities (truck beds, arches, space under a spoiler). | Carve or erase those voxels/slices manually (`paint(..., None)` in `voxlib.py`) or author in MagicaVoxel. |
| **Interleaving slices between objects** | Sorting slices individually across objects. | Sort whole stacks by their ground contact `pos.y`. |
| **High draw-call cost for scenery** | Hundreds of static trees/rocks each issuing `count` draw calls per frame. | Pre-render static stacks once at load time into plain textures. |
| **Shimmering / crawling pixels** | Fractional positions, fractional camera zoom, or non-integer window stretch. | Snap positions to whole game pixels; enforce integer viewport scaling and whole-number camera zoom. |
| **Hidden mixels or blurry nodes** | A node manually set to Linear, a scaled parent node, or a `2×` HUD over a `1×` scene. | Audit `global_scale`, per-node texture filters, and draw UI at the base resolution. |
| **Car flips backwards in reverse** | Computing `turn` from velocity vector instead of vehicle heading. | Use heading angle (`heading - PI / 2`) for turning vehicles. |

## 8. Verification checklist

Run these checks when implementing sprite stacking or pixel-perfect rendering in a game:

### Sprite stacking checks

For dimension checks, use identical fully opaque rectangular slices, measure the alpha bounds, and disable outline and shadow. Irregular silhouettes can occupy less space.
- `squash = 1.0`, `turn = 0`: width equals one slice width; height equals slice height + `(count - 1)` px.
- `squash = 1.0`, `turn = 0` pixel-exact check: drawn pixels match pasting slices manually 1 px above each other. Automate via frame readback if the engine supports it; otherwise add a temporary debug key cycling `turn`, `squash`, and `spacing`.
- `squash = 0.75`: visibly shorter than `squash = 1.0`; at `turn = 90°`, width equals slice length (`h`).
- `spacing = 2.0`: taller than `spacing = 1.0` for a multi-layer test stack.
- `spacing = 0.0`, `squash = 1.0`: renders completely flat (all slices stacked on the same position, top slice over the rest).
- Circular motion test: driving in a circle keeps the nose aligned with motion; reversing keeps the nose pointing along heading without flipping 180°.

### Pixel-perfect checks
- `integer_scale(1920, 1080, 384, 216)` -> `(5, 0, 0)`; `(2560, 1440, 384, 216)` -> `(6, 128, 72)`; `(1366, 768, 384, 216)` -> `(3, 107, 60)`; `(300, 200, 384, 216)` -> `None` (enforce a minimum window size or choose a smaller base).
- Non-multiple window screenshot: every game pixel covers the exact same whole number of screen pixels with black bars filling the remainder; zoomed-in edges show zero blended intermediate colours.
- Scene audit catches: scale-2 sprite, sprite under a scale-1.5 parent, non-90° rotated regular sprite, node with Linear filter, camera at zoom `1.5`, and antialiased label font—while passing flipped sprites (`-1`), 270° rotated sprites, integer camera zoom (`2`), and unantialiased pixel fonts.
