"""Regression cases for carving and stack warnings, each built from a real mistake.
Run with: uv run --with numpy --with pillow python -m unittest discover -s evals"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from voxlib import (blank, carve, crop, decal, facing, load_sheet, part_rows, save_sheet, sculpt,  # noqa: E402
                    shade, shared_palette, stack_views, strip_outline, trim)
from stack import elevations, thin_runs  # noqa: E402

RED, DRK, TYR, BARK, LEAF = (210, 40, 50), (40, 50, 70), (30, 30, 34), (110, 70, 40), (60, 150, 70)


def view(w, h, rects):
    a = np.zeros((h, w, 4), np.uint8)
    for x0, y0, x1, y1, c in rects:
        a[y0:y1, x0:x1] = (*c, 255)
    return a


def outlined(v):
    """A 1-px dark outline on every empty pixel 4-adjacent to the drawing, as artists draw it."""
    h, w = v.shape[:2]
    o = np.zeros((h + 2, w + 2, 4), np.uint8)
    o[1:-1, 1:-1] = v
    m = o[..., 3] > 0
    p = np.pad(m, 1)
    o[~m & (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:])] = (15, 15, 20, 255)
    return o


def dark(a):
    return int(((a[..., :3].astype(int).sum(-1) < 60) & (a[..., 3] > 0)).sum())


class CarveTests(unittest.TestCase):
    def test_asymmetric_views_keep_their_orientation(self):
        top = view(6, 8, [(0, 0, 6, 8, LEAF), (1, 2, 2, 3, RED)])
        right = view(8, 5, [(0, 0, 8, 5, RED), (1, 2, 2, 3, LEAF)])
        left = view(8, 5, [(0, 0, 8, 5, BARK), (2, 2, 3, 3, TYR)])
        front = view(6, 5, [(0, 0, 6, 5, DRK)])
        for nose, side, side2 in (("left", right, left), ("right", left, right)):
            for roof in (top, None):
                vol = carve(top=roof, side=side, side2=side2, side_nose=nose, front=front)
                np.testing.assert_array_equal(elevations(vol)[1][2], right[2])
                np.testing.assert_array_equal(vol[2, :, 0], left[2])
                if roof is None:
                    np.testing.assert_array_equal(vol[-1, 4, [0, -1]], [left[0, 4], right[0, 3]])
        vol = carve(top=np.rot90(top, 2), top_nose="up", side=right)
        np.testing.assert_array_equal(elevations(vol)[3], top)

    def test_side_decals_match_the_drawings(self):
        vol = blank(5, 8, 6)
        vol[:] = (*DRK, 255)
        mask = vol[..., 3] > 0
        for side, x, nose in (("right", -1, 1), ("left", 0, 6)):
            drawing = view(8, 5, [(nose, 2, nose + 1, 3, RED)])
            decal(vol, drawing[:, ::-1], mask, side)
            np.testing.assert_array_equal(vol[2, 6, x], (*RED, 255))
            np.testing.assert_array_equal(vol[2, 1, x], (*DRK, 255))

    def test_outline_in_concave_corners_is_stripped(self):
        # A cap on a stem over a base plate: outline pixels in the corners under the cap touch
        # the outside only diagonally. They used to survive as dark voxels inside the stack.
        side = outlined(view(24, 24, [(0, 0, 24, 10, RED), (9, 10, 15, 20, BARK), (0, 20, 24, 24, LEAF)]))
        stripped, rgb = strip_outline(side)
        self.assertEqual(dark(stripped), 0)
        self.assertEqual(rgb, (15, 15, 20))
        top = outlined(view(24, 24, [(0, 0, 24, 24, RED)]))
        vol = carve(*(strip_outline(v)[0] for v in (top, side, side, side)))
        self.assertEqual(dark(vol), 0)

    def test_rounded_keeps_a_round_base_and_rounds_the_tower(self):
        # A thin tower on a wide disc. Rounding after the top view cut the disc eroded it.
        yy, xx = np.mgrid[0:24, 0:24]
        disc = np.zeros((24, 24, 4), np.uint8)
        disc[(yy - 11.5) ** 2 + (xx - 11.5) ** 2 < 144] = (*RED, 255)
        side = view(24, 30, [(8, 0, 16, 26, RED), (0, 26, 24, 30, LEAF)])
        vol = carve(top=disc, side=side, front=side, back=side, rounded=True)
        self.assertEqual(int((vol[0, ..., 3] > 0).sum()), int((disc[..., 3] > 0).sum()))
        mid = vol[vol.shape[0] // 2, ..., 3] > 0
        ys, xs = np.nonzero(mid)
        self.assertFalse(mid[ys.min(), xs.min()], "the tower should carve round, not square")

    def test_no_body_colour_ring_around_a_narrower_cabin_top(self):
        # The outlined cabin's top row is a pixel shorter, so the slice below exposes a 1-px
        # ledge. It took the top view's body colour: a red ring around the roof.
        L, W = 48, 24
        top = view(W, L, [(0, 0, W, L, RED), (4, 10, W - 4, 38, DRK)])
        side = view(L, 18, [(0, 7, L, 15, RED), (10, 1, 37, 7, DRK), (5, 13, 13, 18, TYR), (35, 13, 43, 18, TYR)])
        front = view(W, 18, [(0, 7, W, 15, RED), (4, 1, W - 4, 7, DRK), (1, 13, 4, 18, TYR), (W - 4, 13, W - 1, 18, TYR)])
        views = shared_palette([strip_outline(crop(outlined(v)))[0] for v in (top, side, front, front)], 24)
        vol = carve(*views)
        red = (vol[..., 0] > 150) & (vol[..., 1] < 80) & (vol[..., 3] > 0)
        solid = (vol[..., 3] > 0).sum((1, 2))
        above_body = np.arange(len(solid)) > np.flatnonzero(solid == solid.max()).max()
        cabin = above_body & (solid < solid.max() // 2)          # the hood slice is still body-sized
        self.assertTrue(cabin.any())
        self.assertEqual(int(red[cabin].sum()), 0)
        self.assertEqual(dark(vol), 0, "outline specks left in the corners")


    def test_steep_step_lips_take_the_facing_view_and_shade_like_walls(self):
        # A coupe's nose rises about a layer per pixel. The top view painted every step's lip, so
        # the front showed a second row of headlights above the front view's, and shade() left
        # the lips light between dark walls: stripes across every slope.
        def stairs(run):
            L, W, H = 16, 8, 6
            side = np.zeros((H, L, 4), np.uint8)
            for z in range(H):
                side[H - 1 - z, run * z:] = (*BARK, 255)       # nose LEFT: column 0 is the front
            top = view(W, L, [(0, 0, W, L, RED)])
            front = view(W, H, [(0, 0, W, H, LEAF)])
            vol = carve(top=top, side=side, front=front)
            occ = vol[..., 3] > 0
            nose = [occ[z, :, 4].nonzero()[0].max() for z in range(H)]   # front-most y per layer
            return vol, nose

        vol, nose = stairs(1)
        for z in range(vol.shape[0] - 1):
            self.assertEqual(tuple(vol[z, nose[z], 4, :3]), LEAF, f"lip of layer {z}")
        shaded = shade(vol, 0.3)
        for z in range(vol.shape[0] - 1):
            self.assertLess(int(shaded[z, nose[z], 4, :3].sum()), sum(LEAF), f"lip of layer {z} unshaded")
        vol, nose = stairs(2)                                    # a gentle slope (a hood) stays a top
        for z in range(vol.shape[0] - 1):
            self.assertEqual(tuple(vol[z, nose[z], 4, :3]), RED, f"top of layer {z}")


class SculptByPartsTests(unittest.TestCase):
    # Carving a soft 4-view character projected two noisy drawings onto every wall and left
    # specks at 45 degrees. Sculpting parts and painting features only where they face fixes it.
    def test_part_rows_reads_both_views_on_one_ground(self):
        front = np.zeros((4, 10), bool)
        front[0, 3:7] = True                       # head, top row of the drawing
        front[1:, 1:9] = True
        side = np.zeros((5, 6), bool)              # one row taller, nose LEFT
        side[0, 2] = side[1, 1:3] = True           # a tuft and a nose at the front (column 0 side)
        side[2:, 0:6] = True
        vol = blank(5, 6, 10)
        rows = part_rows(vol, front, side)
        self.assertEqual(rows[0], (0, 1, 8, 0, 5))
        self.assertEqual(rows[-1], (3, 3, 6, 3, 4))   # side columns 1..2 are y 4..3: the front
        self.assertNotIn(4, [r[0] for r in rows])     # the tuft only the side view shows
        self.assertEqual(part_rows(vol, front, side, z=(3, 3), x=(0, 4)), [(3, 3, 4, 3, 4)])

    def test_sculpt_keeps_the_spans_and_rounds_the_corners(self):
        m = sculpt(blank(1, 6, 10), [(0, 2, 7, 1, 4)])[0]
        ys, xs = np.nonzero(m)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (2, 7, 1, 4))
        self.assertTrue(m[2:4, 2:8].all(), "the full width at the middle depth")
        self.assertFalse(m[1, 2] or m[4, 7], "corners cut")

    def test_facing_and_decal_stay_on_their_side(self):
        box = np.zeros((3, 4, 5), bool)
        box[:, :, :] = True
        self.assertTrue(facing(box, "front")[:, 3].all() and not facing(box, "front")[:, :3].any())
        self.assertEqual(int(facing(box, "back", depth=2).sum()), 3 * 2 * 5)
        self.assertTrue(facing(box, "left")[:, :, 0].all() and not facing(box, "left")[:, :, 1:].any())
        self.assertTrue(facing(box, "top")[2].all() and not facing(box, "top")[:2].any())
        vol = blank(3, 4, 5)
        vol[box] = (*LEAF, 255)
        front = np.zeros((3, 5, 4), np.uint8)
        front[..., 3] = 255
        front[...] = (*LEAF, 255)
        front[1, 1] = (*DRK, 255)                  # an eye on the middle row
        front[1, 3] = (*RED, 255)
        painted = decal(vol, front, box, "front", colours=[DRK], flat=TYR)
        self.assertEqual(int(painted.sum()), 1)
        self.assertEqual(tuple(vol[1, 3, 1, :3]), TYR)  # z = 1, the front layer, x = 1
        decal(vol, front, box, "front")
        self.assertEqual(tuple(vol[1, 3, 3, :3]), RED)
        rest = vol[:, :3, :, :3].reshape(-1, 3)
        self.assertTrue((rest == LEAF).all(), "nothing runs round to the sides or the back")


def posts(width):
    v = np.zeros((12, 12, 12, 4), np.uint8)
    v[:2, 2:10, 2:10] = (*BARK, 255)
    v[2:10, 2:2 + width, 2:2 + width] = (*BARK, 255)
    v[2:10, 10 - width:10, 10 - width:10] = (*BARK, 255)
    v[10:, 2:10, 2:10] = (*RED, 255)
    return v


class ThinPartTests(unittest.TestCase):
    def test_one_pixel_posts_are_flagged(self):
        # 1-px posts vanish completely at some turns of a sprite stack; 2-px posts never do.
        self.assertEqual(thin_runs(posts(1)[..., 3] > 0), [(2, 9)])
        self.assertEqual(thin_runs(posts(2)[..., 3] > 0), [])

    def test_warning_reaches_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "posts_slices.png"
            save_sheet(posts(1), sheet)
            report = json.loads(subprocess.check_output([sys.executable, str(SCRIPTS / "stack.py"), str(sheet)]))
        self.assertTrue(any("1-px-thin" in w for w in report["warnings"]), report["warnings"])


class SheetTests(unittest.TestCase):
    def test_load_sheet_reads_the_stored_counts(self):
        vol = posts(2)
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "posts_slices.png"
            save_sheet(vol, sheet)
            np.testing.assert_array_equal(load_sheet(sheet), vol)
            np.testing.assert_array_equal(load_sheet(sheet, vol.shape[0]), vol)
            save_sheet([vol, vol[::-1]], sheet)
            frames = load_sheet(sheet)
            self.assertEqual(len(frames), 2)
            np.testing.assert_array_equal(frames[1], vol[::-1])


class StackViewsAndShadingTests(unittest.TestCase):
    def test_stack_views_and_auto_outline_metadata(self):
        L, W = 24, 14
        top = outlined(view(W, L, [(0, 0, W, L, RED), (3, 6, W - 3, 18, DRK)]))
        side = outlined(view(L, 10, [(0, 4, L, 10, RED), (6, 0, 18, 4, DRK)]))
        front = outlined(view(W, 10, [(0, 4, W, 10, RED), (3, 0, W - 3, 4, DRK)]))
        vol, outline = stack_views(top=top, side=side, front=front, back=front, shade_amount=0.2)
        self.assertEqual(outline, "#0f0f14")
        self.assertEqual(dark(vol), 0, "stack_views should strip the 1-px dark view outline")
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "car_slices.png"
            save_sheet(trim(vol), sheet, outline=outline)
            rep_auto = json.loads(subprocess.check_output([
                sys.executable, str(SCRIPTS / "stack.py"), str(sheet),
            ]))
            self.assertEqual(rep_auto["render"]["outline"], "#0f0f14")
            viewer_html = Path(rep_auto["files"]["viewer"]).read_text(encoding="utf-8")
            for needle in ('data-mode="scan"', 'data-mode="exploded"', 'id="exportBtn"', 'buildVolume', '"outline": "#0f0f14"'):
                self.assertIn(needle, viewer_html)
            rep_none = json.loads(subprocess.check_output([
                sys.executable, str(SCRIPTS / "stack.py"), str(sheet), "--outline", "none", "--no-viewer",
            ]))
            self.assertEqual(rep_none["render"]["outline"], "none")
            self.assertNotIn("viewer", rep_none["files"])

    def test_shade_cool_hue_shift_and_neutral_mode(self):
        vol = np.zeros((6, 6, 6, 4), np.uint8)
        vol[:] = (220, 220, 220, 255)
        cool = shade(vol, amount=0.25, cool=0.25)
        r, g, b = (int(v) for v in cool[0, 0, 2, :3])     # lower wall voxel
        self.assertLess(r, g)
        self.assertLess(g, b)
        self.assertLess(b, 220)
        self.assertEqual(tuple(cool[5, 2, 2, :3]), (220, 220, 220), "exposed top stays unshaded")
        neutral = shade(vol, amount=0.25, cool=0.0)
        nr, ng, nb = (int(v) for v in neutral[0, 0, 2, :3])
        self.assertEqual((nr, ng, nb), (nr, nr, nr))


if __name__ == "__main__":
    unittest.main()
