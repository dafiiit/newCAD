"""Simulation results → files the app can show.

- `field.glb`: the outer surface of the mesh as one binary glTF mesh. Next to
  POSITION and NORMAL every vertex carries the raw result values as custom
  attributes (`_VON_MISES`, `_SAFETY`, `_DISP`, `_TEMP`, `_MODE1`…). The
  viewport applies the colour map in its shader, so changing the range needs
  no engine round trip. `_FACE_ID` indexes `extras.faceTags` ("part/tag"),
  so a click on the result maps to the same B-rep face as in the model view.
- `result.vtu`: the full volume mesh with nodal fields for ParaView.

Coordinates: like the part GLBs, Z-up millimetres become glTF Y-up.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from ..geometry.glb import z_up_to_y_up

FLOAT, UINT32 = 5126, 5125
T6_SPLIT = [(0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5)]


def _opposite(mesh: Any) -> dict[tuple[int, int, int], int]:
    """Sorted corner triple of every element face → the element's fourth (opposite) corner."""
    T = mesh.tets[:, :4]
    opp: dict[tuple[int, int, int], int] = {}
    for a, b, c, d in ((0, 1, 2, 3), (0, 1, 3, 2), (1, 2, 3, 0), (0, 2, 3, 1)):
        tri = np.sort(T[:, [a, b, c]], axis=1)
        for row, o in zip(tri.tolist(), T[:, d].tolist()):
            opp[(row[0], row[1], row[2])] = o
    return opp


def _outward(mesh: Any, tris: np.ndarray, opp: dict[tuple[int, int, int], int]) -> np.ndarray:
    """Flip triangles whose normal points into the solid (Gmsh doesn't guarantee surface orientation)."""
    tris = tris.copy()
    X = mesh.nodes
    n = np.cross(X[tris[:, 1]] - X[tris[:, 0]], X[tris[:, 2]] - X[tris[:, 0]])
    o = np.array([opp.get(tuple(sorted(t)), t[0]) for t in tris[:, :3].tolist()])
    flip = np.einsum("ij,ij->i", n, X[o] - X[tris[:, 0]]) > 0
    if tris.shape[1] == 6:
        tris[flip] = tris[flip][:, [0, 2, 1, 5, 4, 3]]
    else:
        tris[flip] = tris[flip][:, [0, 2, 1]]
    return tris


