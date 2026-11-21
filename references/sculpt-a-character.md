# Sculpt a character by parts

Use this for a character from direction views (front, back, sides). The drawings decide each part's size and where its features go. Colours come from a few clean colours you pick, not from projecting every pixel.

**Why not just carve?** `carve(..., rounded=True)` gives about the same shape. But it colours each wall voxel from the nearest drawing, and on a rounded body that choice flips between the front and the side drawing voxel by voxel. At 45° the two drawings interleave, and their soft pixels and linework show as specks, worst on soft or AI-made art. On one 4-view sheet, 5.4% of the carved surface voxels were isolated specks; the same character built with this recipe had 0.1%, plus the hair texture added on purpose.

## 1. Prepare the views

```bash
uv run scripts/pixel_grid.py sheet.png -o views.png --split            # add --colors 14 for soft art
```

Soft or AI-made art (a `fit_error` above about 10, or dozens of colours in a small sprite) reads better with `--colors 12`–`16`. A ring or row of directions splits into one file per direction; use the four that face front, back, left and right. Then load the drawings and print them:

```python
front, back, side, side2 = (load(f"views_{i}.png") for i in (1, 2, 3, 4))
for v in (front, side):
    print(v.shape); print(show(v))
```

Clear a drawn shadow under the feet first (`v[near(v, ["#60656a"])] = 0` with its colour from `show`), or `part_rows` reads it as part of the legs. The side view must have its nose pointing LEFT (`side = side[:, ::-1]` if not), and `side2` RIGHT. From the dumps, note the rows where each part starts and ends: hair, face, neck, body, arms, shorts or skirt, legs. Layers count up from the feet: row `r` of a drawing `h` rows tall is layer `z = h - 1 - r`.

Make the volume from the views' sizes: `vol = blank(tallest height, side width, front width)`.

## 2. Shape each part

`part_rows(vol, front, side, z=(lo, hi))` reads, for every layer in that band, how far the front view spans in x and the side view in y. `sculpt(vol, rows)` turns each layer into a rounded slice inside that box.

```python
rows = lambda **r: part_rows(vol, front, side, **r)
legs = sculpt(vol, rows(z=(0, 4), x=(0, 9)) + rows(z=(0, 4), x=(10, 19)))   # two legs, split by x
body = sculpt(vol, rows(z=(9, 22)))
head = sculpt(vol, rows(z=(23, 38)), power=2.2)                             # rounder than the default 2.5
```

- **Print the rows** (`print(rows(z=(9, 22)))`) and fix layers where something else covers the part's edge. Only each row's two ends count, so a face inside the hair is fine. An arm held across the body is not.
- **Separate parts where the silhouette joins them:** legs by `x`, arms that hang beside the body by `x` and a narrower `y`, a tail by `y`.
- **Hair is several parts, not one.** A crown (the dome), back hair down to where it ends in the back view, side locks or a fringe hanging in front of the face's edges, and a tuft or bun as its own small part. One rounded mass reads as a helmet from every angle.
- **Power:** 2 is an ellipse; 2.5 (the default) suits chunky pixel bodies; 3 or more is boxy (a backpack, a crate).
- **Invent what no view shows** by editing the numbers: a fuller back of the head, a nose 1 px proud of the face.

## 3. Paint each part flat

Pick 2–4 colours per part from the art: its main colour, a shadow, maybe a highlight. Use bands by height and masks from `coords`.

```python
Z, Y, X = coords(vol)
paint(vol, legs, "#18262f")
paint(vol, body, "#c6e3c3")
paint(vol, body & (Z >= 15), "#f3f0c8")          # a lighter yoke
paint(vol, head, "#48604d")                      # hair
paint(vol, head & (Z <= 30), "#1d2c2a")          # darker lower bob
paint(vol, facing(head, "top") & ((X + 2 * Y + Z) % 7 == 0), "#576654")   # a few strands
```

Paint whole parts first, then features. Later paint wins.

## 4. Put features only where they face

`decal(vol, view, where, side, colours=..., flat=...)` paints the voxels of `where` that face that view, where the drawing shows those colours. `flat` paints one clean colour; without it the drawing's own pixels are copied. Nothing runs round to the sides.

```python
face = head & (Z <= 29)
decal(vol, front, face, "front", colours=["#f5f2cb", "#c7ccb4"], flat="#f8deae", depth=2)   # skin
eyes = face & (Z >= 25) & (abs(X - 9.5) <= 4)                                          # the eye box
decal(vol, front, eyes, "front", colours=["#43453a"], tol=8, flat="#41291b", depth=2)
paint(vol, facing(body, "front") & (Z == 21) & (abs(X - 9.5) <= 2), "#385146")         # collar
decal(vol, back, body & (Z >= 13) & (Z <= 18) & (abs(X - 9.5) <= 3), "back",
      colours=["#2a392e"], flat="#385146")                                             # back print
decal(vol, side2[:, ::-1], head & (Z >= 32), "left", colours=["#f5f2cb"], flat="#f8facf")  # hair clip
```

