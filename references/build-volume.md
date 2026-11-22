# Building the volume

You are making a small voxel model. Shape is decided by the silhouettes you have, plus your knowledge of the object. Colour comes from the art. Expect to combine methods and then paint and fix by hand. That last step is where results go from "inflated sticker" to "looks like a real little 3D object".

## Conventions and toolbox

`vol[z, y, x, 4]` is a uint8 RGBA array, so `vol.shape` is `(H, D, W, 4)` (use `H, D, W = vol.shape[:3]`):
- z = 0 is the ground;
- +y is the object's **front** (down in a slice);
- x runs left→right as you look at the front.

Views are RGBA pictures as drawn, with row 0 at the top. `save_sheet(vol, path)` writes the slice sheet; `save_sheet([vol0, vol1, ...], path)` writes an animation, one row per frame.

```python
# /// script
# dependencies = ["numpy", "pillow"]
# ///
import sys; sys.path.insert(0, "/path/to/sprite-in-the-round/scripts")
import numpy as np
from voxlib import *

front, outline = strip_outline(crop(load("art.png")))   # outline: rgb to pass to stack.py --outline
vol = lathe(front)                                        # or carve / inflate / extrude / heightmap / primitives
vol = shade(vol, 0.25)                                    # darker walls near the ground, in flat steps
save_sheet(trim(vol), "obj_slices.png")
print(trim(vol).shape)                                    # (H, D, W, 4); stack.py reads H from the sheet
```

Run it with `uv run build.py`; the header makes uv install numpy and Pillow. Without uv, `pip install numpy pillow` and `python3 build.py`. For a quick one-off command: `uv run --with numpy --with pillow python -c "..."`.

| function | does |
|---|---|
| `load(path)`, `save(img, path)`, `save_sheet(vol_or_frames, path, outline=None)`, `load_sheet(path, count=None, frames=None)` | file I/O, hard alpha; a list of volumes is an animation; `outline=` stores the silhouette outline colour for `stack.py --outline auto`; `load_sheet` reads the slice and frame counts `save_sheet` stored |
| `crop(img)`, `fit(img, w, h)`, `hexrgb(s)`, `rgbhex(rgb)` | tight crop; nearest-neighbour resize; colour conversions |
| `strip_outline(img, colour=None)` | → `(img, outline_rgb)`, with the silhouette outline recoloured from inside. Finds dark outlines; pass `colour=` for a light one. |
| `strip_edge(img, width, colours=None)` | → `(img, rim_rgb)`, with the band at both ends of every row recoloured from inside: rim light, glass edges, backdrop seen at the sides |
| `shared_palette([imgs], n)` | one palette of n colours for all views |
| `near(img_or_vol, colours, tol=24)` | mask of pixels/voxels close to any of the colours: remove a drawn shadow, recolour a part |
| `show(img_or_slice)` | text dump: one letter per colour, `.` = empty. Use it to read exact coordinates. |
| `stack_views(...)` | batteries-included 2–5 view pipeline (`strip_outline` → `shared_palette` → `carve` → cool-shifted `shade`) → `(vol, outline_hex)` |
| `carve`, `lathe`, `inflate`, `extrude`, `heightmap`, `dome` | shape methods, below |
| `part_rows(vol, front, side, z=, x=, y=)`, `sculpt(vol, rows, power)` | a part's size per layer from two views; the rounded part as a mask |
| `facing(mask, side, depth)`, `decal(vol, view, where, side, colours=, flat=)` | the surface of a part seen from one side; paint a view's features there only |
| `blank(H, D, W)`, `coords(vol)`, `paint(vol, mask, colour)`, `place(dst, src, z, y, x)` | build and edit with boolean masks |
| `exposed_top(vol)` | mask of voxels seen from straight above |
| `shade(vol, amount, bands, cool)`, `trim(vol)` | finishing (cool-shifted banded wall shading by default); `trim([frames])` crops all frames by one box |

Every function is a few lines. Read it, copy it into your script and change it when it doesn't do what this object needs.

## Carve from views (objects)

A voxel exists where **all** views have a pixel. Each row of the side view becomes one slice: the top view, cut to the length the side view has at that height and to the width the front/back views have at that height.

