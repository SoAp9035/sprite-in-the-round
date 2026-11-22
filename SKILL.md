---
name: sprite-in-the-round
description: Build a static, rotatable 3D pixel-art model (voxel volume) from a sprite, a 4-view model sheet, a turnaround, a directional character sheet, or just a description, and export it as GLB and OBJ for any 3D tool or engine, or as sprite-stack slices and direction sheets for a 2D game. Use for "make this pixel art 3D", pixel art to GLB/OBJ, voxel props, vehicles and characters, sprite stacking, fake-3D pixel art, rotatable or turntable pixel art, and stacked slices.
compatibility: Helper scripts need Python 3.9+ with NumPy and Pillow. Grid recovery also uses SciPy and headless OpenCV. uv installs dependencies from the script headers. Best with an agent that can look at images.
metadata:
  technique-source: "references/sprite-stacking-guide.md"
  version: "2.7"
---

# Pixel art to a static 3D model

Build one coloured volume from the supplied art. Deliver its self-contained `.glb`, the same mesh as `.obj`, and a pixel preview. Design the hidden shape to suit the subject. A stack of horizontal slices is the editable intermediate and can also be drawn directly in a 2D game. Read the [local integration guide](references/sprite-stacking-guide.md) for the full sprite-stacking technique, standalone 4-view slicing, game-engine integration, and pixel-perfect rendering rules.

## Read the references in the image

- **Object model sheet.** Prefer matching orthographic top, side, front and back views at one pixel scale. Identify each by its features. The roof gives the footprint, the side gives height along its length, and the ends give width and paint at each height. Two or three views can be enough.
- **Character sheet.** Identify directions and poses by looking at the face, feet and equipment. Pick the same standing pose from the front, side and back. A right-side drawing is useful for asymmetric gear. Keep the feet on a common ground line. A ¾ game sprite includes some of the top of the head in its apparent height. Build it by parts as in `references/sculpt-a-character.md`; read `references/sheets-and-animation.md` for fitting game views.
- **One sprite.** Continue with it. Use visible features to infer depth, the top and the back. If more views would settle a specific ambiguity, explain which ones would help. When designing a missing view, read `references/making-views.md`.
- **No art, only a description.** Draw the views yourself as character grids (`references/making-views.md`) or build from primitives (`references/build-volume.md`).

## Keep one art pixel per voxel

Use clean native PNGs directly. For enlarged, blurry or screenshotted art, recover the grid before modelling. Crop editor UI and split sheets as needed.

```bash
uv run scripts/pixel_grid.py sheet.png -o art.png --split
uv run scripts/pixel_grid.py screenshot.png -o art.png --size 64x64
```

The second command assumes a known 64×64 canvas. Inspect `art_check.png` at an integer zoom. Check the eyes, outlines, single-pixel highlights and transparency. If the JSON lists `grid_candidates`, compare those sizes. For 2–4 views (including `1×4` and `2×2` model sheets), `--split` refines each view's grid on noisy sheets, peels backdrop halos, and gives each drawing a `view_guess` (top, side, front or back) from matching sizes; confirm it by the features before carving. Read `references/clean-input.md` when cleanup needs work. Keep a clean source palette. On damaged art, use repeated flat colours in the source as a reference when fixing a softened outline or highlight.

## Build the form

Write a small Python build script using `scripts/voxlib.py`. The volume uses `vol[z, y, x, rgba]`. The ground is at z = 0 and the front faces +y. A horizontal slice contains one layer of solid art pixels. See `references/build-volume.md` for coordinates, painting and worked examples.

| Available art | Starting point |
|---|---|
| Object with a top and side view | `stack_views(top=..., side=..., front=..., back=...)` strips 1-px view outlines, harmonizes the palette, carves, shades walls with cool-shifted bands, and returns `(vol, outline)`. Check nose and tail orientation. Add `rounded=True` when round parts are narrower than the widest part (a tower on a wide base), or they carve square. Use raw `carve(...)` when you want full manual control over outlines or shading. |
| Character with direction views | Sculpt it by parts (`references/sculpt-a-character.md`): `sculpt(vol, part_rows(...))` for each part, flat paint, and `decal` for the face and markings. Don't keep `carve`'s projected colours on a character: they speckle at 45°. |
| One round object | `lathe(front, wrap=60)`. Paint the cap or lid and keep labels on the front. |
| One character or irregular object | `inflate(front)`, or sculpt by parts with depths you choose. Paint the back and sides. |
| A flat emblem or top-down drawing | `extrude` for a thin object, or `heightmap` with distinct heights for a roof, cabin or other raised parts. |

