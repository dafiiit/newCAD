"""Study + build + mates → a solver-ready mechanism.

The mechanism is plain data in model units (mm, kg, deg as given) plus the
SI values the solvers need. The MuJoCo exporter (mjcf.py) and the Rapier
preview in the browser both read it, so the preview moves the same bodies on
the same joints as the simulation.

Body frames coincide with the assembly frame in the modelled position. Part
geometry therefore needs no re-centring: a body's pose at time t is the
transform that moves the part from where it was modelled.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np

from ...geometry.facetags import rematch
from .. import materials as M
from .model import GROUND, Mate, MotionSetup

MOTION_VERSION = "2"


class MotionProblem(Exception):
    """The motion study can't run as set up; the message says what to fix."""


def _unit(v: list[float] | np.ndarray) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise MotionProblem("an axis can't be zero")
    return a / n


def find_face(ref: Any, metas: dict[str, dict[str, Any]], scale: float, what: str, warnings: list[str]) -> dict[str, Any]:
    """The current face meta for a stored face reference (re-matched by signature after a rebuild)."""
    faces = metas[ref.part]["faces"]
    for f in faces:
        if f["tag"] == ref.tag:
            return f
    if not ref.sig:
        raise MotionProblem(f"{what}: face {ref.tag} on {ref.part} no longer exists. Pick the face again.")
    m = rematch(ref.sig, [(x["tag"], {k: v for k, v in x.items() if k != "tag"}) for x in faces], scale)
    if m["tag"] is None or m["ambiguous"]:
        raise MotionProblem(f"{what}: the picked face on {ref.part} changed too much to find it again. Pick the face again.")
    warnings.append(f"{what}: face {ref.tag} on {ref.part} moved; using {m['tag']} (match score {m['score']})")
    return next(f for f in faces if f["tag"] == m["tag"])


def joint_frame(mate: Mate, faces: list[dict[str, Any]], coms: dict[str, list[float]]) -> tuple[list[float], list[float]]:
    """Joint centre and axis (mm, unit vector) from the mate's explicit values or its faces."""
    name = mate.label or mate.id
    round_faces = [f for f in faces if f.get("axis") and f.get("axis_point")]
    axis = _unit(mate.axis) if mate.axis else None
    if axis is None and mate.type in ("revolute", "prismatic"):
        if round_faces:
            axis = _unit(round_faces[0]["axis"])
            for f in round_faces[1:]:
                if abs(float(np.dot(axis, _unit(f["axis"])))) < 0.999:
                    raise MotionProblem(f"{name}: the picked round faces are not on one axis")
        elif mate.type == "prismatic" and any(f.get("normal") for f in faces):
            axis = _unit(next(f["normal"] for f in faces if f.get("normal")))
        else:
            raise MotionProblem(f"{name}: pick a bore or pin face (or give the axis) so the joint knows how it turns")
    if axis is None:
        axis = np.array([0.0, 0.0, 1.0])
    if mate.origin:
        origin = np.asarray(mate.origin, dtype=float)
    elif mate.type == "ball" and any(f["type"] == "sphere" for f in round_faces):
        origin = np.mean([f["axis_point"] for f in round_faces if f["type"] == "sphere"], axis=0)
    elif round_faces:
        # centre of the bore along its axis: the face's centre of mass projected onto the axis line
        pts = []
        for f in round_faces:
            p0, d = np.asarray(f["axis_point"], float), _unit(f["axis"])
            c = np.asarray(f.get("com") or f["center"], float)
            pts.append(p0 + d * float(np.dot(c - p0, d)))
        origin = np.mean(pts, axis=0)
    elif faces:
        origin = np.mean([f.get("com") or f["center"] for f in faces], axis=0)
    elif mate.type in ("fixed",):
        cs = [coms[p] for p in mate.parts if p in coms]
        origin = np.mean(cs, axis=0) if cs else np.zeros(3)
    else:
        raise MotionProblem(f"{name}: pick the faces of the joint (or give its centre)")
    return [round(float(x), 6) for x in origin], [round(float(x), 9) for x in axis]


def _si(kind: str, jtype: str, value: float) -> float:
    """Model units → SI. kind: speed, torque, position, stiffness, damping, rest."""
    rot = jtype == "revolute"
    if kind == "speed":
        return value * 2 * math.pi / 60 if rot else value / 1000
    if kind in ("position", "rest"):
        return math.radians(value) if rot else value / 1000
    if kind in ("stiffness", "damping"):
        return value if rot else value * 1000
    return value  # torque N·m, force N


