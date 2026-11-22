"""Server-side snapshot renderer so a model (or a vision-capable agent) can look at its own result.

Pure numpy + Pillow: orthographic projection, painter's algorithm, Lambert
shading. It is a quick look, not a production renderer.
"""
from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

# camera direction (from the model towards the eye), build123d coordinates, Z up
VIEWS: dict[str, tuple[float, float]] = {  # azimuth (deg, from -Y towards +X), elevation (deg)
    "iso": (35.0, 28.0),
    "front": (0.0, 0.0),
    "back": (180.0, 0.0),
    "right": (90.0, 0.0),
    "left": (-90.0, 0.0),
    "side": (90.0, 0.0),
    "top": (0.0, 89.9),
    "bottom": (0.0, -89.9),
}


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    if len(c) != 6:
        return np.array([180, 190, 205], dtype=float)
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def render(meshes: list[dict[str, Any]], view: str = "iso", size: tuple[int, int] = (800, 600),
           highlight: str | None = None) -> bytes:
    """meshes: [{"id", "color", "positions" (n,3), "indices" (m,3)}] → PNG bytes."""
    az, el = VIEWS.get(view, VIEWS["iso"])
    a, e = math.radians(az), math.radians(el)
    eye = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
    up = np.array([0.0, 0.0, 1.0]) if abs(el) < 89 else np.array([0.0, 1.0, 0.0])
    right = np.cross(up, eye)
    right /= np.linalg.norm(right)
    up2 = np.cross(eye, right)
    light = eye * 0.7 + up2 * 0.5 - right * 0.3
    light /= np.linalg.norm(light)

    W, H = size
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    tris, depth, cols = [], [], []
    allp = [m["positions"] for m in meshes if len(m["positions"])]
    if not allp:
        draw.text((W // 2 - 40, H // 2), "No geometry", fill=(120, 120, 120))
        return _png(img)
    P = np.concatenate(allp)
    center = (P.min(axis=0) + P.max(axis=0)) / 2
    for m in meshes:
        pos, idx = m["positions"], m["indices"]
        if not len(idx):
            continue
        v = pos[idx]  # (t,3,3)
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
        facing = n @ eye
        keep = facing > -1e-6
        v, n = v[keep], n[keep]
        shade = 0.45 + 0.55 * np.clip(n @ light, 0, 1)
        base = _hex(m.get("color", "#B4C2D6"))
        if highlight and m.get("id") == highlight:
            base = base * 0.55 + np.array([29, 78, 216]) * 0.45
        c = np.clip(base[None, :] * shade[:, None], 0, 255)
        rel = v - center
        sx, sy, sz = rel @ right, rel @ up2, rel @ eye
        tris.append(np.stack([sx, sy], axis=2))
        depth.append(sz.mean(axis=1))
        cols.append(c)
    T, D, C = np.concatenate(tris), np.concatenate(depth), np.concatenate(cols)
    span = max(T[..., 0].max() - T[..., 0].min(), 1e-6), max(T[..., 1].max() - T[..., 1].min(), 1e-6)
    s = 0.84 * min(W / span[0], H / span[1])
    cx = (T[..., 0].max() + T[..., 0].min()) / 2
    cy = (T[..., 1].max() + T[..., 1].min()) / 2
    order = np.argsort(D)
    for i in order:
        t = T[i]
        pts = [(W / 2 + (x - cx) * s, H / 2 - (y - cy) * s) for x, y in t]
        col = tuple(int(x) for x in C[i])
        draw.polygon(pts, fill=col, outline=col)
    return _png(img)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
