"""Regression cases for native vs damaged grid selection. Run with pixel_grid.py's dependencies."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "scripts" / "pixel_grid.py"


class PixelGridTests(unittest.TestCase):
    def recover(self, image, *args):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            output = Path(directory) / "art.png"
            image.save(source)
            run = subprocess.run(
                [sys.executable, str(CLI), str(source), "-o", str(output), *args],
                capture_output=True, text=True, check=True,
            )
            with Image.open(output) as result:
                return json.loads(run.stdout), result.copy()

    def test_rectangular_art_is_not_an_editor_canvas(self):
        for count in (1, 4):
            sheet = Image.new("RGB", (48 * count, 64), "white")
            for i in range(count):
                x = 8 + 48 * i
                sheet.paste((20, 75, 105), (x, 16, x + 32, 48))
                sheet.paste((220, 75, 15), (x + 11, 27, x + 21, 37))
            with self.subTest(count=count):
                report, recovered = self.recover(sheet, "--split", "--pixel", "1")
                self.assertNotIn("canvas", report)
                self.assertEqual(len(report["drawings"]), count)
                self.assertEqual(recovered.getchannel("A").histogram()[255], count * 32 * 32)
                self.assertEqual(recovered.getpixel((8, 16)), (20, 75, 105, 255))

    def test_editor_screenshot_still_recovers_the_canvas(self):
        with Image.open(HERE / "files" / "editor_shot.png") as source:
            report, recovered = self.recover(source, "--size", "64x64")
        self.assertEqual(report["canvas"], [214, 52, 438, 438])
        self.assertEqual(recovered.size, (64, 64))
        self.assertEqual(recovered.getbbox(), (12, 3, 52, 60))

    def test_clean_sprite_and_integer_upscale(self):
        with Image.open(HERE / "files" / "mushroom.png") as image:
            native = image.convert("RGBA")
        for scale in (1, 2):
            with self.subTest(scale=scale):
                source = native.resize((native.width * scale, native.height * scale),
                                       Image.Resampling.NEAREST)
                _, result = self.recover(source)
                self.assertEqual(result.size, native.size)
                self.assertEqual(result.tobytes(), native.tobytes())

    def test_automatic_background_preserves_the_outline(self):
        with Image.open(HERE / "files" / "mushroom.png") as image:
            native = image.convert("RGBA")
        opaque = Image.new("RGBA", native.size, (42, 42, 42, 255))
        opaque.alpha_composite(native)
        for mode in ("L", "RGB"):
            for resample in (Image.Resampling.NEAREST, Image.Resampling.BILINEAR):
                with self.subTest(mode=mode, resampling=resample.name):
                    source = opaque.convert(mode).resize((95, 95), resample)
                    report, result = self.recover(source)
                    self.assertEqual(report["native_size"], list(native.size))
                    self.assertEqual(result.getchannel("A").tobytes(), native.getchannel("A").tobytes())

    def test_bilinear_recovery_restores_colours_and_one_pixel_eyes(self):
        with Image.open(HERE / "files" / "mushroom.png") as image:
            native = image.convert("RGBA")
        flat = Image.new("RGBA", native.size, (42, 42, 42, 255))
        flat.alpha_composite(native)
        for source in (native, flat.convert("RGB")):
            with self.subTest(mode=source.mode):
                report, result = self.recover(source.resize((95, 95), Image.Resampling.BILINEAR))
                self.assertIn("bilinear_edge_error", report)
                self.assertEqual(result.size, native.size)
                self.assertEqual(result.tobytes(), native.tobytes())

    def test_low_colour_blur_and_size_override(self):
        with Image.open(HERE / "files" / "mushroom.png") as image:
            opaque = Image.new("RGBA", image.size, (42, 42, 42, 255))
            opaque.alpha_composite(image.convert("RGBA"))
        # Grayscale keeps a bilinear upscale within the old "clean" colour limit.
        source = opaque.convert("L").resize((95, 95), Image.Resampling.BILINEAR)
        report, result = self.recover(source, "--bg", "none")
        self.assertEqual(result.size, opaque.size)
        self.assertEqual(report["grid_candidates"]["input_size"], [95, 95])
        self.assertEqual(report["grid_candidates"]["fixer_size"], list(opaque.size))
        self.assertTrue(report["notes"])
        forced, result = self.recover(source, "--size", "95x95", "--bg", "none")
        self.assertEqual(result.size, source.size)
        self.assertEqual(forced["method"], "size")
        self.assertNotIn("grid_candidates", forced)

    def test_known_grid_with_only_two_blended_samples_per_cell(self):
        with Image.open(HERE / "files" / "mushroom.png") as image:
            native = image.convert("RGBA")
        flat = Image.new("RGBA", native.size, (42, 42, 42, 255))
        flat.alpha_composite(native)
        for source in (flat.convert("RGB"), native):
            with self.subTest(mode=source.mode):
                blurred = source.resize((32, 32), Image.Resampling.BILINEAR)
                report, result = self.recover(blurred, "--size", "16x16")
                self.assertIn("bilinear_edge_error", report)
                self.assertEqual(result.getchannel("A").tobytes(), native.getchannel("A").tobytes())
                np.testing.assert_allclose(np.asarray(result), np.asarray(native), rtol=0, atol=1)

    def test_split_guesses_views_of_a_tall_prop(self):
        # A tree's side view is the tallest drawing, so "tallest = top" picked the wrong views.
        def box(w, h, colour):
            return Image.new("RGBA", (w * 8, h * 8), colour + (255,))
        sheet = Image.new("RGBA", (4 * 200 + 40, 420), (250, 250, 250, 255))
        top, side = box(18, 18, (60, 150, 70)), box(18, 42, (60, 150, 70))
        for i, im in enumerate((top, side, side, side)):
            sheet.paste(im, (40 + i * 200, 40))
        report, _ = self.recover(sheet.convert("RGB"), "--split")
        guesses = [d["view_guess"] for d in report["drawings"]]
        self.assertEqual(guesses, ["top", "side", "front or back", "front or back"])

    def test_split_does_not_find_a_top_view_in_a_character_pair(self):
        # A front and a back of a standing character (same height) were labelled "top" and "side".
        def box(w, h, colour):
            return Image.new("RGBA", (w * 6, h * 6), colour + (255,))
        sheet = Image.new("RGBA", (2 * 200 + 40, 320), (20, 20, 22, 255))
        for i, w in enumerate((20, 21)):
            sheet.paste(box(w, 41, (200, 210, 230)), (40 + i * 200, 40))
        report, _ = self.recover(sheet.convert("RGB"), "--split")
        self.assertEqual([d.get("view_guess") for d in report["drawings"]], ["front, back or side"] * 2)


    def test_split_keeps_a_side_view_apart_from_a_front_view(self):
        # In a ring of directions a side view (half the pixels of the front view) nearly touches
        # the front view, and was merged into it like a detached sparkle. A real sparkle still joins.
        import pixel_grid
        m = np.zeros((60, 80), bool)
        m[10:50, 10:30] = True                     # front view, 800 px
        m[10:50, 33:43] = True                     # side view, 400 px, 3 px away
        m[5:7, 46:48] = True                       # a sparkle 3 px from the side view
        boxes, _ = pixel_grid.drawings(m)
        self.assertEqual(sorted((b[2], b[3]) for b in boxes), [(15, 45), (20, 40)])

    def test_split_guesses_views_on_1x4_and_2x2_model_sheets(self):
        # Evenly spaced 1x4 and 2x2 orthographic model sheets used to be misclassified as
        # animation grids, which suppressed view_guess for all four drawings.
        def box(w, h, colour):
            return Image.new("RGBA", (w * 6, h * 6), colour + (255,))

        top, side = box(20, 26, (60, 150, 70)), box(26, 22, (110, 70, 40))
        front, back = box(20, 22, (200, 80, 60)), box(20, 22, (80, 100, 190))

        row_sheet = Image.new("RGBA", (4 * 220 + 60, 260), (250, 250, 250, 255))
        for i, im in enumerate((top, side, front, back)):
            row_sheet.paste(im, (40 + i * 220, 40))
        rep_row, _ = self.recover(row_sheet.convert("RGB"), "--split")
        self.assertNotIn("grid", rep_row)
        self.assertEqual([d.get("view_guess") for d in rep_row["drawings"]],
                         ["top", "side", "front or back", "front or back"])

        grid_sheet = Image.new("RGBA", (540, 540), (250, 250, 250, 255))
        for im, (x, y) in zip((top, side, front, back), ((40, 40), (300, 40), (40, 300), (300, 300))):
            grid_sheet.paste(im, (x, y))
        rep_2x2, _ = self.recover(grid_sheet.convert("RGB"), "--split")
        self.assertNotIn("grid", rep_2x2)
        self.assertEqual([d.get("view_guess") for d in rep_2x2["drawings"]],
                         ["top", "side", "front or back", "front or back"])

    def test_split_refines_per_view_grids_and_peels_jpeg_halo(self):
        # AI-generated 4-view sheets often have slight per-view scale/phase drift plus bilinear
        # softening and JPEG compression on a pale backdrop. The outer grey halo must be peeled so
        # strip_outline() still reaches the real dark outline, and per-view grids must recover sizes.
        sys.path.insert(0, str(HERE.parent / "scripts"))
        from voxlib import load, stack_views

        def pixel_view(w, h, fill, roof, accent):
            a = np.zeros((h, w, 4), np.uint8)
            a[1:-1, 1:-1] = (*fill, 255)
            # 1-px and 2-px pixel-art details (roof bands, windows, trim) so a real pixel grid exists
            for r in range(2, h // 2):
                a[r, 2:-2] = (*(roof if r % 2 == 0 else tuple(max(0, c - 25) for c in roof)), 255)
            for c in range(3, w - 3, 4):
                a[h // 2 + 2:h - 3, c:c + 2] = (*accent, 255)
            a[h // 2, 1:-1] = (120, 80, 50, 255)
            a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = (18, 18, 26, 255)
            return Image.fromarray(a)

        views = [
            pixel_view(22, 30, (65, 145, 75), (70, 95, 155), (230, 200, 90)),   # top: 22x30
            pixel_view(30, 24, (220, 195, 165), (70, 95, 155), (90, 130, 175)), # side: 30x24
            pixel_view(22, 24, (220, 195, 165), (175, 70, 60), (90, 130, 175)), # front: 22x24
            pixel_view(22, 24, (220, 195, 165), (175, 70, 60), (120, 80, 50)),  # back: 22x24
        ]
        bg = (248, 248, 246)
        sheet = Image.new("RGB", (880, 260), bg)
        scales = (5.3, 5.4, 5.2, 5.35)
        xs = (30, 220, 460, 660)
        for im, sc, x0 in zip(views, scales, xs):
            nw, nh = int(round(im.width * sc)), int(round(im.height * sc))
            up = im.resize((nw, nh), Image.Resampling.BILINEAR)
            patch = Image.new("RGBA", (nw, nh), (*bg, 255))
            patch.alpha_composite(up)
            sheet.paste(patch.convert("RGB"), (x0, 45))

        with tempfile.TemporaryDirectory() as directory:
            src_jpg = Path(directory) / "ai_sheet.jpg"
            out_png = Path(directory) / "views.png"
            sheet.save(src_jpg, quality=85)
            run = subprocess.run(
                [sys.executable, str(CLI), str(src_jpg), "-o", str(out_png), "--split"],
                capture_output=True, text=True, check=True,
            )
            rep = json.loads(run.stdout)
            self.assertNotIn("grid", rep)
            self.assertEqual([d.get("view_guess") for d in rep["drawings"]],
                             ["top", "side", "front or back", "front or back"])
            recovered = [load(d["file"]) for d in rep["drawings"]]
            for got, want in zip(recovered, views):
                self.assertLessEqual(abs(got.shape[1] - want.width), 1)
                self.assertLessEqual(abs(got.shape[0] - want.height), 1)
            vol, outline = stack_views(top=recovered[0], side=recovered[1],
                                       front=recovered[2], back=recovered[3], shade_amount=0)
            self.assertIsNotNone(outline, "dark outline was masked by an unpeeled backdrop halo")
            dark_left = int(((vol[..., :3].astype(int).mean(-1) < 35) & (vol[..., 3] > 0)).sum())
            self.assertEqual(dark_left, 0, "baked dark outline voxels survived into the volume")

if __name__ == "__main__":
    unittest.main()