Colours come from the view that faces each voxel:
- top surfaces take the top view;
- the `wall` px (2) next to open air, under something higher, take the side view (left/right walls), the front view (+y) or the back view (−y), from the same row;
- a 1-px step lip beside a higher layer takes the facing view too, when that view was drawn. Slopes that rise a layer per pixel (a nose, a windscreen, a cabin one pixel narrower at the roof) are walls, not tops: from the top view they get a second row of headlights or a ring of body colour. Gentler slopes (a hood) keep the top view;
- hidden voxels under a higher one continue its colour, because a turned stack shows a pixel or two of each layer behind the one above.

```python
top, side, front, back = (load(f"views_{i}.png") for i in (1, 2, 3, 4))
vol, outline = stack_views(top=top, side=side, front=front, back=back)  # side_nose="right" / top_nose="up" if needed
save_sheet(trim(vol), "obj_slices.png", outline=outline)                # stack.py restores the 1-px outline automatically
```

`stack_views` runs `strip_outline`, `shared_palette(..., 32)`, `carve`, and `shade(..., 0.2, cool=0.25)` in one call (pass `colors=0` to keep every colour, `shade_amount=0` to skip wall shading, or call `carve(...)` directly for custom control).

- **Scale.** Height = side height × top length ÷ side length. The front and back are scaled to the top view's width and that height.
- **Top and side only.** The width at every height becomes the top view's width. That suits vertical walls (crates, houses); for round things use `lathe(side, top=top)`.
- **No top view.** `carve(side=..., front=..., back=...)` takes the width from the front/back and the depth from the side. The views keep their own size and stand on one ground line, so they must share a scale (sprite-sheet directions do). `rounded=True` makes each layer an ellipse inside that box: creatures and other organic shapes. Tops take the side view's colour, so repaint them where that's wrong. For a character, sculpt by parts instead (below): carved walls mix the front and side drawings and speckle at 45°.
- **Both sides.** `side2=` is the other side as drawn (nose pointing the other way). Without it, the far side repeats the near one mirrored.
- **Cells from one sheet.** `aligned=True` uses views exactly as given, uncropped and unscaled, so animation frames carved one by one line up (see `sheets-and-animation.md`).
- **Orientation check.** The tall part of the side view (cabin, roof) must sit over the matching part of the top view (windows, roof). If row 3 of the preview shows the roof at the wrong end, use `top_nose="up"`.
- **After carving, cut what views can't express.** Truck beds, arches, gaps under a spoiler, handles and the space between legs all come out solid (see "Paint and fix").

## Sculpt by parts: characters

Shape each part (head, body, arms, legs) from its band of the front and side views, paint it flat, and put the face and markings only on the surface that faces their view:

```python
rows = lambda **r: part_rows(vol, front, side, **r)       # vol = blank(tallest view, side width, front width)
Z, Y, X = coords(vol)
head = sculpt(vol, rows(z=(23, 38)), power=2.2)
paint(vol, head, "#48604d")
decal(vol, front, head & (Z <= 29), "front", colours=["#f5f2cb"], flat="#f8deae", depth=2)   # the face
```

The full recipe and a worked example are in `sculpt-a-character.md`.

## Lathe: round objects from one view

Each layer becomes a disc, or a ring, at the radii the view covers at that height. Pots, vases, bottles, jars, trees, towers, lamps, barrels, mushrooms, chess pieces.

```python
vol = lathe(view)                  # the picture wraps all the way round: leaves, bark, staves
vol = lathe(view, wrap=60)         # the picture only on the front 60°; elsewhere the edge colour of each row
vol = lathe(view, sides=view)      # a pattern all round (cookies in a jar, bricks): no stretched stripe at 90°
vol = lathe(side, top=top_view)    # top surfaces coloured from a top view (spots on a cap, a tree crown)
vol = lathe(view, top="#d5b2ff")   # ... or one colour (a lid, the soil in a pot)
vol = lathe(view, axis=11.5)       # an off-centre axis, in columns of the cropped view
```

**Why the sides need care.** Each column of the view colours a whole chord of the disc, straight through from front to back. The chord at the edge is about √radius voxels deep (11 for a 58-px jar), so the view's last 2–3 columns become a stripe 15–25 px wide when the object is seen from the side. Whatever the artist painted there shows up big: a rim highlight, a glass edge, a light outline, the backdrop showing through glass.

