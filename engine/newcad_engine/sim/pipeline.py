"""The simulation pipeline: one job directory in, one result directory out.

    python -m newcad_engine.sim.pipeline <job_dir> <out_dir>

job_dir holds `job.json` (a study resolved by sim.study.resolve, plus
`threads` and `timeout_s`) and `parts/<id>.brep`. The pipeline meshes with
Gmsh, solves with CalculiX and writes:

    result.json   summary numbers (peak stress and where, safety factor, frequencies, …)
    field.glb     surface with raw nodal fields for the viewport
    result.vtu    volume mesh with fields (ParaView)
    mesh.msh      the Gmsh mesh; solver/ holds the CalculiX deck and log

It prints one JSON object per line on stdout: {"progress": 0..1, "stage": "..."}
while it runs and {"done": true, "ok": ...} at the end. The same pipeline runs
on the local compute target and on a remote compute node, so both give
identical results. It runs as its own process (Gmsh and CalculiX are GPL and
are never loaded into the engine).
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np


def emit(**kw: Any) -> None:
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def _where(mesh: Any, node: int, node_face: dict[int, tuple[str, str]]) -> dict[str, Any]:
    p = mesh.nodes[node]
    key = node_face.get(node)
    if key is None and node_face:
        # interior node: report the nearest surface node's face
        cand = np.fromiter(node_face.keys(), dtype=np.int64)
        near = cand[np.argmin(np.linalg.norm(mesh.nodes[cand] - p, axis=1))]
        key = node_face[int(near)]
    return {"point": [round(float(x), 3) for x in p], "part": key[0] if key else None, "face": key[1] if key else None}


def run(job_dir: Path, out_dir: Path) -> dict[str, Any]:
    from ..results import fields as F
    from .fem import calculix as C
    from .mesh.gmsh_mesh import mesh_parts

    job = json.loads((job_dir / "job.json").read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    threads = int(job.get("threads") or 1)
    t0 = time.perf_counter()
    emit(progress=0.02, stage="Meshing")
    parts_in = [{"id": p["id"], "brep": job_dir / "parts" / f"{p['id']}.brep", "faces": p["faces"]} for p in job["parts"]]
    mesh = mesh_parts(parts_in, float(job["mesh"]["size"]), int(job["mesh"]["order"]), out_dir,
                      progress=lambda f, s: emit(progress=0.02 + f, stage=s), threads=threads)
    t_mesh = time.perf_counter() - t0
    q = mesh.quality
    emit(progress=0.35, stage=f"Mesh: {q['elements']:,} elements, {q['nodes']:,} nodes")

    work = out_dir / "solver"
    work.mkdir(exist_ok=True)
    book = C.write_input(job, mesh, work / "job.inp")
    emit(progress=0.4, stage="Solving with CalculiX")
    t_solve = C.run(work, "job", threads, float(job.get("timeout_s", 1800)))
    emit(progress=0.85, stage="Reading results")
    n = len(mesh.nodes)
    blocks = C.read_frd(work / "job.frd", n)

    node_part = np.zeros(n, dtype=np.int64)
    node_part[mesh.tets.reshape(-1)] = np.repeat(mesh.tet_part, mesh.tets.shape[1])
    node_face: dict[int, tuple[str, str]] = {}
    for key, tris in mesh.faces.items():
        if mesh.exterior.get(key, True):
            for nd in np.unique(tris):
                node_face.setdefault(int(nd), key)

    surf = F.surface(mesh)
    scalars: dict[str, np.ndarray] = {}
    vectors: dict[str, np.ndarray] = {}
    point_data: dict[str, np.ndarray] = {}
    bb = job.get("bbox") or {"min": mesh.nodes.min(axis=0).tolist(), "max": mesh.nodes.max(axis=0).tolist()}
    size = float(max(bb["max"][k] - bb["min"][k] for k in range(3)))
    summary: dict[str, Any] = {"type": job["type"], "study": job["study"], "mesh": q, "warnings": job.get("warnings", [])}
    fields_meta: dict[str, Any] = {}
    kind = job["type"]

    if kind == "static":
        U = next(b["data"][:, :3] for b in blocks if b["name"] == "DISP")
        S = next(b["data"][:, :6] for b in blocks if b["name"] == "STRESS")
        vm = C.von_mises(S)
        yields = np.array([p["material"]["yield"] for p in job["parts"]], dtype=float)[node_part]
        sf = np.minimum(np.divide(yields, vm, out=np.full_like(vm, 1e3), where=vm > 1e-9), 1e3)
        umag = np.linalg.norm(U, axis=1)
        i_vm, i_u, i_sf = int(np.argmax(vm)), int(np.argmax(umag)), int(np.argmin(sf))
        summary.update({
            "max_von_mises_mpa": float(vm[i_vm]), "max_von_mises_at": _where(mesh, i_vm, node_face),
            "max_displacement_mm": float(umag[i_u]), "max_displacement_at": _where(mesh, i_u, node_face),
            "min_safety_factor": float(sf[i_sf]), "min_safety_factor_at": _where(mesh, i_sf, node_face),
            "safety_target": job.get("safety_target"),
            "reactions_n": C.read_reactions(work / "job.dat") if (work / "job.dat").exists() else [],
        })
        # surface peak (what a user sees) next to the nodal peak
        sn = surf["nodes"]
        summary["surface_max_von_mises_mpa"] = float(vm[sn].max())
        scalars.update({"von_mises": vm, "safety": sf, "disp_mag": umag})
        vectors["disp"] = U
        fields_meta = {
            "von_mises": {"label": "von Mises stress", "unit": "MPa", "min": float(vm[sn].min()), "max": float(vm[sn].max())},
            "safety": {"label": "Safety factor", "unit": "", "min": float(sf[sn].min()), "max": float(min(sf[sn].max(), 10.0))},
            "disp_mag": {"label": "Displacement", "unit": "mm", "min": 0.0, "max": float(umag[sn].max())},
        }
        point_data = {"displacement": U, "stress": S, "von_mises": vm, "safety_factor": sf}
        summary["deform_scale"] = float(0.08 * size / umag.max()) if umag.max() > 0 else 1.0
    elif kind == "modal":
        freqs = C.read_frequencies(work / "job.dat")
        modes = [b for b in blocks if b["name"] == "DISP"]
        summary["frequencies_hz"] = [round(f, 4) for f in freqs]
        summary["modes"] = []
        for i, b in enumerate(modes[: len(freqs) or len(modes)]):
            U = b["data"][:, :3]
            m = float(np.linalg.norm(U, axis=1).max()) or 1.0
            U = U / m
            vectors[f"mode{i + 1}"] = U
            point_data[f"mode{i + 1}"] = U
            fi = freqs[i] if i < len(freqs) else b["value"]
            umag = np.linalg.norm(U, axis=1)
            summary["modes"].append({"index": i + 1, "frequency_hz": round(float(fi), 4), "max_at": _where(mesh, int(np.argmax(umag)), node_face)})
        summary["deform_scale"] = 0.08 * size
        if vectors:
            scalars["mode_mag"] = np.linalg.norm(vectors["mode1"], axis=1)
            fields_meta["mode_mag"] = {"label": "Relative displacement", "unit": "", "min": 0.0, "max": 1.0}
    else:
        T = next(b["data"][:, 0] for b in blocks if b["name"] == "NDTEMP")
        i_hi, i_lo = int(np.argmax(T)), int(np.argmin(T))
        summary.update({"max_temperature_c": float(T[i_hi]), "max_temperature_at": _where(mesh, i_hi, node_face),
                        "min_temperature_c": float(T[i_lo]), "min_temperature_at": _where(mesh, i_lo, node_face)})
        scalars["temp"] = T
        sn = surf["nodes"]
        fields_meta["temp"] = {"label": "Temperature", "unit": "°C", "min": float(T[sn].min()), "max": float(T[sn].max())}
        point_data = {"temperature": T}

    emit(progress=0.92, stage="Writing result files")
    extras = {"study": job["study"], "type": kind, "fields": fields_meta,
              "modes": summary.get("modes", []), "deformScale": summary.get("deform_scale", 1.0)}
    F.write_field_glb(out_dir / "field.glb", surf, scalars, vectors, extras)
    try:
        F.write_vtu(out_dir / "result.vtu", mesh, point_data)
    except Exception as e:  # VTU is a convenience export; don't fail the study for it
        summary["warnings"].append(f"VTU export failed: {e}")
    summary["fields"] = fields_meta
    summary["timing_s"] = {"mesh": round(t_mesh, 3), "solve": round(t_solve, 3), "total": round(time.perf_counter() - t0, 3)}
    summary["solver"] = {"name": "CalculiX", "version": C.ccx_version(), "threads": threads}
    (out_dir / "result.json").write_text(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    job_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        summary = run(job_dir, out_dir)
        emit(done=True, ok=True, progress=1.0, stage="Done", summary=summary)
    except Exception as e:  # report every failure as one readable line
        from .fem.calculix import SolverError
        from .mesh.gmsh_mesh import MeshError
        known = isinstance(e, (SolverError, MeshError))
        msg = str(e) if known else f"{type(e).__name__}: {e}"
        emit(done=True, ok=False, error=msg, trace=None if known else traceback.format_exc(limit=8)[-3000:])


if __name__ == "__main__":
    main()
