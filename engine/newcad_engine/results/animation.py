"""Motion results → `motion.glb`: an animation track per body, no geometry.

Every body is one glTF node named after its part id, animated with
translation and rotation samplers (LINEAR). The transform moves the part
from where it was modelled, so the viewport applies it directly to the part
meshes it already has from the model GLBs. Like the part GLBs, Z-up
millimetres become glTF Y-up millimetres.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

FLOAT = 5126
# rotation that maps Z-up (x, y, z) to Y-up (x, z, -y)
C = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    """(n, 4) w,x,y,z → (n, 3, 3)."""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], -2)


def mat_to_quat_xyzw(R: np.ndarray) -> np.ndarray:
    """(n, 3, 3) → (n, 4) x,y,z,w (glTF order), sign-continuous over time."""
    out = np.zeros((len(R), 4))
    for i, m in enumerate(R):
        tr = m[0, 0] + m[1, 1] + m[2, 2]
        if tr > 0:
            s = np.sqrt(tr + 1.0) * 2
            q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
            q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
        elif m[1, 1] > m[2, 2]:
            s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
            q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
        else:
            s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
            q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
        q = np.asarray(q)
        q /= np.linalg.norm(q)
        if i and np.dot(q, out[i - 1]) < 0:
            q = -q
        out[i] = q
    return out


def to_view(pose: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(n, 7) MuJoCo poses (m, w-x-y-z quaternion, Z-up) → Y-up mm translations and xyzw quaternions."""
    t = (C @ pose[:, :3].T).T * 1000.0
    R = C @ quat_to_mat(pose[:, 3:7]) @ C.T
    return t, mat_to_quat_xyzw(R)


def write_motion_glb(path: Path, times: np.ndarray, poses: np.ndarray, bodies: list[str], extras: dict[str, Any]) -> int:
    """times: (n,), poses: (n, bodies, 7) in MuJoCo world coordinates."""
    chunks: list[bytes] = []
    accessors: list[dict[str, Any]] = []

    def add(arr: np.ndarray, typ: str, minmax: bool = False) -> int:
        a = np.ascontiguousarray(arr, dtype=np.float32)
        acc: dict[str, Any] = {"bufferView": len(chunks), "componentType": FLOAT, "count": int(len(a)), "type": typ}
        if minmax:
            acc["min"], acc["max"] = [float(a.min())], [float(a.max())]
        chunks.append(a.tobytes())
        accessors.append(acc)
        return len(accessors) - 1

    t_acc = add(np.asarray(times, float), "SCALAR", minmax=True)
    nodes, channels, samplers = [], [], []
    for bi, pid in enumerate(bodies):
        tr, rot = to_view(poses[:, bi, :])
        nodes.append({"name": pid, "translation": tr[0].tolist(), "rotation": rot[0].tolist()})
        for path_name, data, typ in (("translation", tr, "VEC3"), ("rotation", rot, "VEC4")):
            samplers.append({"input": t_acc, "output": add(data, typ), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": bi, "path": path_name}})
    views, offset = [], 0
    for c in chunks:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(c)})
        offset += len(c) + ((-len(c)) % 4)
    blob = b"".join(c + b"\0" * ((-len(c)) % 4) for c in chunks)
    gltf = {
        "asset": {"version": "2.0", "generator": "newcad-engine"},
        "scene": 0, "scenes": [{"nodes": list(range(len(nodes))), "extras": extras}],
        "nodes": nodes, "animations": [{"name": "motion", "channels": channels, "samplers": samplers}],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    data = b"".join([struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)),
                     struct.pack("<I4s", len(js), b"JSON"), js, struct.pack("<I4s", len(blob), b"BIN\0"), blob])
    path.write_bytes(data)
    return len(data)


def read_motion_glb(data: bytes) -> dict[str, Any]:
    """Read back a motion GLB (tests): {"extras", "times", "tracks": {pid: {"translation", "rotation"}}}."""
    jl, _ = struct.unpack_from("<I4s", data, 12)
    gltf = json.loads(data[20:20 + jl])
    bl, _ = struct.unpack_from("<I4s", data, 20 + jl)
    blob = data[28 + jl:28 + jl + bl]

    def arr(ai: int) -> np.ndarray:
        a = gltf["accessors"][ai]
        v = gltf["bufferViews"][a["bufferView"]]
        w = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
        x = np.frombuffer(blob, dtype=np.float32, count=a["count"] * w, offset=v["byteOffset"])
        return x if w == 1 else x.reshape(-1, w)

    anim = gltf["animations"][0]
    tracks: dict[str, dict[str, np.ndarray]] = {}
    times = None
    for ch in anim["channels"]:
        smp = anim["samplers"][ch["sampler"]]
        times = arr(smp["input"])
        tracks.setdefault(gltf["nodes"][ch["target"]["node"]]["name"], {})[ch["target"]["path"]] = arr(smp["output"])
    return {"extras": gltf["scenes"][0].get("extras", {}), "times": times, "tracks": tracks}