1. **Strip edge bands before lathing.** A light outline goes with `strip_outline(view, colour=...)`. Bands just inside it go with `strip_edge`, which recolours them from inside:
   ```python
   view, rim = strip_outline(view, colour="#a2c3df")                  # the glass's light outline
   view[26:], _ = strip_edge(view[26:], 5, ["#d5b2ff", "#5d2269"])    # body rows only: glass edge + backdrop
   ```
   Each listed colour also catches shades within `tol` (24) of it; raise `tol` to catch a family of shades with one entry. Then give the rim back as the outline of the finished stack (`--outline '#a2c3df'`): it reads as the glass edge from every angle.
2. **For a pattern all round, pass `sides=`.** Walls within 30° of each side then take their colour from that picture: a side view (front to the left), or the view itself for a pattern that looks the same from everywhere. To keep front-only details (highlight streaks, a label) off the sides, pass a copy of the view with them painted out.
3. **Look at the 90° turn and the flat side view** in the preview. A uniform vertical stripe or horizontal streaks there mean an edge band is still being stretched.

More rules:
- **Top surfaces** default to the view's colour at that radius in the topmost row, which is often a highlight or outline: a lid turns into a pale disc. Pass `top=` (a top view or a colour), or paint `exposed_top(vol)`.
- **Off-centre features** (a handle, a spout, a face) become rings. Build them as separate parts and `place` them; front-only details belong under `wrap=60`.
- **Lying objects** (a barrel on its side, a log): lathe, then rotate the volume, e.g. `np.rot90(vol, 1, axes=(0, 1))`. Check the preview to confirm the direction.

## Inflate: characters, creatures and organic shapes from one front view

Each pixel gets a thickness that grows with its distance from the silhouette edge (a pillow profile). Thin parts stay thin; the middle is thickest.

```python
vol = inflate(front, depth=10)     # depth = thickest point; for characters about 0.5–0.7 × width
```

The front picture goes straight through, so the back half (`y < vol.shape[1] // 2`) shows it mirrored. **Always repaint the back.** Decide what each part looks like from behind:
- back of the head: hair, hood or helmet;
- back of the body: clothes, a cape or a shell;
- no face, no buttons, no belt buckle;
- items held in one hand still belong to that hand.

```python
Z, Y, X = coords(vol)
solid = vol[..., 3] > 0
back = solid & (Y < vol.shape[1] // 2)
head = Z >= 14                                 # rows from show() / the art
paint(vol, back & head, "#5b3a29")             # hair all over the back of the head
paint(vol, back & ~head, "#3f5f9f")            # tunic colour on the back of the body
```

For better shapes, inflate parts separately and `place` them: head, body, each arm. Or sculpt by parts with depths you choose (`sculpt-a-character.md`), or draw a side silhouette and `carve(top=..., side=..., front=...)`, using a top view you design from the front view's widths.

## Extrude: flat objects

```python
vol = extrude(front, 2)            # signs, coins, cards, doors, leaves, blades
```

Edges show the front's colours; `shade` darkens them. Give a coin or a door frame a raised rim: extrude it by 1 more and `place` it.

## Height map: one top-down sprite

```python
top, outline = strip_outline(crop(load("car_top.png")))
a = top[..., 3] > 0
h = dome(a, 4)                                         # rounded body, 1..4 high
glass = (np.abs(top[..., :3].astype(int) - hexrgb("#2b2d42")).max(-1) < 30) & a
h[glass] += 3                                          # cabin stands taller
vol = shade(heightmap(top, h), 0.25)
```

Heights can come from colour regions (roof vs wall vs ground clutter), from `dome`, or from your reading of the object. `heightmap` colours each column with the top colour all the way down. Repaint the walls if they need different materials (a brick house with a tiled roof).

## Primitives: from a description, or parts no view shows

```python
vol = blank(16, 15, 15)                                # H, D, W
Z, Y, X = coords(vol)
paint(vol, ((X - 7) ** 2 + (Y - 7) ** 2 <= 2) & (Z < 7), "#6b4226")             # trunk
crown = (X - 7) ** 2 + (Y - 7) ** 2 + ((Z - 10) * 1.3) ** 2 <= 36
paint(vol, crown, "#3e8948")
paint(vol, crown & ((X + Y + Z) % 7 == 0), "#63c74d")                             # leaf flecks
vol = shade(trim(vol), 0.3)
```

