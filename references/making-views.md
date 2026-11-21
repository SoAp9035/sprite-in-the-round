# Views you don't have

`carve` gives the most faithful shape, and it only needs views that agree with each other. When the user gave one view, you can often make the others yourself. Even a flat-coloured silhouette carries the shape; colour comes mostly from the view you already have.

## What carve expects

| view | seen from | orientation | size must match |
|---|---|---|---|
| top | straight above | front pointing **down** | length = side view's length, width = front view's width |
| side | the object's right side | front pointing **left** | height = front view's height |
| front | the front | as drawn | |
| back (optional) | behind | as drawn (it is mirrored for you) | |
| side2 (optional) | the other side | as drawn, front pointing **right** | same as side |

Sizes can differ by a whole-number scale between views (`carve` rescales to the top view), but proportions must agree. A 2:1 car must be 2:1 in both the top view and the side view. The top view is optional: without it, views keep their size and must share one scale, as sprite-sheet directions do.

## Draw a missing view yourself

This is usually the best route for a single front view of something boxy (house, chest, car, robot), or for a top-down sprite that needs a height profile. Write it as a character grid and convert it:

```python
import numpy as np
from PIL import Image

PAL = {".": None, "r": "#b13e53", "d": "#5d275d", "w": "#f4f4f4", "k": "#1a1c2c"}
SIDE = """
....rrrrrr......
...rrwwwwrrr....
rrrrrrrrrrrrrrrr
rrrrrrrrrrrrrrrr
ddkkdddddddkkddd
..kk.......kk...
"""
def grid_to_png(text, pal, path):
    rows = [r for r in text.strip("\n").splitlines()]
    a = np.zeros((len(rows), max(map(len, rows)), 4), np.uint8)
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            c = pal.get(ch)
            if c:
                a[y, x] = (*[int(c[i:i + 2], 16) for i in (1, 3, 5)], 255)
    Image.fromarray(a).save(path)
grid_to_png(SIDE, PAL, "side.png")
```

How to design it:
- Start from what you know. Take the length from the top view, or from the real object's proportions. Take the height from the front view's rows.
- Line up features with the view you have. If the front view shows a door 6 px tall, the side view's wall is at least that tall. Windows on the front are at the same height on the side.
- Reuse the existing palette, and paint flat colours. `carve` only uses the side view's colours for the side walls, 2 px deep.
- For a top-down sprite, the side view is mostly a height profile: where the hood is low, where the cabin rises, where the wheels sit.
- Then look at row 3 of the stack preview: the flat views of your volume should match the views you drew.

## Generate views with an image model (if your environment has one)

Pass the user's sprite as a reference image (or describe the subject directly). Pick a target tier — **15–20 px** chunky retro, **26–44 px** detailed hi-bit, or **36–56 px** showcase — keep the layout and shading sentences intact, and swap in the object:

```
Chunky pixel art orthographic model sheet of {the object in the reference image, same design and palette}
with rich 3-tone hue-shifted pixel shading (deep cool-shifted shadows, saturated midtones, bright warm top
highlights along ridges and edges), bold 3-4px stripes/accents, and crisp specular pixels on glass. Four
views in a clean 1x4 horizontal row (or 2x2 grid) on a completely flat solid white or pale gray background:
1. TOP view looking straight down, front pointing DOWN.
2. SIDE view, front pointing LEFT.
3. FRONT view.
4. BACK view.
Strictly orthographic: zero perspective, zero tilt, zero 3/4 angle. Identical scale across all four views
so length, width, and height match pixel for pixel. Bold 1px dark outline around each view, solid flat
color clusters, crisp internal panel shading, zero anti-aliasing, zero soft edges, zero cast ground
shadows, zero grid lines, zero text, zero labels, generous empty space between views. Low-resolution
chunky pixel art, each view about 36 pixels.
```

For round objects, ask for a top view and one side view only, and use `lathe(side, top=top)`. Run the result through `pixel_grid.py --split`; generated "pixel art" rarely sits on one global grid, so `--split` refines each view's grid independently, peels anti-aliased halos, and labels `top`, `side` and `front or back`.

## Check any view sheet before using it

- Which drawing is which? Use matching sizes (`view_guess` from `pixel_grid.py --split`) and features, not "tallest is the top". Does the side face **left**?
- Is it really orthographic? A visible roof in the side view, or a visible side in the front view, means perspective. Redraw those parts or ask for another sheet.
- Do sizes agree? Compare the side length with the top length, the front width with the top width, and the side height with the front height. The first generation often doesn't.
- Bold 1-px outline and flat fills? Soft grey edges smear once stacked. SpriteCook's first try came out like that.
- Does the back view show the back (lights, exhaust, the back of a head), or is it a copy of the front?
