"""Motion job: mechanism in, MuJoCo results out. Called by sim/pipeline.py for `type: motion` jobs.

Writes into the result directory:

    result.json   summary: peak bearing load per joint (and when, and on which part), driver effort, ranges
    series.json   time series for the plots (joint position and speed, reaction force, moment, effort)
    motion.glb    animation track per body (applied to the part meshes in the viewport)
    model.xml     the MJCF model (open it in MuJoCo's viewer: python -m mujoco.viewer --mjcf model.xml)
    sweep.json    one row per sweep value (only for sweeps)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

Emit = Callable[..., None]


def run(job: dict[str, Any], job_dir: Path, out_dir: Path, emit: Emit) -> dict[str, Any]:
    import mujoco

    from ...results.animation import to_view, write_motion_glb
    from . import batch
    from .mjcf import build_xml, compile_model
    from .run import simulate

    t0 = time.perf_counter()
    mech = job["mechanism"]
    warnings = list(job.get("warnings", []))
    threads = int(job.get("threads") or 1)
    geoms = None
    if mech["settings"]["contacts"]:
        from .collision import collision_geoms
        emit(progress=0.02, stage="Collision shapes (convex decomposition)")
        geoms = {}
        for i, b in enumerate(mech["bodies"]):
            geoms[b["id"]] = collision_geoms(str(job_dir / "parts" / f"{b['id']}.brep"), b["id"], warnings)
            emit(progress=0.02 + 0.08 * (i + 1) / len(mech["bodies"]), stage=f"Collision shapes: {b['name']}")
    emit(progress=0.1, stage="Building MuJoCo model")
    xml = build_xml(mech, geoms, name=job.get("study", "newcad"))
    (out_dir / "model.xml").write_text(xml)
    m, idx = compile_model(xml, mech)
    sweep = mech.get("sweep")
    span = 0.55 if sweep else 0.8

    def prog(f: float, frame: dict[str, Any] | None) -> None:
        kw: dict[str, Any] = {}
        if frame:
            # live preview while the job runs: body poses in viewport coordinates
            pids = list(frame)
            arr = np.asarray([frame[p] for p in pids], float)
            tr, rot = to_view(arr)
            kw["frame"] = {p: [*map(float, tr[i]), *map(float, rot[i])] for i, p in enumerate(pids)}
        emit(progress=0.12 + span * f, stage=f"Simulating {mech['settings']['duration']:g} s", **kw)

    res = simulate(m, idx, mech, record="full", progress=prog)
    t_sim = time.perf_counter() - t0
    emit(progress=0.12 + span, stage="Writing results")
    anim = res.pop("animation")
    series = res.pop("series")
    write_motion_glb(out_dir / "motion.glb", anim["t"], anim["pose"], anim["bodies"],
                     {"study": job.get("study"), "type": "motion", "duration": mech["settings"]["duration"]})
    (out_dir / "series.json").write_text(json.dumps(series, separators=(",", ":")))

    summary: dict[str, Any] = {
        "type": "motion", "study": job.get("study"), "duration_s": mech["settings"]["duration"],
        "timestep_s": mech["settings"]["timestep"], "warnings": warnings, "fields": {},
        "bodies": [{"id": b["id"], "mass_kg": round(b["mass_kg"], 6)} for b in mech["bodies"]], **res,
    }
    # the headline bearing is a moving joint; fixed mates (a part bolted to ground) only count when there is nothing else
    loads = [(x["peak_force_n"], x) for x in res["mates"] if x["peak_force_on"] and x["type"] != "fixed"] \
        or [(x["peak_force_n"], x) for x in res["mates"] if x["peak_force_on"]]
    if loads:
        top = max(loads, key=lambda t: t[0])[1]
        part = next((p for p in reversed(top["parts"]) if p in top["peak_force_on"]), None)
        summary["peak_bearing"] = {"mate": top["id"], "label": top["label"], "part": part, "force_n": top["peak_force_n"], "at_s": top["peak_at_s"]}
    if res["loop_error_mm"] > 0.1:
        warnings.append(f"Loop joints drift apart by up to {res['loop_error_mm']:.2f} mm; a smaller time step makes them stiffer")

    if sweep:
        kind, device = batch.backend()
        emit(progress=0.7, stage=f"Sweep: {len(sweep['values'])} variants on {'GPU (MuJoCo Warp)' if device.startswith('cuda') else 'MuJoCo Warp, CPU' if kind == 'mujoco_warp' else f'{threads} CPU processes'}")
        ts = time.perf_counter()

        def sp(f: float) -> None:
            emit(progress=0.7 + 0.25 * f, stage=f"Sweep {sweep['parameter']}: {f:.0%}")

        if kind == "mujoco_warp":
            try:
                rows = batch.warp_sweep(m, idx, mech, sweep["values"], device, sp)
            except Exception as e:  # e.g. a model feature MuJoCo Warp doesn't support yet
                warnings.append(f"MuJoCo Warp could not run the sweep ({type(e).__name__}: {e}); used the CPU instead")
                kind, device = "cpu_pool", "cpu"
                rows = batch.cpu_sweep(xml, mech, sweep["values"], threads, sp)
        else:
            rows = batch.cpu_sweep(xml, mech, sweep["values"], threads, sp)
        sw = {"parameter": sweep["parameter"], "values": sweep["values"], "rows": rows, "backend": kind, "device": device,
              "wall_s": round(time.perf_counter() - ts, 3)}
        (out_dir / "sweep.json").write_text(json.dumps(sw))
        summary["sweep"] = {k: sw[k] for k in ("parameter", "backend", "device", "wall_s")} | {"variants": len(rows),
                                                                                                "failed": sum(1 for r in rows if not r["ok"])}
        summary["sweep"]["rows"] = rows
    summary["timing_s"] = {"simulate": round(t_sim, 3), "total": round(time.perf_counter() - t0, 3)}
    summary["solver"] = {"name": "MuJoCo", "version": mujoco.__version__, "threads": threads}
    (out_dir / "result.json").write_text(json.dumps(summary, indent=1))
    return summary