Boxes, cylinders (`(X-cx)**2 + (Y-cy)**2 <= r*r`), spheres, cones (radius shrinking with Z) and their unions and differences cover most props. Wheels are short cylinders lying along x: `(Y-cy)**2 + (Z-cz)**2 <= r*r` with `x0 <= X < x1`.

## Compose parts

```python
pot = lathe(pot_view)                                  # both views already outline-stripped
plant = inflate(plant_view, depth=6)
H = pot.shape[0] + plant.shape[0]
scene = blank(H, max(pot.shape[1], plant.shape[1]), max(pot.shape[2], plant.shape[2]))
place(scene, pot, z=0, y=(scene.shape[1] - pot.shape[1]) // 2, x=(scene.shape[2] - pot.shape[2]) // 2)
place(scene, plant, z=pot.shape[0] - 2, y=(scene.shape[1] - plant.shape[1]) // 2,
      x=(scene.shape[2] - plant.shape[2]) // 2)       # sink it 2 layers into the soil
vol = shade(trim(scene), 0.25)
```

## Glass and other see-through parts

Alpha is 0 or 255, so nothing is truly see-through. Make glass an opaque shell that shows what's inside:
- Recolour the backdrop seen through the glass in the source art (it is usually the original background colour inside the silhouette) as the contents or a darker interior, before building.
- Keep the contents' colours and add the glass on top: a few light highlight streaks on the front (`wrap=60` or a `Y > ...` mask), and the glass's edge colour as the render outline.
- An empty bottle or window: paint the glass one light tint with a darker band near the bottom, and let the outline carry the edge.

## Paint and fix

- **Read before you edit.** `print(show(vol[z]))` prints one layer and `print(show(front))` prints a view, so masks hit the right pixels.
- **Cut holes and overhangs:** `paint(vol, (Z >= 2) & (Z < 5) & (np.abs(X - 7) <= 2), None)`.
- **Details on one side only:** combine a mask with `Y > ...` (front), `Y < ...` (back) or `X < ...` (left).
- **Details on top:** `exposed_top(vol) & mask`. For example, paint mushroom spots where the top surface sits at certain radii.
- **Symmetry:** build one half and mirror it with `vol[:, :, ::-1]`, then combine.
- **Asymmetric decals** (text, numbers) read mirrored on the far side when one side view paints both sides. Repaint them on that side, or leave them off.
- **Stray voxels and empty margins:** check the `warnings` from `stack.py`, then `trim(vol)`.
- **Shade last,** after painting. `shade(vol, 0.25)` darkens the walls and step lips that carve painted from the side views, in flat cool-shifted steps (`cool=0.25` by default so warm walls and whites stay crisp instead of going muddy grey; pass `cool=0` for neutral RGB darkening). Use `0.2–0.3` for flat-coloured art and chunky props; art that already has rich painted shading needs `0–0.15`.

## Size sanity and pixel-art tiers

- Pick a target tier when authoring from scratch or generating views:
  - **Chunky retro:** `15–20` slices (about `24×40` px). Bold silhouettes, 3–4 px stripes.
  - **Detailed hi-bit:** `26–44` slices (`32×64` to `48×96` px). Holds vents, windows, spoked rims, roof tiles.
  - **Showcase / HD:** `36–56` slices (`32×32` to `128×128` px). Smooth rotation without chunky stepping.
- Use **3-tone hue-shifted ramps** (cool deep shadow, saturated mid, warm top highlight) with flat clusters and crisp specular pixels on glass.
- **Spheres in 2D sprite stacks:** an equal-radius sphere (`R_z = R_xy`) looks round in GLB/OBJ, but stretches vertically under sprite-stack pitch `squash` and slice `spacing`. For a 2D sprite-stack-only sphere, set `R_z = R_xy * sqrt(1 - squash²) / spacing`.
- One slice per art pixel of height. Keep each dimension under about 128 (render cost, and `.vox` is limited to 256). If the art is large and detailed (over 96 px), consider building at half size (`fit` the views down by 2): stacks read best when chunky.
