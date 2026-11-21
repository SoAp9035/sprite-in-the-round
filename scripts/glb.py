"""Write a static, flat-coloured mesh (glTF binary or Wavefront OBJ) from vol[height, depth, width, RGBA]."""
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def _rectangles(plane):
    """Consume a face mask, merging coplanar rectangles of the same packed colour."""
    for u, v in zip(*np.nonzero(plane)):
        colour = plane[u, v]
        if not colour:  # consumed by an earlier rectangle
            continue
        end_v = v + 1
        while end_v < plane.shape[1] and plane[u, end_v] == colour:
            end_v += 1
        end_u = u + 1
        while end_u < plane.shape[0] and np.all(plane[end_u, v:end_v] == colour):
            end_u += 1
        plane[u:end_u, v:end_v] = 0
        yield u, v, end_u, end_v, colour


def _surface(vol, ppm=16):
    # glTF X points right, Y up, Z towards the viewer. Reserve zero for empty space.
    rgba = vol.transpose(2, 0, 1, 3)
    keys = rgba[..., :3].astype(np.int32) @ [65536, 256, 1] + 1
    keys[rgba[..., 3] < 128] = 0
    quads, colours, normals = [], [], []
    for axis in range(3):
        u_axis, v_axis = (axis + 1) % 3, (axis + 2) % 3
        layers = keys.transpose(axis, u_axis, v_axis)
        for sign in (-1, 1):
            normal = [0, 0, 0]
            normal[axis] = sign
            for depth, layer in enumerate(layers):
                adjacent = depth + sign
                faces = (np.where(layers[adjacent] == 0, layer, 0)
                         if 0 <= adjacent < len(layers) else layer.copy())
                for u, v, end_u, end_v, colour in _rectangles(faces):
                    corners = np.empty((4, 3), dtype=np.float32)
                    corners[:, axis] = depth + (sign > 0)
                    corners[:, u_axis] = (u, end_u, end_u, u)
                    corners[:, v_axis] = (v, v, end_v, end_v)
                    quads.append(corners if sign > 0 else corners[::-1])
                    normals.append(normal)
                    colours.append(colour - 1)
    if not quads:
        raise ValueError("cannot export an empty volume")
    positions = np.asarray(quads)
    positions -= (keys.shape[0] / 2, 0, keys.shape[2] / 2)
    positions /= ppm  # art pixels per metre (16 by default)
    palette, indices = np.unique(colours, return_inverse=True)
    # Each face uses one texel. Inset its UVs so even a viewer that forces
    # linear filtering sees the palette colour at the centre of the face.
    width = int(np.ceil(np.sqrt(len(palette))))
    height = (len(palette) + width - 1) // width
    pixels = np.zeros((width * height, 3), np.uint8)
    pixels[:len(palette)] = (palette[:, None] >> [16, 8, 0]) & 255
    texels = np.column_stack((indices % width, indices // width))
    vertices = np.empty((len(quads), 4, 8), dtype="<f4")
    vertices[..., :3] = positions
    vertices[..., 3:6] = np.asarray(normals)[:, None, :]
    # A tiny square also gives importers a nondegenerate tangent basis.
    uv = np.array([[0.49, 0.49], [0.51, 0.49], [0.51, 0.51], [0.49, 0.51]])
    vertices[..., 6:] = (texels[:, None, :] + uv) / [width, height]
    return vertices.reshape(-1, 8), Image.fromarray(pixels.reshape(height, width, 3))


def write_glb(path, vol, ppm=16):
    vertices, palette = _surface(vol, ppm)
    n = len(vertices)
    # glTF reserves the maximum representable index for primitive restart.
    short = n <= 65535
    indices = (np.arange(0, n, 4, dtype="<u4")[:, None] + [0, 1, 2, 0, 2, 3])
    indices = indices.astype("<u2" if short else "<u4")
    png = io.BytesIO()
    palette.save(png, format="PNG")
    data = vertices.tobytes() + indices.tobytes() + png.getvalue()
    data += bytes(-len(data) % 4)
    attrs = [{"bufferView": 0, "byteOffset": offset, "componentType": 5126, "count": n, "type": kind}
             for offset, kind in ((0, "VEC3"), (12, "VEC3"), (24, "VEC2"))]
    attrs[0].update(min=vertices[:, :3].min(0).tolist(), max=vertices[:, :3].max(0).tolist())
    attrs.append({"bufferView": 1, "componentType": 5123 if short else 5125,
                  "count": indices.size, "type": "SCALAR"})
    doc = {
        "asset": {"version": "2.0", "generator": "sprite-in-the-round"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": Path(path).stem, "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                                    "indices": 3, "material": 0}]}],
        "extensionsUsed": ["KHR_materials_unlit"],
        "materials": [{"name": "Sprite palette", "extensions": {"KHR_materials_unlit": {}},
                       "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0, "roughnessFactor": 1}}],
        "textures": [{"sampler": 0, "source": 0}],
        "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"bufferView": 2, "mimeType": "image/png"}],
        "accessors": attrs, "buffers": [{"byteLength": len(data)}],
        "bufferViews": [{"buffer": 0, "byteLength": vertices.nbytes, "byteStride": 32, "target": 34962},
                        {"buffer": 0, "byteOffset": vertices.nbytes, "byteLength": indices.nbytes, "target": 34963},
                        {"buffer": 0, "byteOffset": vertices.nbytes + indices.nbytes, "byteLength": png.tell()}],
    }
    header = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    header += b" " * (-len(header) % 4)
    with open(path, "wb") as out:
        out.write(struct.pack("<4sII", b"glTF", 2, 28 + len(header) + len(data)))
        out.write(struct.pack("<I4s", len(header), b"JSON") + header)
        out.write(struct.pack("<I4s", len(data), b"BIN\0") + data)


def write_obj(path, vol, ppm=16):
    """Write the same surface as write_glb as Wavefront OBJ + MTL + palette PNG, for tools without
    glTF import. Same axes and scale: Y up, front +Z, ppm art pixels per metre, origin at the
    centre of the footprint on the ground. Returns the paths written (obj, mtl, png)."""
    vertices, palette = _surface(vol, ppm)
    path = Path(path)
    mtl, png = path.with_suffix(".mtl"), path.with_name(path.stem + "_palette.png")
    palette.save(png)
    pos, pi = np.unique(vertices[:, :3], axis=0, return_inverse=True)
    nrm, ni = np.unique(vertices[:, 3:6], axis=0, return_inverse=True)
    uv, ti = np.unique(vertices[:, 6:], axis=0, return_inverse=True)
    pi, ni, ti = (i.reshape(-1, 4) + 1 for i in (pi, ni, ti))   # one quad per face, OBJ is 1-based
    lines = [f"# sprite-in-the-round: flat-coloured voxel surface, Y up, front +Z, {ppm:g} art px per metre",
             f"mtllib {mtl.name}", f"o {path.stem}"]
    lines += [f"v {x:.6g} {y:.6g} {z:.6g}" for x, y, z in pos]
    # glTF puts v = 0 at the top of the image, OBJ at the bottom
    lines += [f"vt {u:.6g} {1 - v:.6g}" for u, v in uv]
    lines += [f"vn {x:.6g} {y:.6g} {z:.6g}" for x, y, z in nrm]
    lines += ["usemtl palette", "s off"]
    lines += ["f " + " ".join(f"{a}/{b}/{c}" for a, b, c in zip(p, t, n)) for p, t, n in zip(pi, ti, ni)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Kd 1 lets the texture carry the colour; illum 1 = no specular. Each face samples the middle
    # of its palette texel, so linear filtering still shows the exact colour.
    mtl.write_text("# sprite-in-the-round palette material\nnewmtl palette\nKa 0 0 0\nKd 1 1 1\nKs 0 0 0\n"
                   f"d 1\nillum 1\nmap_Kd {png.name}\n", encoding="utf-8")
    return [str(path), str(mtl), str(png)]
