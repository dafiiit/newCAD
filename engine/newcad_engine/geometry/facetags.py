"""Stable face tags (mitigation for the topological naming problem).

OCCT renumbers faces on every rebuild, so comments and boundary conditions
can't point at a face index. Each face gets a tag derived from its geometric
signature (surface type, rounded area, centroid and normal). An unchanged
face keeps its tag across rebuilds. When a face moved or resized, `rematch`
finds the closest new face by signature and says how sure it is.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

Sig = dict[str, Any]  # {"type": str, "area": float, "center": [x,y,z], "normal": [x,y,z] | None}


def tag_of(sig: Sig) -> str:
    c = [round(x, 1) for x in sig["center"]]
    n = [round(x, 2) + 0.0 for x in sig["normal"]] if sig.get("normal") else None
    key = f"{sig['type']}|{round(sig['area'], 1)}|{c}|{n}"
    return "f" + hashlib.sha1(key.encode()).hexdigest()[:8]


def assign_tags(sigs: list[Sig]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for s in sigs:
        t = tag_of(s)
        if t in seen:  # identical signature (rare): disambiguate by order
            seen[t] += 1
            t = f"{t}-{seen[t]}"
        else:
            seen[t] = 0
        out.append(t)
    return out


def _dist(a: Sig, b: Sig, scale: float) -> float:
    d = math.dist(a["center"], b["center"]) / max(scale, 1e-6)
    d += abs(a["area"] - b["area"]) / max(a["area"], b["area"], 1e-6)
    if a.get("normal") and b.get("normal"):
        dot = sum(x * y for x, y in zip(a["normal"], b["normal"]))
        d += (1 - dot) * 0.5
    if a["type"] != b["type"]:
        d += 1.0
    return d


def rematch(old: Sig, candidates: list[tuple[str, Sig]], scale: float = 100.0) -> dict[str, Any]:
    """Find the face that best matches an old signature. `scale` is a model size in mm.

    Returns {"tag", "score", "ambiguous"}; tag is None when nothing is close.
    """
    if not candidates:
        return {"tag": None, "score": None, "ambiguous": False}
    exact = tag_of(old)
    for t, _ in candidates:
        if t == exact or t.startswith(exact + "-"):
            return {"tag": t, "score": 0.0, "ambiguous": False}
    scored = sorted((_dist(old, s, scale), t) for t, s in candidates)
    best = scored[0]
    if best[0] > 0.6:
        return {"tag": None, "score": best[0], "ambiguous": False}
    ambiguous = len(scored) > 1 and scored[1][0] - best[0] < 0.05
    return {"tag": best[1], "score": round(best[0], 3), "ambiguous": ambiguous}
