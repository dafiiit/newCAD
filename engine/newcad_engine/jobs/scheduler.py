"""Matches jobs to compute targets.

Each solver adapter declares which devices it can use. Each target reports
its devices and installed solvers. A job can run on a target that has every
solver it needs and a free slot. Among those:

- a job whose solvers can use a CUDA GPU prefers a target that has one
  (fluids and batch motion in later phases);
- CPU-only jobs prefer the local target (no upload), unless it is busy;
- otherwise the target with the most performance cores wins.

A study can also pin a target by id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SolverAdapter:
    id: str
    name: str
    license: str
    devices: tuple[str, ...]          # "cpu", "cuda"
    prefers: str = "cpu"              # device the adapter is fastest on
    note: str = ""


ADAPTERS: dict[str, SolverAdapter] = {
    "gmsh": SolverAdapter("gmsh", "Gmsh", "GPL-2.0-or-later", ("cpu",), note="Tetrahedral volume meshing"),
    "calculix": SolverAdapter("calculix", "CalculiX", "GPL-2.0", ("cpu",),
                              note="Static, modal and steady thermal FEM. CPU only: the CUDA path through PaStiX is experimental"),
}

# what each job kind needs
JOB_SOLVERS: dict[str, tuple[str, ...]] = {
    "fem.static": ("gmsh", "calculix"),
    "fem.modal": ("gmsh", "calculix"),
    "fem.thermal": ("gmsh", "calculix"),
}


@dataclass
class Choice:
    target: str | None
    reason: str
    candidates: list[str] = field(default_factory=list)


def requirements(kind: str) -> dict[str, Any]:
    solvers = JOB_SOLVERS.get(kind)
    if solvers is None:
        raise KeyError(f"Unknown job kind {kind}")
    wants_gpu = any(ADAPTERS[s].prefers == "cuda" for s in solvers)
    return {"solvers": list(solvers), "prefers_gpu": wants_gpu}


def choose(kind: str, targets: list[dict[str, Any]], busy: dict[str, int], pinned: str | None = None,
           exclude: set[str] | None = None) -> Choice:
    """targets: described targets ({id, kind, online, slots, devices: {cpu, gpus, solvers}}). busy: running jobs per target."""
    req = requirements(kind)
    exclude = exclude or set()
    able, reasons = [], []
    for t in targets:
        if t["id"] in exclude:
            continue
        if pinned and pinned != "auto" and t["id"] != pinned:
            continue
        if not t.get("online"):
            reasons.append(f"{t['name']} is offline")
            continue
        sv = (t.get("devices") or {}).get("solvers") or {}
        missing = [ADAPTERS[s].name for s in req["solvers"] if not sv.get(s)]
        if missing:
            reasons.append(f"{t['name']} has no {', '.join(missing)}")
            continue
        able.append(t)
    if not able:
        why = "; ".join(reasons) or (f"no target named {pinned}" if pinned and pinned != "auto" else "no compute target")
        return Choice(None, f"No compute target can run this: {why}")
    free = [t for t in able if busy.get(t["id"], 0) < int(t.get("slots", 1))]
    if not free:
        return Choice(None, "Waiting for a free compute target", [t["id"] for t in able])

    def score(t: dict[str, Any]) -> tuple[float, ...]:
        d = t.get("devices") or {}
        gpu = 1.0 if d.get("gpus") else 0.0
        cores = float((d.get("cpu") or {}).get("performance_cores") or 1)
        local = 1.0 if t["kind"] == "local" else 0.0
        if req["prefers_gpu"]:
            return (gpu, cores, local)
        return (local, cores)

    best = max(free, key=score)
    return Choice(best["id"], f"Runs on {best['name']}", [t["id"] for t in able])
