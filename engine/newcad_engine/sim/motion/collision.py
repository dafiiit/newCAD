"""Collision geometry for motion studies.

MuJoCo collides convex shapes. Simple parts are recognised and kept as exact
primitives (box, cylinder, sphere); everything else is split into convex
pieces with CoACD (approximate convex decomposition). Without CoACD a part
falls back to its convex hull, which closes holes and slots, so the study
warns about it.

Runs in the motion pipeline process (it loads the B-rep with build123d).
Coordinates stay in assembly millimetres.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def _faces(shape: Any) -> list[tuple[str, Any]]:
    return [(str(f.geom_type).split(".")[-1].lower(), f) for f in shape.faces()]


def primitive(shape: Any) -> dict[str, Any] | None:
    """An exact primitive for a box, cylinder or sphere shaped solid, else None."""
    if len(shape.solids()) != 1:
        return None
    faces = _faces(shape)
    kinds = sorted(k for k, _ in faces)
    vol = float(shape.volume)
    if kinds == ["plane"] * 6:
        bb = shape.bounding_box()
        size = [bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z]
        if abs(size[0] * size[1] * size[2] - vol) <= 1e-4 * vol:
            c = bb.center()
            return {"type": "box", "pos": [c.X, c.Y, c.Z], "half": [s / 2 for s in size]}
    if kinds == ["cylinder", "plane", "plane"]:
        cyl = next(f for k, f in faces if k == "cylinder")
        try:
            ax = cyl.axis_of_rotation
            r = float(cyl.radius)
        except Exception:
            return None
        d = np.array([ax.direction.X, ax.direction.Y, ax.direction.Z])
        p0 = np.array([ax.position.X, ax.position.Y, ax.position.Z])
        caps = [np.array([c.X, c.Y, c.Z]) for c in (f.center() for k, f in faces if k == "plane")]
        t = sorted(float(np.dot(c - p0, d)) for c in caps)
        h = t[1] - t[0]
        if h > 0 and abs(math.pi * r * r * h - vol) <= 1e-3 * vol:
            mid = p0 + d * (t[0] + t[1]) / 2
            return {"type": "cylinder", "pos": mid.tolist(), "axis": d.tolist(), "radius": r, "half_length": h / 2}
    if kinds == ["sphere"]:
        f = faces[0][1]
        try:
            r = float(f.radius)
            c = f.axis_of_rotation.position
        except Exception:
            return None
        if abs(4 / 3 * math.pi * r ** 3 - vol) <= 1e-3 * vol:
            return {"type": "sphere", "pos": [c.X, c.Y, c.Z], "radius": r}
    return None


def tessellate(shape: Any, tolerance: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    verts, tris = shape.tessellate(tolerance, 0.4)
    return np.array([[p.X, p.Y, p.Z] for p in verts], float), np.array(tris, np.int64)


def coacd_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("coacd") is not None


def decompose(v: np.ndarray, f: np.ndarray, threshold: float = 0.08, max_hulls: int = 24) -> list[np.ndarray]:
    """Convex pieces (their vertices, mm) of a closed triangle mesh."""
    import coacd
    try:
        coacd.set_log_level("error")
    except Exception:
        pass
    parts = coacd.run_coacd(coacd.Mesh(v, f), threshold=threshold, max_convex_hull=max_hulls, preprocess_mode="auto", seed=1)
    return [np.asarray(pv, float) for pv, _ in parts if len(pv) >= 4]


def collision_geoms(brep: str, part: str, warnings: list[str]) -> list[dict[str, Any]]:
    """Collision geoms of one part: one primitive, convex pieces, or its convex hull."""
    from build123d import import_brep
    shape = import_brep(brep)
    prim = primitive(shape)
    if prim:
        return [prim]
    v, f = tessellate(shape)
    if coacd_available():
        try:
            pieces = decompose(v, f)
            if pieces:
                return [{"type": "mesh", "vertices": p.tolist()} for p in pieces]
        except Exception as e:  # fall back to the hull rather than fail the study
            warnings.append(f"{part}: convex decomposition failed ({e}); colliding with its convex hull")
    else:
        warnings.append(f"{part}: CoACD is not installed, so it collides as its convex hull (holes and slots are closed)")
    return [{"type": "mesh", "vertices": v.tolist()}]