Preserve interior linework. Where a silhouette outline becomes a dark stripe through the volume, `stack_views` (or `strip_outline`) strips it and stores the outline colour in the slice sheet so `stack.py` redraws it once around the silhouette. When drawing views or building from scratch, pick a clear tier — **15–20 slices** chunky retro, **26–44** detailed hi-bit, or **36–56** showcase — and shade with a **3-tone hue-shifted ramp** (cool deep shadow, saturated mid, warm highlight) with bold 2–4 px stripes. Keep intentional one-pixel features, such as antennae, in a GLB or OBJ. In a sprite stack, a 1-px post, rope or antenna vanishes at some turns, so make it 2 px thick there; `stack.py` warns about such parts. Cut openings after carving. Paint the face, markings and equipment only on the surfaces where they belong.

For example, from this skill directory, a build script beside prepared views can contain:

```python
# /// script
# dependencies = ["numpy", "pillow"]
# ///
import sys
sys.path.insert(0, "scripts")  # use the skill's absolute scripts path when building elsewhere
from voxlib import load, save_sheet, stack_views, trim

volume, outline = stack_views(top=load("top.png"), side=load("side.png"),
                              front=load("front.png"), back=load("back.png"))
save_sheet(trim(volume), "car_slices.png", outline=outline)
```

## Export and inspect

```bash
uv run build.py
uv run scripts/stack.py car_slices.png
```

For a single pose this writes `car.glb`, `car.obj` (with `car.mtl` and `car_palette.png`, which travel together) and `car_preview.png`. `stack.py` defaults to `--outline auto`, automatically restoring any outline colour saved by `save_sheet(..., outline=...)` in 2D previews, GIFs, direction sheets and viewers (pass `--outline none` to disable, or `--outline '#rrggbb'` to override; GLB/OBJ meshes never bake outlines). Read the `warnings` in the printed JSON. Front, side, back and top in the preview should agree with the artwork. At 45° and 135° the body should be clean: dark specks or stripes there mean a view paints where it doesn't face. Open the GLB in a 3D importer and inspect it from the front and the reverse angle. Check that the mesh stands upright, holes stay open, face details remain sharp, and the back has the intended paint. Fix the volume and export again if needed.

The GLB and OBJ hold the same mesh: solid, flat-coloured faces with a small palette texture. They use Y up, front +Z and 16 art pixels per metre, so a 38-layer character is 2.4 m tall: pass `--height 1.6` (metres) for a person-sized one, or one `--ppm` value across a set of props. The JSON reports `mesh_size_m`. The origin is at the centre of the slice footprint on the ground plane. Use the GLB where it is supported (Blender, Godot, Unity via glTFast, three.js, web viewers) and the OBJ for everything else. The PNG preview uses the sprite-stack camera, which draws one screen pixel per layer: its turned views look about 1.5 times taller than the mesh from the same angle. Judge proportions from the flat views in the preview's last row or in a 3D viewer, not from the turned views. For a standing character, preview with `--squash 0.4 --no-shadow`: the default 0.75 camera mostly shows the top of the head. The preview's optional outline and shadow are preview effects. For the stepped screen-pixel look in a 3D game, use an orthographic camera, render at the game's pixel resolution and enlarge the viewport by a whole number with nearest sampling.

## Common mistakes

- **Carved colours on a character.** `carve` paints each wall from the nearest drawing, so on a rounded body the front and side drawings interleave, and their soft pixels and linework show as specks at 45°. Sculpt characters by parts and paint them flat.
- **Thin parts.** 1-px parts are fine in the mesh but blink in a turning sprite stack.
- **Front details carried round.** `lathe`, `inflate` and other one-view builds take their colours from the front picture, so its highlights, eyes and labels also land on the sides, seen edge-on, and with `inflate` on the back. Look at the flat side and back in the preview's last row and at the 90° and 180° turns, and paint those details out where they don't belong.
- **Gaps inside a view.** Background fully enclosed by the drawing (between legs, ropes or fins) carves solid. Make it transparent, or cut it from the volume afterwards.
- **Things sticking out of a wall.** A small sign or flower box in the side view carves a ledge along that whole wall. Paint it flat on the wall or add it as a separate part.
- **Off-centre base.** The stack and the mesh origin use the middle of the bounding box, so a base that reaches further on one side makes the object orbit when turned. Centre the object, or pad the volume.
- **Views that disagree.** Check that the top length matches the side length and the side height matches the front height before carving. A view drawn at a different scale or perspective carves a wrong shape.
- **Stretched spheres in 2D sprite stacks.** An equal-radius voxel sphere (`R_z = R_xy`) looks round in GLB/OBJ, but stretches into a vertical egg under sprite-stack `squash` and `spacing`. For a 2D sprite-stack-only sphere, set `R_z = R_xy * sqrt(1 - squash²) / spacing`.

## Hand over

Hand over the GLB, OBJ and preview. Mention which views supplied the shape and what you inferred. If the requested asset is for a 2D sprite-stack renderer, deliver the slice sheet instead. Direction exports, the HTML viewer and engine conventions are in `references/render-and-ship.md`. For an explicitly requested animation, the existing slice-sheet workflow is in `references/sheets-and-animation.md`.
