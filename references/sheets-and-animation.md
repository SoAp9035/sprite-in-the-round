# Sprite sheets and animation

A character sheet holds what a single sprite can't: the back, the sides and how the character moves. That makes it the best input for a character. You get real silhouettes from several sides, and you can make the stack walk.

## Reading the sheet

`pixel_grid.py sheet.png -o cat.png --split` writes one file per drawing with its `row` and `col`. When the drawings sit on a regular grid, the JSON also has `grid` and a `cell_file` per drawing (`cat_r2c3.png`). Cell files are cut at the same place in every cell, so a frame keeps its position relative to the others: the bob of a walk, a tail swinging past the body. Use cell files for animation; the tight crops (`cat_7.png`) suit single views.

Then look at the sheet and decide what each row and column is:
- **Rows are usually directions, columns animation frames**, but some sheets put directions in columns and frames in rows.
- **Direction order varies**: RPG Maker uses down, left, right, up; LPC uses up, left, down, right. Tell them apart by the face: toward the camera is the front, away is the back, nose left or right is a side.
- **Extra rows** hold other actions: idle, sit, attack, sleep. In a walk, column 1 is often the standing pose.
- **One side only:** many sheets draw one side and mirror it in the engine. Reuse that side.
- **Rows that differ only a little**, like blinking or breathing, can be one model with painted changes.

## Game views are not model-sheet views

Sheet sprites are drawn for a camera above and in front: a 3/4 view, not an orthographic one.
- **Side views** are close to true profiles. Trust them for height and length.
- **Front and back views** show some of the top. A cat walking toward you shows its back rising behind its head; a character's head shows its crown. `carve` reads all of that as height. Use the front and back for width, and for what the front and back look like. Where they show top surfaces instead of front ones, trim the silhouette or treat those rows as colour only.
- **Heights differ by a pixel or two** between directions (ears, hair, a tail tip). Without a top view, `carve` keeps every view at its own size and stands them on one ground line, so small differences don't rescale anything.
- **The stack's camera also looks down** (squash 0.75), so tops show a lot: the top of the head, the back, the shoulders. Paint them on purpose.

## Building a character from direction views

For a static model, sculpt the character by parts (`sculpt-a-character.md`): the shape is about the same as carving, but the colours stay clean. Carving, below, is the quick way to build every animation frame the same way; repaint its colours flat afterwards.

How much the front and back views can be trusted decides the route.
- **Front and back close to orthographic.** This covers most standing humanoids: a person seen from the front looks like a person seen from the front. Carving from all four directions works.
- **Front and back strongly 3/4.** A four-legged animal walking toward you is drawn as a tall column of head, back and tail. Its silhouette is mostly top, not front, so carving with it gives slabs and a fat head. Take the shape from the side views, and use the front and back for paint only.

```python
side  = load("cat_r4c1.png")     # nose left
side2 = load("cat_r2c1.png")     # nose right: the other side as drawn
front, back = load("cat_r1c1.png"), load("cat_r3c1.png")
views = [strip_outline(v)[0] for v in (side, side2, front, back)]
vol = carve(side=views[0], side2=views[1], front=views[2], back=views[3], rounded=True)
```

- **Carve all four, rounded.** There is no top view. Front and back give the width at each height, the sides give the depth, and `rounded=True` makes each layer an ellipse inside that box, so heads and bodies read as round from 45°. `side2` paints the far side from its own drawing.
- **Thin decorations widen silhouettes.** Whiskers, hair strands, a staff held out, sparkles and the drawn shadow under the feet (`img[near(img, ["#929292"])] = 0`) all do it. Take them out before carving, then paint them back or add them as thin parts.
- **Legs and arms** exist where both views have them. Check the gaps between legs at 45°.
- **Tops.** Without a top view, tops take the side view's colour at that height. On a dome (a head, a cat's back), each layer's ring gets a different row of the side view, so the side view's bands come back as stripes. Paint tops on purpose: a hair colour with a parting and a highlight, or a fur pattern.
- **One width per height.** `carve` gives one width at each height, so a head wider than the body at the same height, or legs apart from the body, need parts.

Ideas that have worked, to mix freely:
- **Sides as halves.** Each side view shapes its own half of the body: the x < W/2 half from `side`, the rest from `side2`. The near and far legs keep their own poses.
- **Parts with chosen widths.** Split the side silhouette into head, body, legs and tail using rows and columns read with `show`. Give each part its own width and roundness, then `place` the parts together.
- **Project a view as paint.** The front art was drawn for a camera above and in front, so paint it the way that camera sees the stack. Send each pixel of the view along the camera's ray: going back one voxel, the ray drops `squash` layers (0.75). Colour the first solid voxel each ray hits. This is how a face drawn for a 3/4 camera lands on a head that is mostly seen from above. Keep the projection to the parts it belongs to (the head, the chest), or it streaks over the sides and tops.
- **Inflate** the front view and repaint the back.
- **Primitives:** ellipsoids and columns with `coords`, for tiny or very stylised characters.

The art is usually already shaded, so use `shade` lightly or not at all.

## Animation

An animated stack is one slice sheet per frame, all the same size, stacked as rows: `save_sheet([vol0, vol1, ...], "cat_walk_slices.png")`, then `stack.py cat_walk_slices.png --fps 8` (the sheet remembers its slice and frame counts). The preview shows every frame at 8 turns, the GIF plays while it turns, the viewer plays it, and `--dirs` lays facings out in rows and frames in columns.

Ways to get the frames. Choose by how well the sheet's directions agree, and mix them freely.
- **Carve every frame** from frame k of each direction. Pass cell files and `aligned=True` so every frame carves in the same box, then `trim(frames)` crops them together. This is quick when the directions are in sync and close to orthographic. Views drawn separately can disagree: a leg forward in the side view but tucked up in the front view comes out short or missing.
- **Shape from the side frames.** Rebuild each frame from frame k of the two side views (as halves, or as parts), and paint it from the front and back frames. This is the steadier route for 3/4 creature sheets.
- **One body, moving parts.** Build the body once from the standing frame, then move the legs, tail or head per frame with masks and `place`, copying the motion from the side frames. No flicker from views that disagree.

Keep frames steady:
- Feet stay on z = 0 unless the character jumps.
- A 1-px body bob reads well; more looks like hopping.
- The turning point is the volume's centre, so trim all frames together, never one by one.
- Keep one palette across frames.
- Check the frame rows in the preview: anything that pops in for one frame and out the next will flicker in the game.

## Engines

For an animated sheet, a slice's source rectangle moves down one frame height per frame: y = frame × D, where D = sheet height ÷ frames. Everything else is the same as a still stack. A direction sheet made with frames is an ordinary sprite sheet: row = facing, column = frame.