def surface(mesh: Any) -> dict[str, Any]:
    """Exterior surface, oriented outward, one vertex copy per tagged face so face ids stay constant per triangle."""
    opp = _opposite(mesh)
    pos, nodes_of, idx, fid, tags = [], [], [], [], []
    base = 0
    for key, tris in sorted(mesh.faces.items()):
        if not mesh.exterior.get(key, True):
            continue
        tris = _outward(mesh, tris, opp)
        lin = np.concatenate([tris[:, list(s)] for s in T6_SPLIT]) if tris.shape[1] == 6 else tris
        uniq, inv = np.unique(lin.reshape(-1), return_inverse=True)
        nodes_of.append(uniq)
        pos.append(mesh.nodes[uniq])
        idx.append(inv.reshape(-1, 3) + base)
        fid.append(np.full(len(uniq), len(tags), dtype=np.float32))
        tags.append(f"{key[0]}/{key[1]}")
        base += len(uniq)
    P = np.concatenate(pos)
    I = np.concatenate(idx)
    N = np.zeros_like(P)
    tn = np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]])
    for k in range(3):
        np.add.at(N, I[:, k], tn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.divide(N, ln, out=np.zeros_like(N), where=ln > 0)
    return {"positions": P, "normals": N, "indices": I, "nodes": np.concatenate(nodes_of), "face_ids": np.concatenate(fid), "tags": tags}


def write_field_glb(path: Path, surf: dict[str, Any], scalars: dict[str, np.ndarray], vectors: dict[str, np.ndarray],
                    extras: dict[str, Any]) -> int:
    """scalars/vectors are nodal arrays over the whole mesh; they are sampled at the surface vertices."""
    nodes = surf["nodes"]
    attrs: list[tuple[str, np.ndarray, str]] = [
        ("POSITION", z_up_to_y_up(surf["positions"]).astype(np.float32), "VEC3"),
        ("NORMAL", z_up_to_y_up(surf["normals"]).astype(np.float32), "VEC3"),
        ("_FACE_ID", surf["face_ids"].astype(np.float32), "SCALAR"),
    ]
    for name, arr in scalars.items():
        attrs.append((f"_{name.upper()}", arr[nodes].astype(np.float32), "SCALAR"))
    for name, arr in vectors.items():
        attrs.append((f"_{name.upper()}", z_up_to_y_up(arr[nodes]).astype(np.float32), "VEC3"))
    idx = surf["indices"].astype(np.uint32).reshape(-1)
    chunks = [a.tobytes() for _, a, _ in attrs] + [idx.tobytes()]
    views, accessors, offset = [], [], 0
    for i, c in enumerate(chunks):
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(c), "target": 34963 if i == len(chunks) - 1 else 34962})
        offset += len(c) + ((-len(c)) % 4)
    for i, (name, a, typ) in enumerate(attrs):
        acc: dict[str, Any] = {"bufferView": i, "componentType": FLOAT, "count": len(a), "type": typ}
        if name == "POSITION":
            acc["min"], acc["max"] = a.min(axis=0).tolist(), a.max(axis=0).tolist()
        accessors.append(acc)
    accessors.append({"bufferView": len(attrs), "componentType": UINT32, "count": len(idx), "type": "SCALAR"})
    blob = b"".join(c + b"\0" * ((-len(c)) % 4) for c in chunks)
    gltf = {
        "asset": {"version": "2.0", "generator": "newcad-engine"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "result", "mesh": 0, "extras": {**extras, "faceTags": surf["tags"]}}],
        "meshes": [{"name": "result", "primitives": [{"attributes": {n: i for i, (n, _, _) in enumerate(attrs)}, "indices": len(attrs), "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    data = b"".join([struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)),
                     struct.pack("<I4s", len(js), b"JSON"), js, struct.pack("<I4s", len(blob), b"BIN\0"), blob])
    path.write_bytes(data)
    return len(data)


def read_field_glb(data: bytes) -> dict[str, Any]:
    """Read back a field GLB (for tests and the MCP summary). Arrays keep glTF (Y-up) coordinates."""
    jl, _ = struct.unpack_from("<I4s", data, 12)
    gltf = json.loads(data[20:20 + jl])
    bl, _ = struct.unpack_from("<I4s", data, 20 + jl)
    blob = data[28 + jl:28 + jl + bl]
    prim = gltf["meshes"][0]["primitives"][0]
    out: dict[str, Any] = {"extras": gltf["nodes"][0]["extras"], "attributes": {}}
    for name, ai in prim["attributes"].items():
        a = gltf["accessors"][ai]
        v = gltf["bufferViews"][a["bufferView"]]
        w = 3 if a["type"] == "VEC3" else 1
        arr = np.frombuffer(blob, dtype=np.float32, count=a["count"] * w, offset=v["byteOffset"])
        out["attributes"][name] = arr.reshape(-1, 3) if w == 3 else arr
    a = gltf["accessors"][prim["indices"]]
    v = gltf["bufferViews"][a["bufferView"]]
    out["indices"] = np.frombuffer(blob, dtype=np.uint32, count=a["count"], offset=v["byteOffset"]).reshape(-1, 3)
    return out


def write_vtu(path: Path, mesh: Any, point_data: dict[str, np.ndarray]) -> None:
    import meshio
    cell = "tetra10" if mesh.order == 2 else "tetra"
    m = meshio.Mesh(mesh.nodes, [(cell, mesh.tets)], point_data={k: np.asarray(v) for k, v in point_data.items()},
                    cell_data={"part": [mesh.tet_part.astype(np.int32)]})
    meshio.write(str(path), m, file_format="vtu", binary=True)
