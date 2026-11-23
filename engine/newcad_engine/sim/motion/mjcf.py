"""Mechanism → MJCF (MuJoCo's model format).

- Parts become bodies with the mass, centre of mass and inertia from the
  B-rep. Every body frame sits at the assembly origin in the modelled
  position, so poses apply to the part geometry as modelled.
- Mates of the kinematic tree become joints (hinge, slide, ball, or none for
  fixed). Mates that close a loop become equality constraints (connect for
  revolute and ball, weld for fixed).
- Drivers become actuators: a speed or position driver is a stiff servo
  (position + velocity actuator pair) that follows a smooth motion profile;
  a torque driver is a motor. Springs are joint stiffness and damping.
- With contacts on, parts get collision geoms (collision.py); parts joined by
  a mate never collide with each other.

MuJoCo works in SI units: millimetres become metres here.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

from .model import GROUND
from .resolve import joint_damping_si

MM = 1e-3


def _f(v: Any) -> str:
    if isinstance(v, (list, tuple, np.ndarray)):
        return " ".join(_f(x) for x in v)
    return f"{float(v):.10g}"


def _m(v: list[float]) -> list[float]:
    return [x * MM for x in v]


def body_name(pid: str) -> str:
    return "world" if pid == GROUND else f"part:{pid}"


def build_xml(mech: dict[str, Any], geoms: dict[str, list[dict[str, Any]]] | None = None, name: str = "newcad") -> str:
    s = mech["settings"]
    dt = float(s["timestep"])
    root = ET.Element("mujoco", model=name)
    ET.SubElement(root, "compiler", angle="radian", inertiafromgeom="false", autolimits="true")
    ET.SubElement(root, "option", timestep=_f(dt), gravity=_f(s["gravity"]), integrator="implicitfast")
    ET.SubElement(root, "size", memory="64M")
    asset = ET.SubElement(root, "asset")
    world = ET.SubElement(root, "worldbody")
    contact = ET.SubElement(root, "contact")
    equality = ET.SubElement(root, "equality")
    actuator = ET.SubElement(root, "actuator")

    bodies = {b["id"]: b for b in mech["bodies"]}
    tree = {j["child"]: j for j in mech["joints"] if j["role"] == "tree"}
    elems: dict[str, ET.Element] = {GROUND: world}
    damping_all = float(s.get("damping") or 0.0)
    springs = {x["mate"]: x for x in mech["springs"]}
    geoms = geoms or {}
    for pid in mech["order"]:
        b = bodies[pid]
        j = tree.get(pid)
        parent_el = elems[j["parent"]] if j else world
        el = ET.SubElement(parent_el, "body", name=body_name(pid), pos="0 0 0")
        elems[pid] = el
        I = np.asarray(b["inertia_kgmm2"], float) * MM * MM
        mass = max(float(b["mass_kg"]), 1e-6)
        diag = np.maximum(np.diag(I), 1e-12)
        ET.SubElement(el, "inertial", pos=_f(_m(b["com"])), mass=_f(mass),
                      fullinertia=_f([diag[0], diag[1], diag[2], I[0, 1], I[0, 2], I[1, 2]]))
        if j is None:
            ET.SubElement(el, "freejoint", name=f"free:{pid}")
        elif j["type"] != "fixed":
            kind = {"revolute": "hinge", "prismatic": "slide", "ball": "ball"}[j["type"]]
            attrs = {"name": j["id"], "type": kind, "pos": _f(_m(j["origin"]))}
            if kind != "ball":
                # the joint coordinate is parts[1] relative to parts[0]; flip the axis when parts[1] is the parent
                attrs["axis"] = _f([a * j["sign"] for a in j["axis"]])
                damp = damping_all and joint_damping_si(j["type"], damping_all)
                sp = springs.get(j["id"])
                if sp:
                    attrs["stiffness"] = _f(sp["stiffness_si"])
                    attrs["springref"] = _f(sp["rest_si"])
                    damp += sp["damping_si"]
                if damp:
                    attrs["damping"] = _f(damp)
                if j.get("limits_si"):
                    attrs["range"] = _f(j["limits_si"])
            elif damping_all:
                attrs["damping"] = _f(joint_damping_si("revolute", damping_all))
            ET.SubElement(el, "joint", **attrs)
        for gi, g in enumerate(geoms.get(pid, [])):
            ga = {"name": f"col:{pid}:{gi}", "contype": "1", "conaffinity": "1", "condim": "3", "friction": "0.5 0.005 0.0001",
                  "group": "3"}
            if g["type"] == "box":
                ga.update(type="box", pos=_f(_m(g["pos"])), size=_f(_m(g["half"])))
            elif g["type"] == "cylinder":
                ga.update(type="cylinder", pos=_f(_m(g["pos"])), zaxis=_f(g["axis"]), size=_f([g["radius"] * MM, g["half_length"] * MM]))
            elif g["type"] == "sphere":
                ga.update(type="sphere", pos=_f(_m(g["pos"])), size=_f(g["radius"] * MM))
            else:
                mesh = f"hull:{pid}:{gi}"
                ET.SubElement(asset, "mesh", name=mesh, vertex=_f(np.asarray(g["vertices"], float).reshape(-1) * MM))
                ga.update(type="mesh", mesh=mesh)
            ET.SubElement(el, "geom", **ga)

    solref = _f([max(2 * dt, 0.002), 1.0])
    pairs = set()
    for j in mech["joints"]:
        a, b = j["parts"]
        if GROUND not in (a, b):
            pairs.add(tuple(sorted((a, b))))
        if j["role"] != "loop":
            continue
        # body1 is parts[1] unless that is ground; the force on body1 is reported (see run.py)
        b1, b2 = (b, a) if b != GROUND else (a, b)
        if j["type"] == "fixed":
            ET.SubElement(equality, "weld", name=j["id"], body1=body_name(b1), body2=body_name(b2), solref=solref)
        else:
            ET.SubElement(equality, "connect", name=j["id"], body1=body_name(b1), body2=body_name(b2),
                          anchor=_f(_m(j["origin"])), solref=solref)
    if geoms:
        for a, b in sorted(pairs):
            if a in geoms and b in geoms:
                ET.SubElement(contact, "exclude", body1=body_name(a), body2=body_name(b))

    for d in mech["drivers"]:
        if d["kind"] == "torque":
            ET.SubElement(actuator, "motor", name=f"{d['mate']}:torque", joint=d["mate"], gear="1")
        else:
            ET.SubElement(actuator, "position", name=f"{d['mate']}:pos", joint=d["mate"], kp="1")
            ET.SubElement(actuator, "velocity", name=f"{d['mate']}:vel", joint=d["mate"], kv="1")
    for el in (asset, contact, equality, actuator):
        if not len(el):
            root.remove(el)
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def servo_bandwidth(dt: float) -> float:
    """Natural frequency of the drive servos (rad/s): stiff, but well inside what the time step resolves."""
    return min(2 * math.pi * 40, 0.3 / dt)


def compile_model(xml: str, mech: dict[str, Any]):
    """Compile, index the model, and tune the servo gains to each driven joint's inertia."""
    import mujoco
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    full = np.zeros((m.nv, m.nv))
    try:
        mujoco.mj_fullM(m, d, full)  # MuJoCo >= 3.5
    except TypeError:
        mujoco.mj_fullM(m, full, d.qM)
    idx = index(m, mech)
    wn = servo_bandwidth(m.opt.timestep)
    for dv in idx["drivers"]:
        if dv["kind"] == "torque":
            continue
        inertia = max(float(full[dv["dof"], dv["dof"]]), 1e-9)
        kp, kv = inertia * wn * wn, 2.0 * inertia * wn
        p, v = dv["act"]
        m.actuator_gainprm[p, 0], m.actuator_biasprm[p, 1] = kp, -kp
        m.actuator_gainprm[v, 0], m.actuator_biasprm[v, 2] = kv, -kv
        dv["kp"], dv["kv"] = kp, kv
    return m, idx