- **Bound every feature to its box** (a `Z` and `X` range). Colour matching alone also hits look-alike colours elsewhere: the eye colour matched the hair shadow.
- **Keep `tol` small** (8–12) for feature colours on soft art.
- **The face comes from the front view only.** A side view's eye or fringe pixels decalled onto the `left`/`right` surfaces land beside the front's and double the face at 45°. Use the side view for the profile's shape and for side-only details (an ear, a hair clip).
- **Don't decal every dark pixel of the body.** The drawing's arm and fold lines sit at the silhouette edge, and the front-facing voxels there are on the flanks, so they show as stripes at 45°.
- **`depth=2`** on round parts (a face on a round head) keeps the feature solid when turned.
- Side names are relative to the front elevation. A nose-right drawing shows the left wall. Flip that drawing horizontally for `decal(..., "left")`, which expects its input nose-left. Likewise, flip a nose-left drawing for `decal(..., "right")`.

## 5. Check and export

```bash
uv run build.py
uv run scripts/stack.py girl_slices.png --squash 0.4 --no-shadow --height 1.6
```

A standing character reads better from a lower camera than the default 0.75, which mostly shows the top of the head. `--height` sets the mesh's height in metres: at the default 16 art pixels per metre a 38-layer character imports 2.4 m tall. If the art has a dark outline, pass its colour (`strip_outline` returns it) as `--outline '#201214'`: the preview and sprite-stack exports then draw it round the silhouette at every angle, as the art does. The GLB and OBJ have no outline. In the preview:
- the flat front and back in the last row should resemble the drawings;
- 45° and 135° should show clean parts. Specks or stripes there mean a decal reached too far;
- the face and markings should not appear on the back.

## Worked example

A 20 × 19 × 38 chibi from a soft, AI-made 4-view sheet (front, back, side nose left, side nose right), after `--split --colors 14`:

```python
# /// script
# dependencies = ["numpy", "pillow"]
# ///
import sys
sys.path.insert(0, "/path/to/sprite-in-the-round/scripts")
import numpy as np
from voxlib import *

front, back, side, side2 = (load(f"views_{i}.png") for i in (1, 2, 3, 4))
vol = blank(39, 20, 20)                                   # tallest view, side width, front width
rows = lambda **r: part_rows(vol, front, side, **r)
Z, Y, X = coords(vol)

legs = sculpt(vol, rows(z=(0, 4), x=(0, 9)) + rows(z=(0, 4), x=(10, 19)))
shorts = sculpt(vol, rows(z=(5, 8)))
body = sculpt(vol, rows(z=(9, 22)))
head = sculpt(vol, rows(z=(23, 38)), power=2.2)

paint(vol, legs, "#18262f")
paint(vol, shorts, "#15252d")
paint(vol, body, "#c6e3c3")
paint(vol, body & (Z >= 15), "#f3f0c8")
paint(vol, body & (Z == 9), "#385146")                    # hem
paint(vol, head, "#48604d")
paint(vol, head & (Z <= 30), "#1d2c2a")
paint(vol, facing(head, "top") & ((X + 2 * Y + Z) % 7 == 0), "#576654")

face = head & (Z <= 29)
decal(vol, front, face, "front", colours=["#f5f2cb", "#c7ccb4", "#d1e6c4"], flat="#f8deae", depth=2)
eyes = face & (Z >= 25) & (abs(X - 9.5) <= 4)
decal(vol, front, eyes, "front", colours=["#43453a"], tol=8, flat="#41291b", depth=2)
for side_name in ("front", "back"):
    paint(vol, facing(body, side_name) & (Z == 21) & (abs(X - 9.5) <= 2), "#385146")
decal(vol, back, body & (Z >= 13) & (Z <= 18) & (abs(X - 9.5) <= 3), "back",
      colours=["#2a392e", "#1d2c2a", "#43453a"], flat="#385146")
decal(vol, side2[:, ::-1], head & (Z >= 32), "left", colours=["#f5f2cb", "#d1e6c4"], flat="#f8facf")

save_sheet(trim(vol), "girl_slices.png")
```

More detail is more of the same: sleeves and hands as their own parts, a fringe painted on the front of the hair, shading bands on the lower half of each part.

For animation frames, carving each frame (`sheets-and-animation.md`) keeps the frames consistent with no per-frame tables. Repaint the carved colours flat with the same masks for every frame.
