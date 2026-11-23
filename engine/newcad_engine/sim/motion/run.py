"""Run a mechanism in MuJoCo (CPU) and record what the Check tab shows.

Per mate (joint) it records the joint coordinate, its speed, the reaction
force that parts[0] exerts on parts[1] (the bearing load) and the moment
about the joint centre; per driver the actuator effort; per body the pose
for the animation track. Peak loads are tracked at every recorded step, not
only at the plotted samples.

Reactions: a joint of the kinematic tree reads MuJoCo's interaction force
between the child body and its parent (cfrc_int, after
mj_rnePostConstraint). A joint that closes a loop is an equality
constraint; its reaction is the constraint force (efc_force rows of that
equality, in world axes, acting on body1).
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable

import numpy as np

from .mjcf import controls
from .model import GROUND

EQUALITY = 0  # mjCNSTR_EQUALITY


def mat_of(xmat: np.ndarray, b: int) -> np.ndarray:
    return np.eye(3) if b < 0 else xmat[b].reshape(3, 3)


def pos_of(xpos: np.ndarray, b: int) -> np.ndarray:
    return np.zeros(3) if b < 0 else xpos[b]


def reactions(idx: dict[str, Any], rootid: np.ndarray, cfrc_int: np.ndarray, subtree_com: np.ndarray, xpos: np.ndarray,
              xmat: np.ndarray, efc_type: np.ndarray, efc_id: np.ndarray, efc_force: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """(force on parts[1] from parts[0], moment about the joint centre) per mate, world axes, N and N·m."""
    out = []
    eq_rows: dict[int, list[int]] = {}
    for r in np.nonzero(efc_type == EQUALITY)[0]:
        eq_rows.setdefault(int(efc_id[r]), []).append(int(r))
    for e in idx["mates"]:
        if e["role"] == "tree":
            c = e["child"]
            f6 = cfrc_int[c]
            tq, f = f6[:3], f6[3:6]
            com = subtree_com[rootid[c]]
            p = pos_of(xpos, c) + mat_of(xmat, c) @ np.asarray(e["origin_m"])
            tq_p = tq + np.cross(com - p, f)
            s = 1.0 if e["sign"] == 1 else -1.0
            out.append((s * f, s * tq_p))
        else:
            rows = eq_rows.get(e["eq"], [])
            f = efc_force[rows[:3]] if len(rows) >= 3 else np.zeros(3)
            if e["flip"]:
                f = -f
            out.append((np.asarray(f, float), np.zeros(3)))
    return out


def loop_angle(R0: np.ndarray, R1: np.ndarray, axis: np.ndarray) -> float:
    """Rotation of body 1 relative to body 0 about `axis` (given in body 0's modelled frame)."""
    Rr = R0.T @ R1
    s = 0.5 * np.array([Rr[2, 1] - Rr[1, 2], Rr[0, 2] - Rr[2, 0], Rr[1, 0] - Rr[0, 1]])
    return math.atan2(float(np.dot(s, axis)), (float(np.trace(Rr)) - 1) / 2)


def simulate(m: Any, idx: dict[str, Any], mech: dict[str, Any], *, record: str = "full", values: dict[str, float] | None = None,
             fps: float = 60.0, progress: Callable[[float, dict[str, Any] | None], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Step the model for the study's duration. record="full" keeps time series and the animation; "peaks" only summaries."""
    import mujoco
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    s = mech["settings"]
    dt = float(m.opt.timestep)
    n = max(1, int(round(s["duration"] / dt)))
    every_series = max(1, n // int(s["samples"]))
    every_anim = max(1, int(round(1.0 / (fps * dt))))
    every_peak = max(1, n // 200_000)
    mates = idx["mates"]
    joints = {j["id"]: j for j in mech["joints"]}
    nb = len(idx["bodies"])
    body_ids = list(idx["bodies"].values())
    peak = [{"f": 0.0, "t": 0.0, "vec": np.zeros(3), "loc": {}, "tq": 0.0} for _ in mates]
    eff_peak = [0.0 for _ in idx["drivers"]]
    eff_sq = [0.0 for _ in idx["drivers"]]
    q_range = [[math.inf, -math.inf] for _ in mates]
    qd_max = [0.0 for _ in mates]
    loop_err = 0.0
    T: list[float] = []
    S: dict[str, list[Any]] = {f"{k}:{e['id']}": [] for e in mates for k in ("q", "qd", "f", "fm", "tm")}
    E: list[list[float]] = [[] for _ in idx["drivers"]]
    anim_t: list[float] = []
    anim_pose: list[np.ndarray] = []
    q_unwrap: dict[str, float] = {}
    t_wall = time.perf_counter()
    last_emit = t_wall
    nsamp = 0

    def joint_q(e: dict[str, Any]) -> tuple[float | None, float | None]:
        if e["role"] == "tree" and "qpos" in e:
            return float(d.qpos[e["qpos"]]), float(d.qvel[e["dof"]])
        if e["type"] == "revolute":
            a = loop_angle(mat_of(d.xmat, e["b0"]), mat_of(d.xmat, e["b1"]), np.asarray(joints[e["id"]]["axis"]))
            prev = q_unwrap.get(e["id"])
            if prev is not None:
                a = prev + (a - prev + math.pi) % (2 * math.pi) - math.pi
            q_unwrap[e["id"]] = a
            return a, None
        return None, None

    for k in range(n + 1):
        t = k * dt
        need_series = record == "full" and k % every_series == 0
        need_peak = k % every_peak == 0
        if need_series or need_peak:
            mujoco.mj_rnePostConstraint(m, d)
            R = reactions(idx, m.body_rootid, d.cfrc_int, d.subtree_com, d.xpos, d.xmat, d.efc_type, d.efc_id, d.efc_force)
            eff = [float(sum(d.actuator_force[a] for a in dv["act"])) for dv in idx["drivers"]]
            for i, (e, (f, tq)) in enumerate(zip(mates, R)):
                fm = float(np.linalg.norm(f))
                q, qd = joint_q(e)
                if q is not None:
                    q_range[i] = [min(q_range[i][0], q), max(q_range[i][1], q)]
                if qd is not None:
                    qd_max[i] = max(qd_max[i], abs(qd))
                if fm > peak[i]["f"]:
                    loc = {}
                    if e["parts"][1] != GROUND:
                        loc[e["parts"][1]] = (mat_of(d.xmat, e["b1"]).T @ f).tolist()
                    if e["parts"][0] != GROUND:
                        loc[e["parts"][0]] = (mat_of(d.xmat, e["b0"]).T @ -f).tolist()
                    peak[i] = {"f": fm, "t": t, "vec": f.copy(), "loc": loc, "tq": float(np.linalg.norm(tq))}
                if need_series:
                    jt = e["type"]
                    S[f"q:{e['id']}"].append(None if q is None else (math.degrees(q) if jt != "prismatic" else q * 1000))
                    S[f"qd:{e['id']}"].append(None if qd is None else (math.degrees(qd) if jt != "prismatic" else qd * 1000))
                    S[f"f:{e['id']}"].append([round(float(x), 6) for x in f])
                    S[f"fm:{e['id']}"].append(round(fm, 6))
                    S[f"tm:{e['id']}"].append(round(float(np.linalg.norm(tq)), 6))
                if e["role"] == "loop" and e["type"] in ("revolute", "ball"):
                    o = np.asarray(e["origin_m"])
                    p1 = pos_of(d.xpos, e["b1"]) + mat_of(d.xmat, e["b1"]) @ o
                    p0 = pos_of(d.xpos, e["b0"]) + mat_of(d.xmat, e["b0"]) @ o
                    loop_err = max(loop_err, float(np.linalg.norm(p1 - p0)))
            for i, v in enumerate(eff):
                eff_peak[i] = max(eff_peak[i], abs(v))
                eff_sq[i] += v * v
                if need_series:
                    E[i].append(round(v, 6))
            nsamp += 1
            if need_series:
                T.append(round(t, 6))
        if record == "full" and k % every_anim == 0:
            anim_t.append(t)
            anim_pose.append(np.concatenate([d.xpos[body_ids], d.xquat[body_ids]], axis=1).copy())
        if k == n:
            break
        if progress and k % 200 == 0:
            now = time.perf_counter()
            if now - last_emit > 0.25:
                last_emit = now
                frame = {pid: np.concatenate([d.xpos[b], d.xquat[b]]).tolist() for pid, b in idx["bodies"].items()} if record == "full" else None
                progress(k / n, frame)
            if cancelled and cancelled():
                raise KeyboardInterrupt
        d.ctrl[:] = controls(idx["drivers"], t + dt, m.nu, values)
        mujoco.mj_step(m, d)
        if not np.all(np.isfinite(d.qpos)):
            raise FloatingPointError(f"The simulation became unstable at t = {t:.4f} s. Use a smaller time step, or check the joints and drivers.")

    summary_mates = []
    for e, pk, qr, qm in zip(mates, peak, q_range, qd_max):
        j = joints[e["id"]]
        unit_q = "mm" if j["type"] == "prismatic" else "deg"
        conv = (lambda x: x * 1000) if j["type"] == "prismatic" else math.degrees
        summary_mates.append({
            "id": e["id"], "label": j["label"], "type": j["type"], "parts": j["parts"], "role": e["role"],
            "peak_force_n": round(pk["f"], 6), "peak_at_s": round(pk["t"], 6), "peak_force_world": [round(float(x), 6) for x in pk["vec"]],
            "peak_force_on": {p: [round(float(x), 6) for x in v] for p, v in pk["loc"].items()},
            "peak_moment_nm": round(pk["tq"], 6),
            "range": [round(conv(qr[0]), 4), round(conv(qr[1]), 4)] if math.isfinite(qr[0]) else None, "range_unit": unit_q,
            "max_speed": (round(qm * 60 / (2 * math.pi), 4) if j["type"] != "prismatic" else round(qm * 1000, 4)) if "qpos" in e else None,
            "speed_unit": "mm/s" if j["type"] == "prismatic" else "rpm",
        })
    out: dict[str, Any] = {
        "mates": summary_mates,
        "drivers": [{"mate": dv["mate"], "kind": dv["kind"], "value": dv["value"], "unit": dv["unit"],
                     "peak_effort": round(p, 6), "rms_effort": round(math.sqrt(sq / max(nsamp, 1)), 6),
                     "effort_unit": "N·m" if joints[dv["mate"]]["type"] == "revolute" else "N"}
                    for dv, p, sq in zip(idx["drivers"], eff_peak, eff_sq)],
        "loop_error_mm": round(loop_err * 1000, 6), "steps": n, "wall_s": round(time.perf_counter() - t_wall, 3),
    }
    if record == "full":
        out["series"] = {
            "t": T,
            "mates": {e["id"]: {"q": S[f"q:{e['id']}"], "qd": S[f"qd:{e['id']}"], "force": S[f"f:{e['id']}"],
                                 "force_mag": S[f"fm:{e['id']}"], "moment_mag": S[f"tm:{e['id']}"]} for e in mates},
            "drivers": {dv["mate"]: E[i] for i, dv in enumerate(idx["drivers"])},
        }
        out["animation"] = {"t": np.asarray(anim_t), "pose": np.asarray(anim_pose).reshape(len(anim_t), nb, 7), "bodies": list(idx["bodies"])}
    return out