def index(m: Any, mech: dict[str, Any]) -> dict[str, Any]:
    import mujoco
    nm = lambda t, n: mujoco.mj_name2id(m, t, n)  # noqa: E731
    bodies = {b["id"]: nm(mujoco.mjtObj.mjOBJ_BODY, body_name(b["id"])) for b in mech["bodies"]}
    mates = []
    for j in mech["joints"]:
        e = {"id": j["id"], "type": j["type"], "role": j["role"], "parts": j["parts"], "origin_m": _m(j["origin"]),
             "b0": -1 if j["parts"][0] == GROUND else bodies[j["parts"][0]], "b1": -1 if j["parts"][1] == GROUND else bodies[j["parts"][1]]}
        if j["role"] == "tree":
            e["child"] = bodies[j["child"]]
            e["sign"] = j["sign"]
            if j["type"] != "fixed":
                jid = nm(mujoco.mjtObj.mjOBJ_JOINT, j["id"])
                e["qpos"], e["dof"], e["jtype"] = int(m.jnt_qposadr[jid]), int(m.jnt_dofadr[jid]), j["type"]
        else:
            e["eq"] = nm(mujoco.mjtObj.mjOBJ_EQUALITY, j["id"])
            e["flip"] = j["parts"][1] == GROUND  # body1 is parts[0] then
        mates.append(e)
    by = {e["id"]: e for e in mates}
    drivers = []
    for dv in mech["drivers"]:
        e = by[dv["mate"]]
        if dv["kind"] == "torque":
            act = [nm(mujoco.mjtObj.mjOBJ_ACTUATOR, f"{dv['mate']}:torque")]
        else:
            act = [nm(mujoco.mjtObj.mjOBJ_ACTUATOR, f"{dv['mate']}:pos"), nm(mujoco.mjtObj.mjOBJ_ACTUATOR, f"{dv['mate']}:vel")]
        drivers.append({**dv, "act": act, "dof": e["dof"], "qpos": e["qpos"]})
    return {"bodies": bodies, "mates": mates, "drivers": drivers}


def profile(kind: str, value: float, ramp: float, t: float) -> tuple[float, float]:
    """Driver set point at time t: (position or torque, velocity). Speeds ramp linearly; positions follow a minimum-jerk curve."""
    if kind == "torque":
        return (value * min(t / ramp, 1.0) if ramp > 0 else value), 0.0
    if kind == "speed":
        if ramp <= 0:
            return value * t, value
        if t < ramp:
            return value * t * t / (2 * ramp), value * t / ramp
        return value * (t - ramp / 2), value
    if ramp <= 0:
        return value, 0.0
    x = min(max(t / ramp, 0.0), 1.0)
    return value * (10 * x**3 - 15 * x**4 + 6 * x**5), value * (30 * x**2 - 60 * x**3 + 30 * x**4) / ramp


def controls(drivers: list[dict[str, Any]], t: float, nu: int, values: dict[str, float] | None = None) -> np.ndarray:
    """ctrl vector at time t; `values` overrides driver values (SI) by mate id (sweeps)."""
    ctrl = np.zeros(nu)
    for dv in drivers:
        val = (values or {}).get(dv["mate"], dv["value_si"])
        a, b = profile(dv["kind"], val, dv["ramp"], t)
        if dv["kind"] == "torque":
            ctrl[dv["act"][0]] = a
        else:
            ctrl[dv["act"][0]], ctrl[dv["act"][1]] = a, b
    return ctrl
