# Getting clean native pixel art

Goal: one image pixel = one art pixel, a transparent background, a small flat palette, and the outline colour noted. Everything after this step assumes it.

## Is it already native?

It is **not** native when any of these hold:
- every colour region is a block of 2+ identical pixels;
- the image is much larger than the art could be (an 800×546 image of a 64×64 sprite);
- edges are soft or blurry;
- there is JPEG noise (speckle around edges, many near-identical colours);
- an editor checkerboard, rulers, menus or text are visible.

AI "pixel art" is usually all of these at once.

## Default: `scripts/pixel_grid.py`

```bash
uv run scripts/pixel_grid.py shot.png -o art.png                       # detect everything
uv run scripts/pixel_grid.py shot.png -o art.png --size 64x64          # the art is known to be 64x64
uv run scripts/pixel_grid.py shot.png -o art.png --crop 200,40,470,465 # cut away UI first
uv run scripts/pixel_grid.py sheet.png -o views.png --split            # one PNG per drawing
```

What it does, in order:
1. **Identifies the background and canvas.** It handles transparency, a flat border colour, or a checkerboard. When UI or a frame surrounds the art, it finds the canvas and uses only that region (`canvas` in the JSON). For a flat backdrop confirmed by the corners and border, it uses the original colours to locate the grid, clears matching cell centres with a narrow tolerance to preserve dark outlines on dark backdrops, and peels 1-px anti-aliased halo fringes on high-contrast soft/JPEG backdrops so pale fringes don't shield dark outlines from `strip_outline`. The `--bg-tol` option overrides that tolerance.
2. **Measures the pixel size.**
   - Clean whole-number upscales: the common divisor of all colour run lengths.
   - Clean fractional scales (2.5, 6.84): fitted to the colour edges.
   - For JPEG, blurry or AI images, Pixel Art Fixer estimates the row and column counts independently. The sampler fits the grid offset to the image. On long sheets it also compares the fit of the edge-profile estimate. With `--split` on a noisy multi-view sheet (2–8 drawings, not an animation grid), each extracted view's grid and phase are refined independently so per-view scale or phase drift in AI model sheets doesn't smear details.
   - When one-pixel details suggest the image could already be native, the script checks how much edge colour and silhouette detail the smaller grid would lose. When the smaller grid loses detail, the script also checks whether bilinear enlargement explains the soft edges. Both candidate sizes appear in the JSON.
3. **Recovers one colour per cell.** A centre median suppresses compression noise. If a bilinear enlargement fits the input edges closely, the script reverses that colour mixing and reports `bilinear_edge_error`.
4. **Drops stray parts.** Small pieces near the image edge, such as a dashed frame line or a canvas border, are removed when the drawing itself doesn't reach the edge. Other detached parts stay and are listed in `notes`. `--parts largest` keeps only the biggest drawing; `--parts all` keeps everything.
5. **Reduces the palette.** For noisy input it first folds near-identical colours (compression noise) into the most common one. It reduces noisy results to 32 colours when more than 48 remain. Clean art and verified bilinear reconstructions skip this palette limit. Bilinear reconstruction can merge rounding differences within two RGB levels. Use `--colors` to request a specific limit.

A rectangular drawing can resemble a flat editor canvas. When the image gives too little evidence to crop it automatically, use `--crop X,Y,W,H` to select the canvas.

Read the JSON:

| field | meaning |
|---|---|
| `pixel`, `method`, `native_size` | image px per art px, how it was found, the resulting size |
| `fit_error` | Mean RGB error on visible source pixels when the sampled cells are enlarged again, before palette cleanup. Values under about 6 suggest a close match. Check noisy results visually, especially above 20. |
| `grid_candidates` | When the native size is ambiguous, `input_size` is the full canvas and `fixer_size` is the proposed smaller grid. `fixer_edge_error` measures the colour or opacity lost at edges. If present, `bilinear_edge_error` measures the same loss after bilinear enlargement. Keeping the input size always yields zero `fit_error`. Compare the eyes, thin outlines or other fine details and use `--size WxH` to try the alternative. |
| `canvas` | the canvas it snapped to, in input pixels |
| `art_bbox`, `colors`, `background` | what is left (`art_bbox` is x, y, w, h in output pixels) and how the background was read. An `art_bbox` as big as the whole image means something besides the art survived. |
| `parts` | connected pieces found and how many were dropped |
| `notes` | read every one: dropped parts, leftovers, palette reduction, a high `fit_error` |
| `drawings` (`--split`) | one file per drawing in reading order, with its `row` and `col`. For 2–4 drawings (including `1×4` and `2×2` orthographic model sheets), `view_guess` labels each one `top`, `side` or `front or back` by matching sizes, or `front, back or side` when all are tall drawings of one height (a character seen from several directions). |
| `grid` (`--split`) | the drawings sit on a regular sprite-sheet grid (not a distinct-proportion `1×4` / `2×2` orthographic model sheet). Each drawing then also has a `cell_file` (`NAME_r2c3.png`), cut at the same place in every cell so animation frames stay lined up. |

