"""Minimal binary glTF writer and reader for part meshes.

Each part becomes one node with one mesh. Besides POSITION and NORMAL, every
vertex carries `_FACE_ID`: the index of the B-rep face it was tessellated
from. Faces are tessellated separately, so the value is constant over each
triangle, which makes it a per-triangle face id. The node's `extras` hold the
stable face tags (`faceTags[i]` belongs to face id i).

Coordinates: build123d is Z-up, glTF is Y-up, so (x, y, z) -> (x, z, -y).
Units stay millimetres.
"""
from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

FLOAT, UINT32 = 5126, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def z_up_to_y_up(v: np.ndarray) -> np.ndarray:
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)


def write_glb(name: str, positions: np.ndarray, normals: np.ndarray, indices: np.ndarray, face_ids: np.ndarray,
              extras: dict[str, Any] | None = None) -> bytes:
    """positions/normals: (n,3) float32 in build123d coordinates; indices: (m,3) uint32; face_ids: (n,) per vertex."""
    pos = z_up_to_y_up(positions.astype(np.float32)).astype(np.float32)
    nor = z_up_to_y_up(normals.astype(np.float32)).astype(np.float32)
    fid = face_ids.astype(np.float32)
    idx = indices.astype(np.uint32).reshape(-1)
    chunks = [pos.tobytes(), nor.tobytes(), fid.tobytes(), idx.tobytes()]
    views, offset = [], 0
    for i, c in enumerate(chunks):
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(c), "target": ELEMENT_ARRAY_BUFFER if i == 3 else ARRAY_BUFFER})
        offset += len(c)
        offset += (-offset) % 4
    blob = b"".join(c + b"\0" * ((-len(c)) % 4) for c in chunks)
    n = len(pos)
    mn = pos.min(axis=0).tolist() if n else [0, 0, 0]
    mx = pos.max(axis=0).tolist() if n else [0, 0, 0]
    gltf = {
        "asset": {"version": "2.0", "generator": "newcad-engine"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0, "extras": extras or {}}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "_FACE_ID": 2}, "indices": 3, "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": FLOAT, "count": n, "type": "VEC3", "min": mn, "max": mx},
            {"bufferView": 1, "componentType": FLOAT, "count": n, "type": "VEC3"},
            {"bufferView": 2, "componentType": FLOAT, "count": n, "type": "SCALAR"},
            {"bufferView": 3, "componentType": UINT32, "count": len(idx), "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return b"".join([
        struct.pack("<4sII", b"glTF", 2, total),
        struct.pack("<I4s", len(js), b"JSON"), js,
        struct.pack("<I4s", len(blob), b"BIN\0"), blob,
    ])


def read_glb(data: bytes) -> dict[str, Any]:
    """Read back a GLB written by write_glb. Returns build123d (Z-up) coordinates."""
    magic, _, _ = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB")
    jl, _ = struct.unpack_from("<I4s", data, 12)
    gltf = json.loads(data[20:20 + jl])
    bl, _ = struct.unpack_from("<I4s", data, 20 + jl)
    blob = data[28 + jl:28 + jl + bl]

    def acc(i: int, dtype: Any, width: int) -> np.ndarray:
        a = gltf["accessors"][i]
        v = gltf["bufferViews"][a["bufferView"]]
        arr = np.frombuffer(blob, dtype=dtype, count=a["count"] * width, offset=v["byteOffset"])
        return arr.reshape(-1, width) if width > 1 else arr

    prim = gltf["meshes"][0]["primitives"][0]
    pos = acc(prim["attributes"]["POSITION"], np.float32, 3)
    pos = np.stack([pos[:, 0], -pos[:, 2], pos[:, 1]], axis=1)
    idx = acc(prim["indices"], np.uint32, 1).reshape(-1, 3)
    fid = acc(prim["attributes"]["_FACE_ID"], np.float32, 1).astype(np.int32)
    return {"positions": pos, "indices": idx, "face_ids": fid, "extras": gltf["nodes"][0].get("extras", {})}