def mechanism(study: Any, manifest: dict[str, Any], metas: dict[str, dict[str, Any]], mates: list[Mate]) -> dict[str, Any]:
    """Resolve a motion study. Raises MotionProblem with what to fix."""
    setup: MotionSetup = study.motion or MotionSetup()
    by = {p["id"]: p for p in manifest["parts"]}
    ids = study.parts or [p["id"] for p in manifest["parts"]]
    if not ids:
        raise MotionProblem("The model has no parts yet")
    for pid in ids:
        if pid not in by:
            raise MotionProblem(f"Part {pid} is not in the model")
        if not by[pid]["ok"]:
            raise MotionProblem(f"Part {pid} doesn't build: {by[pid].get('error')}")
    warnings: list[str] = []
    scale = 100.0
    if manifest.get("bbox"):
        mn, mx = manifest["bbox"]["min"], manifest["bbox"]["max"]
        scale = max(1.0, max(mx[k] - mn[k] for k in range(3)))

    bodies = []
    for pid in ids:
        p, meta = by[pid], metas[pid]
        vol = float(meta.get("volume_mm3") or 0.0)
        if vol <= 0 or "inertia_mm5" not in meta:
            raise MotionProblem(f"Part {pid} has no volume, so it has no mass. Motion needs solid parts.")
        if p.get("mass_kg") is not None and pid not in study.materials:
            mass = float(p["mass_kg"])
        else:
            mass = vol * M.lookup(study.materials.get(pid) or p.get("material"))["density"] * 1e-9
        rho = mass / vol  # kg/mm³ (a bought-in mass spreads evenly over the shape)
        inertia = (np.asarray(meta["inertia_mm5"], float) * rho).tolist()  # kg·mm² about the centre of mass
        bodies.append({"id": pid, "name": p.get("name", pid), "key": p["key"], "color": p.get("color"), "mass_kg": mass,
                       "com": meta.get("com") or meta["center"], "inertia_kgmm2": inertia, "bbox": meta["bbox"],
                       "faces": len(meta.get("faces", []))})
    coms = {b["id"]: b["com"] for b in bodies}

    joints = []
    for m in mates:
        name = m.label or m.id
        if any(p != GROUND and p not in by for p in m.parts):
            warnings.append(f"{name}: connects a part that is not in the model; left out")
            continue
        if any(p != GROUND and p not in ids for p in m.parts):
            warnings.append(f"{name}: connects a part outside this study; left out")
            continue
        faces = []
        for f in m.faces:
            if f.part not in m.parts:
                raise MotionProblem(f"{name}: face {f.tag} is on {f.part}, which this joint doesn't connect")
            faces.append({**find_face(f, metas, scale, name, warnings), "part": f.part})
        origin, axis = joint_frame(m, faces, coms)
        lim = None
        if m.limits and m.type in ("revolute", "prismatic"):
            lim = [_si("position", m.type, m.limits[0]), _si("position", m.type, m.limits[1])]
        joints.append({"id": m.id, "label": name, "type": m.type, "parts": list(m.parts), "origin": origin, "axis": axis,
                       "limits": m.limits, "limits_si": lim,
                       "faces": {p: [f["tag"] for f in faces if f["part"] == p] for p in m.parts if p != GROUND}})

    # kinematic tree: breadth-first from ground; the remaining mates close loops
    adj: dict[str, list[tuple[str, int]]] = {GROUND: [], **{b["id"]: [] for b in bodies}}
    for i, j in enumerate(joints):
        a, b = j["parts"]
        adj[a].append((b, i))
        adj[b].append((a, i))
    parent: dict[str, tuple[str, int] | None] = {GROUND: None}
    order: list[str] = []
    roots: list[str] = []

    def bfs(start: str) -> None:
        q = deque([start])
        while q:
            u = q.popleft()
            for v, ji in sorted(adj[u], key=lambda x: x[1]):
                if v not in parent:
                    parent[v] = (u, ji)
                    order.append(v)
                    q.append(v)

    bfs(GROUND)
    mass = {b["id"]: b["mass_kg"] for b in bodies}
    for b in sorted(bodies, key=lambda b: -b["mass_kg"]):
        if b["id"] not in parent:
            # a group of parts connected to nothing fixed: it floats (falls under gravity)
            group_start = len(order)
            parent[b["id"]] = None
            order.append(b["id"])
            roots.append(b["id"])
            bfs(b["id"])
            members = [b["id"], *order[group_start + 1:]]
            names = ", ".join(sorted(members))
            warnings.append(f"{names} {'is' if len(members) == 1 else 'are'} not connected to ground and move{'s' if len(members) == 1 else ''} freely")
    tree_joint = {pj[1] for pj in parent.values() if pj is not None}
    for i, j in enumerate(joints):
        if i in tree_joint:
            child = next(c for c, pj in parent.items() if pj is not None and pj[1] == i)
            j["role"] = "tree"
            j["child"] = child
            j["parent"] = parent[child][0]
            j["sign"] = 1 if j["parts"][1] == child else -1
        else:
            j["role"] = "loop"
            if j["type"] == "prismatic":
                raise MotionProblem(f"{j['label']}: a sliding joint can't close a loop. Close the loop with a revolute or ball joint.")
    body_order = [*order]
    by_mate = {j["id"]: j for j in joints}

    drivers = []
    for d in setup.drivers:
        j = by_mate.get(d.mate)
        if j is None:
            raise MotionProblem(f"Driver on {d.mate}: no such joint")
        if j["type"] not in ("revolute", "prismatic"):
            raise MotionProblem(f"Driver on {j['label']}: only revolute and sliding joints can be driven")
        if j["role"] != "tree":
            raise MotionProblem(f"Driver on {j['label']}: this joint closes a loop; drive another joint of the loop")
        drivers.append({"mate": d.mate, "kind": d.kind, "value": d.value, "ramp": d.ramp,
                        "value_si": _si("torque" if d.kind == "torque" else d.kind, j["type"], d.value),
                        "unit": {"speed": "rpm" if j["type"] == "revolute" else "mm/s", "torque": "N·m" if j["type"] == "revolute" else "N",
                                 "position": "deg" if j["type"] == "revolute" else "mm"}[d.kind]})
    springs = []
    for s in setup.springs:
        j = by_mate.get(s.mate)
        if j is None:
            raise MotionProblem(f"Spring on {s.mate}: no such joint")
        if j["type"] not in ("revolute", "prismatic") or j["role"] != "tree":
            raise MotionProblem(f"Spring on {j['label']}: springs go on revolute or sliding joints of the tree (not on one that closes a loop)")
        springs.append({"mate": s.mate, "stiffness": s.stiffness, "damping": s.damping, "rest": s.rest,
                        "stiffness_si": _si("stiffness", j["type"], s.stiffness), "damping_si": _si("damping", j["type"], s.damping),
                        "rest_si": _si("rest", j["type"], s.rest)})
    sweep = None
    if setup.sweep:
        kind, _, rest = setup.sweep.parameter.partition(".")
        target, _, field = rest.rpartition(".") if kind in ("drivers", "springs") else (rest, "", "")
        if kind == "drivers" and target not in {d["mate"] for d in drivers}:
            raise MotionProblem(f"Sweep: no driver on {target}")
        if kind == "springs" and target not in {s["mate"] for s in springs}:
            raise MotionProblem(f"Sweep: no spring on {target}")
        if kind == "mass" and target not in mass:
            raise MotionProblem(f"Sweep: no part {target}")
        sweep = {"parameter": setup.sweep.parameter, "kind": kind, "target": target, "field": field, "values": list(setup.sweep.values)}
    if not drivers and not any(setup.gravity) and not roots:
        warnings.append("Nothing drives the mechanism and gravity is off, so nothing moves")
    if setup.timestep * 20 > setup.duration:
        raise MotionProblem("The duration should be at least 20 time steps")
    if setup.duration / setup.timestep > 2_000_000:
        raise MotionProblem("Too many steps: use a larger time step or a shorter duration (at most 2 million steps)")

    return {
        "bodies": bodies, "order": body_order, "roots": roots, "joints": joints, "drivers": drivers, "springs": springs,
        "settings": {"duration": setup.duration, "timestep": setup.timestep, "gravity": list(setup.gravity), "contacts": setup.contacts,
                     "damping": setup.damping, "samples": setup.samples},
        "sweep": sweep, "warnings": warnings,
    }


def joint_damping_si(jtype: str, damping: float) -> float:
    return _si("damping", jtype, damping)