Then **look** at two images, named after `-o` (`-o cat.png` gives `cat_check.png` and `cat_grid.png`):
- `art_check.png`: the result enlarged on a loud flat colour. Anything that isn't the art (frame dashes, UI, background specks, a shadow you don't want) shows up here. A transparent PNG viewed directly hides them.
- `art_grid.png` (listed under `grid_check` when downsampling): dotted magenta grid lines over the input. Each line must sit on a colour edge; lines that drift across cells mean the size is wrong.

Also check in `art_check.png`: is the outline 1 px all round, and are the eyes and small features intact? To remove a leftover by hand, `crop` to the drawing or `paint` the pixels transparent before building.

`--ascii` adds a text dump (one letter per colour) that gives exact coordinates for later painting.

## When detection is wrong

- **Crop to the art first** (`--crop X,Y,W,H`, input pixels). UI, text, rulers and neighbouring sprites add edges of their own. A rough crop with a margin is fine; the canvas snap tightens it.
- **If the user knows the size, use it.** If they say "it's 32×32", pass `--size 32x32` for the canvas or crop region.
- **Measure it yourself.** A dark outline is 1 art pixel thick, so its thickness in image pixels is the pixel size. Alternatively, count the art pixels across a feature and divide that feature's image width by the count. Pass the result as `--pixel 6.84`; use `--pixel 7,6.9` if x and y differ.
- **AI "pixel art" often has no single grid**: cells drift and vary in size. Take the dominant size and accept some cleanup. Or redraw the object at its intended resolution yourself; 32–64 px is quick to write as a character grid (see `making-views.md`).
- **Not pixel art at all** (a smooth illustration, a vector drawing, a render): there is no grid to find, so `fit_error` stays high whatever you try. Choose the resolution yourself. `--pixel N` turns N×N image pixels into one art pixel, and `--pixel 1` keeps every pixel. Pick N so the object ends up at a sprite-stack size (about 16–96 px on its longest side), and expect to clean soft edges and merge colours.
- Photos of screens taken at an angle are out of scope; ask for a screenshot or an export.

## Doing it without the script

1. Crop to the art.
2. Find the pixel size p.
   - Clean upscale: p is the greatest common divisor of the colour run lengths along rows and columns.
   - Otherwise measure it as above.
3. Find the offset φ: the grid lines φ + k·p should land on colour edges.
4. Sample the middle of each cell at φ + (k + 0.5)·p; a median of the middle half resists noise.
5. Never resize with bilinear or bicubic filtering. Nearest-neighbour is only safe for whole-number scales at offset 0.

## Background, palette and outline

- **Background.** Flood-fill from the image border: everything connected to the border and close to its colour, or to either of a checkerboard's two greys. The flood fill does not reach art inside the silhouette that happens to share the background colour. For tiles and full-bleed art, keep the background (`--bg none`).
- **Palette.** Keep intentional shades in clean art. For damaged sheets, merge near-duplicate JPEG colours across all views. Use `voxlib.shared_palette(views, 24)` when a 24-colour palette suits the source.
- **Outline.** `img, rgb = voxlib.strip_outline(img)` recolours the dark pixels on the silhouette edge with the colour just inside them. This keeps the size, so views still line up. Pass the returned colour to `stack.py --outline '#rrggbb'` to draw one outline round the finished stack. If it returns `None`, the outline isn't dark (glass, coloured outlines): read its colour with `show` and pass it, `strip_outline(img, colour="#a2c3df")`. Don't strip outlines from parts that are nothing but outline, such as a 1-px antenna or a whisker.
- **Background seen through the art.** Glass, windows, gaps between bars and holes in a wreath often show the original backdrop's colour inside the silhouette. The flood fill can't reach it, so it stays as art. Repaint it as what should be there (the contents, a darker interior) or cut it out if it is a real hole.

## Sheets with several views

`--split` writes each drawing separately in reading order and drops small marks (labels, specks). A small piece near a drawing (a sparkle, a detached hand) joins it, but two drawings never merge, so a ring of eight directions gives eight files; a drawn shadow under the feet stays with its drawing. If drawings still come out joined, a halo of backdrop-like pixels links them: raise `--bg-tol`. Each drawing's `view_guess` comes from matching sizes: the top view's length is the side view's length, the top's width is the front's width, and the side's height is the front's height. Confirm it by the features:

- **Top view:** the roof, seen from above. Don't pick it as the tallest drawing: that is true for a long car drawn nose down, but a tree's or a tower's tallest drawing is its side.
- **Side view:** the profile, with wheels or feet along the bottom.
- **Front and back:** the remaining two, usually front first. The back shows tail lights, an exhaust, or the back of a head. Same-sized views (a tree from four sides) can be used in any order.

Pass `side_nose="right"` for a right-facing profile and `top_nose="up"` for a nose-up roof drawing. The latter rotates the top view by 180°.
