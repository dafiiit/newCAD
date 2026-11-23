"""Parameter sweeps: one MuJoCo world per value.

On a target with a CUDA GPU and MuJoCo Warp installed, all variants run as
parallel worlds of one batched model on the GPU. Elsewhere (a Mac, or a PC
without NVIDIA) the same sweep runs on a CPU process pool with MuJoCo, one
variant per process. Both report the same summary per variant: peak bearing
load per joint and peak driver effort.

What can vary per world: a driver's value (speed, torque or position; it only
changes the control signal), a spring's stiffness or damping, a part's mass,
and the joint damping. Values that would change the geometry (link lengths)
need a rebuild of the parts and are a separate study per variant.

NEWCAD_SWEEP_BACKEND=warp-cpu forces MuJoCo Warp on the CPU (slow; for tests).
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

import numpy as np

from .resolve import _si, joint_damping_si


def backend() -> tuple[str, str]:
    """(backend, device): ("mujoco_warp", "cuda:0" | "cpu") or ("cpu_pool", "cpu")."""
    forced = os.environ.get("NEWCAD_SWEEP_BACKEND", "")
    if forced == "cpu":
        return "cpu_pool", "cpu"
    try:
        import importlib.util
        if importlib.util.find_spec("mujoco_warp") is None:
            return "cpu_pool", "cpu"
        if forced == "warp-cpu":
            return "mujoco_warp", "cpu"
        import warp as wp
        wp.config.quiet = True
        wp.init()
        if wp.get_cuda_device_count() > 0:
            return "mujoco_warp", "cuda:0"
    except Exception:
        pass
    return "cpu_pool", "cpu"


def overrides(mech: dict[str, Any], value: float) -> dict[str, Any]:
    """What one sweep value changes, in SI: {"drivers": {mate: v}, "stiffness": {mate: v}, "damping": {mate: v}, "mass": {part: kg}}."""
    sw = mech["sweep"]
    joints = {j["id"]: j for j in mech["joints"]}
    out: dict[str, Any] = {"drivers": {}, "stiffness": {}, "damping": {}, "mass": {}}
    if sw["kind"] == "drivers":
        dv = next(d for d in mech["drivers"] if d["mate"] == sw["target"])
        out["drivers"][dv["mate"]] = _si("torque" if dv["kind"] == "torque" else dv["kind"], joints[dv["mate"]]["type"], value)
    elif sw["kind"] == "springs":
        sp = next(s for s in mech["springs"] if s["mate"] == sw["target"])
        jt = joints[sp["mate"]]["type"]
        if sw["field"] == "stiffness":
            out["stiffness"][sp["mate"]] = _si("stiffness", jt, value)
        else:
            out["damping"][sp["mate"]] = _si("damping", jt, value) + joint_damping_si(jt, mech["settings"]["damping"])
    elif sw["kind"] == "mass":
        out["mass"][sw["target"]] = max(float(value), 1e-6)
    else:  # global joint damping
        springs = {s["mate"]: s for s in mech["springs"]}
        for j in mech["joints"]:
            if j["role"] == "tree" and j["type"] in ("revolute", "prismatic", "ball"):
                jt = "revolute" if j["type"] == "ball" else j["type"]
                out["damping"][j["id"]] = joint_damping_si(jt, value) + (springs[j["id"]]["damping_si"] if j["id"] in springs else 0.0)
    return out


def _ids(m: Any, mate: str) -> tuple[int, int, int]:
    import mujoco
    jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, mate)
    dofs = 3 if m.jnt_type[jid] == mujoco.mjtJoint.mjJNT_BALL else 1
    return jid, int(m.jnt_dofadr[jid]), dofs


def apply(m: Any, idx: dict[str, Any], ov: dict[str, Any]) -> None:
    """Apply overrides to a host MjModel in place (CPU path)."""
    for mate, k in ov["stiffness"].items():
        m.jnt_stiffness[_ids(m, mate)[0]] = k
    for mate, c in ov["damping"].items():
        _, dof, n = _ids(m, mate)
        m.dof_damping[dof:dof + n] = c
    for part, kg in ov["mass"].items():
        b = idx["bodies"][part]
        ratio = kg / float(m.body_mass[b])
        m.body_mass[b] = kg
        m.body_inertia[b] *= ratio


def _peaks(res: dict[str, Any]) -> dict[str, Any]:
    return {"peak_force_n": {x["id"]: x["peak_force_n"] for x in res["mates"]},
            "peak_effort": {x["mate"]: x["peak_effort"] for x in res["drivers"]},
            "range": {x["id"]: x["range"] for x in res["mates"]}}


def _variant(args: tuple[str, dict[str, Any], float]) -> dict[str, Any]:
    from .mjcf import compile_model
    from .run import simulate
    xml, mech, value = args
    try:
        m, idx = compile_model(xml, mech)
        ov = overrides(mech, value)
        apply(m, idx, ov)
        res = simulate(m, idx, mech, record="peaks", values=ov["drivers"])
        return {"value": value, "ok": True, **_peaks(res)}
    except Exception as e:  # one unstable variant shouldn't sink the sweep
        return {"value": value, "ok": False, "error": f"{type(e).__name__}: {e}"}


def cpu_sweep(xml: str, mech: dict[str, Any], values: list[float], workers: int,
              progress: Callable[[float], None] | None = None) -> list[dict[str, Any]]:
    import multiprocessing as mp
    rows: list[dict[str, Any] | None] = [None] * len(values)
    if workers <= 1 or len(values) == 1:
        for i, v in enumerate(values):
            rows[i] = _variant((xml, mech, v))
            if progress:
                progress((i + 1) / len(values))
        return rows  # type: ignore[return-value]
    with ProcessPoolExecutor(max_workers=min(workers, len(values)), mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(_variant, (xml, mech, v)): i for i, v in enumerate(values)}
        from concurrent.futures import as_completed
        for k, f in enumerate(as_completed(futs)):
            rows[futs[f]] = f.result()
            if progress:
                progress((k + 1) / len(values))
    return rows  # type: ignore[return-value]


def warp_sweep(m: Any, idx: dict[str, Any], mech: dict[str, Any], values: list[float], device: str,
               progress: Callable[[float], None] | None = None) -> list[dict[str, Any]]:
    """All variants as parallel worlds of one MuJoCo Warp model."""
    import warp as wp
    import mujoco_warp as mjw

    from .mjcf import controls
    from .run import reactions

    n = len(values)
    ovs = [overrides(mech, v) for v in values]
    batched: dict[str, np.ndarray] = {}
    if any(o["stiffness"] for o in ovs):
        a = np.tile(np.asarray(m.jnt_stiffness, float)[None], (n, 1))
        for w, o in enumerate(ovs):
            for mate, k in o["stiffness"].items():
                a[w, _ids(m, mate)[0]] = k
        batched["jnt_stiffness"] = a
    if any(o["damping"] for o in ovs):
        a = np.tile(np.asarray(m.dof_damping, float)[None], (n, 1))
        for w, o in enumerate(ovs):
            for mate, c in o["damping"].items():
                _, dof, k = _ids(m, mate)
                a[w, dof:dof + k] = c
        batched["dof_damping"] = a
    if any(o["mass"] for o in ovs):
        bm = np.tile(np.asarray(m.body_mass, float)[None], (n, 1))
        bi = np.tile(np.asarray(m.body_inertia, float)[None], (n, 1, 1))
        for w, o in enumerate(ovs):
            for part, kg in o["mass"].items():
                b = idx["bodies"][part]
                bi[w, b] *= kg / float(m.body_mass[b])
                bm[w, b] = kg
        batched["body_mass"], batched["body_inertia"] = bm, bi

    s = mech["settings"]
    dt = float(m.opt.timestep)
    steps = max(1, int(round(s["duration"] / dt)))
    every = max(1, steps // 2000)  # reactions are read back every few steps
    mates = idx["mates"]
    peak_f = np.zeros((n, len(mates)))
    peak_e = np.zeros((n, len(idx["drivers"])))
    q_lo = np.full((n, len(mates)), np.inf)
    q_hi = np.full((n, len(mates)), -np.inf)
    bad = np.zeros(n, dtype=bool)
    rootid = np.asarray(m.body_rootid)
    with wp.ScopedDevice(device):
        wm = mjw.put_model(m, batch_sizes={k: n for k in batched})
        for k, a in batched.items():
            dst = getattr(wm, k)
            dst.assign(wp.array(a.astype(np.float32).reshape(dst.shape + ((3,) if k == "body_inertia" else ())), dtype=dst.dtype))
        wd = mjw.make_data(m, nworld=n)
        for k in range(steps + 1):
            if k % every == 0 or k == steps:
                mjw.rne_postconstraint(wm, wd)
                cf, sc = wd.cfrc_int.numpy(), wd.subtree_com.numpy()
                xp, xm = wd.xpos.numpy(), wd.xmat.numpy()
                et, ei, ef = wd.efc.type.numpy(), wd.efc.id.numpy(), wd.efc.force.numpy()
                ne = wd.ne.numpy() if hasattr(wd, "ne") else None
                af, qp = wd.actuator_force.numpy(), wd.qpos.numpy()
                for w in range(n):
                    if bad[w]:
                        continue
                    if not np.all(np.isfinite(qp[w])):
                        bad[w] = True
                        continue
                    rows = slice(0, int(ne[w]) if ne is not None and np.ndim(ne) else et.shape[-1])
                    R = reactions(idx, rootid, cf[w], sc[w], xp[w], xm[w].reshape(-1, 9), et[w][rows], ei[w][rows], ef[w][rows])
                    for i, (f, _) in enumerate(R):
                        peak_f[w, i] = max(peak_f[w, i], float(np.linalg.norm(f)))
                        e = mates[i]
                        if "qpos" in e:
                            q_lo[w, i] = min(q_lo[w, i], float(qp[w, e["qpos"]]))
                            q_hi[w, i] = max(q_hi[w, i], float(qp[w, e["qpos"]]))
                    for i, dv in enumerate(idx["drivers"]):
                        peak_e[w, i] = max(peak_e[w, i], abs(float(sum(af[w, a] for a in dv["act"]))))
                if progress:
                    progress(k / steps)
            if k == steps:
                break
            ctrl = np.stack([controls(idx["drivers"], (k + 1) * dt, m.nu, o["drivers"]) for o in ovs]).astype(np.float32)
            if m.nu:
                wd.ctrl.assign(wp.array(ctrl, dtype=wd.ctrl.dtype))
            mjw.step(wm, wd)
    joints = {j["id"]: j for j in mech["joints"]}
    rows = []
    for w, v in enumerate(values):
        if bad[w]:
            rows.append({"value": v, "ok": False, "error": "The simulation became unstable for this value"})
            continue
        rng = {}
        for i, e in enumerate(mates):
            if np.isfinite(q_lo[w, i]):
                conv = (lambda x: x * 1000) if joints[e["id"]]["type"] == "prismatic" else math.degrees
                rng[e["id"]] = [round(conv(q_lo[w, i]), 4), round(conv(q_hi[w, i]), 4)]
            else:
                rng[e["id"]] = None
        rows.append({"value": v, "ok": True,
                     "peak_force_n": {e["id"]: round(float(peak_f[w, i]), 6) for i, e in enumerate(mates)},
                     "peak_effort": {dv["mate"]: round(float(peak_e[w, i]), 6) for i, dv in enumerate(idx["drivers"])},
                     "range": rng})
    return rows
