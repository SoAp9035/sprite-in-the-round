"""Exercise the static export through the normal slice-sheet CLI."""
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from voxlib import save_sheet


class GlbTests(unittest.TestCase):
    def test_coloured_surface_with_through_hole(self):
        vol = np.zeros((3, 3, 3, 4), dtype=np.uint8)
        vol[:] = (200, 120, 33, 255)
        vol[:, 2] = (12, 40, 80, 255)  # front of the model
        vol[:, 1, 1] = 0
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "test_slices.png"
            save_sheet(vol, sheet)
            report = json.loads(subprocess.check_output([sys.executable, str(SCRIPTS / "stack.py"), str(sheet)]))
            data = Path(report["files"]["glb"]).read_bytes()
        self.assertEqual(struct.unpack_from("<4sII", data), (b"glTF", 2, len(data)))
        length, tag = struct.unpack_from("<I4s", data, 12)
        self.assertEqual(tag, b"JSON")
        doc = json.loads(data[20:20 + length])
        binary = memoryview(data)[28 + length:]
        self.assertEqual(struct.unpack_from("<I4s", data, 20 + length), (len(binary), b"BIN\0"))
        self.assertIn("KHR_materials_unlit", doc["materials"][0]["extensions"])
        self.assertNotIn("animations", doc)
        primitive = doc["meshes"][0]["primitives"][0]

        def read_attribute(name):
            accessor = doc["accessors"][primitive["attributes"][name]]
            view = doc["bufferViews"][accessor["bufferView"]]
            width = {"VEC2": 2, "VEC3": 3}[accessor["type"]]
            return np.ndarray((accessor["count"], width), dtype="<f4", buffer=binary,
                              offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
                              strides=(view["byteStride"], 4))

        pos = read_attribute("POSITION") * 16 + [1.5, 0, 1.5]
        normals, uv = read_attribute("NORMAL"), read_attribute("TEXCOORD_0")
        texture = doc["textures"][doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
        sampler = doc["samplers"][texture["sampler"]]
        self.assertEqual((sampler["minFilter"], sampler["magFilter"]), (9728, 9728))
        view = doc["bufferViews"][doc["images"][texture["source"]]["bufferView"]]
        start = view["byteOffset"]
        palette = np.array(Image.open(io.BytesIO(binary[start:start + view["byteLength"]])))
        texels = np.floor(uv * palette.shape[1::-1]).astype(int)
        colours = palette[texels[:, 1], texels[:, 0]]
        acc = doc["accessors"][primitive["indices"]]
        offset = doc["bufferViews"][acc["bufferView"]]["byteOffset"]
        tris = np.frombuffer(binary, dtype={5123: "<u2", 5125: "<u4"}[acc["componentType"]],
                             count=acc["count"], offset=offset).reshape(-1, 3)
        total_area = 0
        for tri in tris:
            a, b, c = pos[tri]
            area_normal = np.cross(b - a, c - a)
            total_area += np.linalg.norm(area_normal) / 2
            normal = area_normal / np.linalg.norm(area_normal)
            np.testing.assert_array_equal(normals[tri], np.tile(normal, (3, 1)))
            # Probe either side of each triangle. Outside includes the shaft of the hole.
            center = (a + b + c) / 3
            x, y, z = np.floor(center - normal * 0.01).astype(int).clip(0, 2)
            rgb = vol[y, z, x, :3]
            self.assertEqual(vol[y, z, x, 3], 255)
            np.testing.assert_array_equal(colours[tri], np.tile(rgb, (3, 1)))
            x, y, z = np.floor(center + normal * 0.01).astype(int)
            if all(0 <= i < 3 for i in (x, y, z)):
                self.assertEqual(vol[y, z, x, 3], 0)
        self.assertEqual(total_area, 64)

    def test_obj_matches_the_volume(self):
        vol = np.zeros((3, 3, 3, 4), dtype=np.uint8)
        vol[:] = (200, 120, 33, 255)
        vol[:, 2] = (12, 40, 80, 255)  # front of the model
        vol[:, 1, 1] = 0
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "ışık_slices.png"
            save_sheet(vol, sheet)
            report = json.loads(subprocess.check_output([sys.executable, str(SCRIPTS / "stack.py"), str(sheet)]))
            obj, mtl, png = (Path(p) for p in report["files"]["obj"])
            self.assertEqual(obj.name, "ışık.obj")
            lines = obj.read_text(encoding="utf-8").splitlines()
            self.assertIn(f"map_Kd {png.name}", mtl.read_text(encoding="utf-8"))
            palette = np.array(Image.open(png))
        self.assertIn(f"mtllib {mtl.name}", lines)
        rows = lambda tag: np.array([[float(v) for v in l.split()[1:]] for l in lines if l.startswith(tag + " ")])
        pos, uv, nrm = rows("v") * 16 + [1.5, 0, 1.5], rows("vt"), rows("vn")
        faces = [[tuple(int(i) - 1 for i in c.split("/")) for c in l.split()[1:]] for l in lines if l.startswith("f ")]
        total_area = 0
        for face in faces:
            self.assertEqual(len(face), 4)
            p = pos[[c[0] for c in face]]
            area_normal = np.cross(p[1] - p[0], p[2] - p[0])
            total_area += np.linalg.norm(area_normal)
            normal = area_normal / np.linalg.norm(area_normal)
            for c in face:  # counter-clockwise winding agrees with the stored normal
                np.testing.assert_array_equal(nrm[c[2]], normal)
            texel = np.floor([uv[face[0][1]][0] * palette.shape[1], (1 - uv[face[0][1]][1]) * palette.shape[0]]).astype(int)
            x, y, z = np.floor(p.mean(0) - normal * 0.01).astype(int).clip(0, 2)
            self.assertEqual(vol[y, z, x, 3], 255)
            np.testing.assert_array_equal(palette[texel[1], texel[0], :3], vol[y, z, x, :3])
        self.assertEqual(total_area, 64)


    def test_padded_mesh_uses_occupied_size_and_preserves_the_pivot(self):
        vol = np.zeros((10, 8, 8, 4), dtype=np.uint8)
        vol[2:8, 2:5, 1:5] = (90, 160, 200, 255)
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "padded_slices.png"
            save_sheet(vol, sheet)
            for args, ppm in ((["--height", "1"], 6), (["--ppm", "12"], 12)):
                output = subprocess.check_output([sys.executable, str(SCRIPTS / "stack.py"), str(sheet), *args])
                report = json.loads(output)
                np.testing.assert_allclose(report["mesh_size_m"], np.array([4, 3, 6]) / ppm, atol=0.0005)
                data = Path(report["files"]["glb"]).read_bytes()
                length = struct.unpack_from("<I", data, 12)[0]
                position = json.loads(data[20:20 + length])["accessors"][0]
                obj = Path(report["files"]["obj"][0]).read_text()
                vertices = np.array([line.split()[1:] for line in obj.splitlines() if line.startswith("v ")], float)
                for bounds in ((position["min"], position["max"]), (vertices.min(0), vertices.max(0))):
                    # The OBJ writer stores six significant digits.
                    np.testing.assert_allclose(np.asarray(bounds) * ppm, [[-3, 2, -2], [1, 8, 1]], rtol=5e-6)

    def test_height_scales_both_meshes(self):
        # At 16 art px per metre a 38-layer character imported 2.4 m tall; --height sets the size.
        vol = np.zeros((8, 2, 4, 4), dtype=np.uint8)
        vol[:] = (90, 160, 200, 255)
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "tall_slices.png"
            save_sheet(vol, sheet)
            out = subprocess.check_output([sys.executable, str(SCRIPTS / "stack.py"), str(sheet), "--height", "2"])
            report = json.loads(out)
            data = Path(report["files"]["glb"]).read_bytes()
            obj = Path(report["files"]["obj"][0]).read_text()
        self.assertEqual(report["mesh_size_m"], [1.0, 0.5, 2.0])
        length = struct.unpack_from("<I", data, 12)[0]
        doc = json.loads(data[20:20 + length])
        position = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
        self.assertAlmostEqual(position["max"][1] - position["min"][1], 2.0, places=5)
        ys = [float(line.split()[2]) for line in obj.splitlines() if line.startswith("v ")]
        self.assertAlmostEqual(max(ys) - min(ys), 2.0, places=5)

if __name__ == "__main__":
    unittest.main()
