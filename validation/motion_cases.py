"""Analytic motion validation cases, run through the real engine (build123d → MJCF → MuJoCo).

- Four-bar linkage (Phase 4 gate): a Grashof crank-rocker driven at constant
  crank speed. The rocker angle over a full crank turn must follow the
  closed-form position solution of the loop (circle intersection).
- Rotating link: a bar spun about one end at constant speed without gravity.
  The bearing load is the centripetal force m·ω²·r.
- Bearing load hand-off (Phase 4 gate): the peak bearing load of the four-bar's
  coupler goes into a CalculiX static study with one call; the study's load is
  exactly the MuJoCo peak and CalculiX's support reactions balance it.

Mates are made from picked faces (the bores of the links), like in the Check tab.
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import numpy as np

from cases import Result
from newcad_engine.project.store import YOU

# crank-rocker: ground r1, crank r2, coupler r3, rocker r4 (mm). Grashof: 30 + 100 <= 90 + 70
R1, R2, R3, R4 = 100.0, 30.0, 90.0, 70.0
THETA2_0 = 60.0  # modelled crank angle, deg
RPM = 60.0
W, T, HOLE = 12.0, 6.0, 3.0  # link width, thickness, hole radius (mm)


def _xz(a: float, r: float, o: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    return np.array([o[0] + r * math.cos(a), o[1] + r * math.sin(a)])


def coupler_point(b: np.ndarray, o4: np.ndarray, branch: float) -> np.ndarray:
    """C: intersection of the circles (B, r3) and (O4, r4) on the given side of B→O4."""
    d = o4 - b
    L = float(np.linalg.norm(d))
    a = (R3**2 - R4**2 + L**2) / (2 * L)
    h = math.sqrt(max(R3**2 - a**2, 0.0))
    u = d / L
    n = np.array([-u[1], u[0]])
    return b + a * u + branch * h * n


def rocker_angle(theta2: float, branch: float) -> float:
    o4 = np.array([R1, 0.0])
    c = coupler_point(_xz(theta2, R2), o4, branch)
    return math.atan2(c[1] - o4[1], c[0] - o4[0])


def link_code(p: np.ndarray, q: np.ndarray, y: float) -> str:
    """A flat link in the XZ plane (pins along Y) from p to q, holes at both ends."""
    c = (p + q) / 2
    L = float(np.linalg.norm(q - p))
    ang = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    return f"""from build123d import *
with BuildPart() as link:
    Box({L + W}, {T}, {W})
    with Locations((-{L / 2}, 0, 0), ({L / 2}, 0, 0)):
        Cylinder({HOLE}, {T}, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
result = link.part.rotate(Axis.Y, {-ang}).translate(({c[0]}, {y}, {c[1]}))
"""


def _bore(faces: list[dict[str, Any]], at: np.ndarray) -> dict[str, Any]:
    hits = [f for f in faces if f["type"] == "cylinder" and abs(f["com"][0] - at[0]) < 0.5 and abs(f["com"][2] - at[1]) < 0.5]
    if len(hits) != 1:
        raise AssertionError(f"expected one bore at {at}, found {len(hits)}")
    return hits[0]


def _ref(part: str, f: dict[str, Any]) -> dict[str, Any]:
    return {"part": part, "tag": f["tag"], "sig": {k: v for k, v in f.items() if k != "tag"}}


async def _wait(job):
    while job.status in ("queued", "running"):
        await asyncio.sleep(0.05)
    if job.status != "done":
        raise AssertionError(f"{job.name}: {job.status} {job.error}")
    return job.summary


async def four_bar_project(engine, name: str = "Four-bar"):
    """Base (ground link), crank, coupler, rocker: four revolute joints from picked bores; the base is fixed to ground."""
    th = math.radians(THETA2_0)
    o2, o4 = np.array([0.0, 0.0]), np.array([R1, 0.0])
    b = _xz(th, R2)
    branch = 1.0  # coupler above the ground line
    c = coupler_point(b, o4, branch)
    links = {"base": (o2, o4, 0.0), "crank": (o2, b, T + 2), "coupler": (b, c, 2 * (T + 2)), "rocker": (o4, c, T + 2)}
    p = engine.store.create(name)
    files = {f"parts/{k}.py": link_code(a, z, y) for k, (a, z, y) in links.items()}
    asm = "parts:\n" + "".join(f"- id: {k}\n  file: parts/{k}.py\n  material: Steel\n" for k in links)
    p.commit("main", name, YOU, changes={**files, "assembly.yaml": asm + "mates: []\n"})
    man = await engine.geometry.build(p)
    assert man["ok"], man
    faces = {x["id"]: engine.geometry.meta(x["key"])["faces"] for x in man["parts"]}
    pins = [("crank-pivot", "base", "crank", o2), ("crank-pin", "crank", "coupler", b),
            ("rocker-pin", "coupler", "rocker", c), ("rocker-pivot", "base", "rocker", o4)]
    for mid, a, z, at in pins:
        engine.mates.add(p, {"id": mid, "type": "revolute", "parts": [a, z],
                             "faces": [_ref(a, _bore(faces[a], at)), _ref(z, _bore(faces[z], at))]})
    engine.mates.add(p, {"id": "base-fixed", "type": "fixed", "parts": ["ground", "base"]})
    return p, branch


async def four_bar(engine) -> list[Result]:
    """Phase 4 gate: rocker angle of a crank-rocker follows the analytic loop-closure solution."""
    p, branch = await four_bar_project(engine)
    st = engine.sim.create(p, "Crank at 60 rpm", "motion", None)
    turn = 60.0 / RPM
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "motion": {
        "duration": 0.25 + turn * 1.05, "timestep": 0.0005, "drivers": [{"mate": "crank-pivot", "kind": "speed", "value": RPM, "ramp": 0.25}],
        "samples": 1200}}, None)
    s = await _wait(await engine.sim.run(p, st.id))
    state = await engine.sim.state(p, st.id)
    series = json.loads((engine.jobs.result_dir(state["key"]) / "series.json").read_text())
    mates = {m["id"]: m for m in await engine.mates.resolved(p)}
    # joint coordinates turn about the joint axis; angles in the XZ plane turn about -Y
    s2 = -mates["crank-pivot"]["axis_dir"][1]
    s4 = -mates["rocker-pivot"]["axis_dir"][1]
    q2 = np.radians(np.asarray(series["mates"]["crank-pivot"]["q"], float))
    q4 = np.radians(np.asarray(series["mates"]["rocker-pivot"]["q"], float))
    th2 = math.radians(THETA2_0) + s2 * q2
    th4_0 = rocker_angle(math.radians(THETA2_0), branch)
    sim4 = th4_0 + s4 * q4
    ref4 = np.array([rocker_angle(a, branch) for a in th2])
    err = np.degrees(np.abs(np.unwrap(sim4) - np.unwrap(ref4)))
    turned = math.degrees(float(th2.max() - th2.min()))
    assert turned >= 360.0, f"the crank turned only {turned:.0f}°"
    full = np.degrees(np.unwrap(ref4))
    swing_ref = float(full.max() - full.min())
    swing = float(np.degrees(np.unwrap(sim4)).max() - np.degrees(np.unwrap(sim4)).min())
    return [
        Result("Four-bar crank-rocker", "max rocker angle error over a crank turn (deg)", float(err.max()), 0.0, 0.1,
               f"{len(err)} samples, crank turned {turned:.0f}°; loop joints stay within {s['loop_error_mm']:.4f} mm", unit="°"),
        Result("Four-bar crank-rocker", "rocker swing (deg)", swing, swing_ref, 0.002,
               f"links {R1:g}/{R2:g}/{R3:g}/{R4:g} mm, Freudenstein position solution"),
    ]


LINK_L, LINK_RPM = 120.0, 300.0


async def rotating_link(engine) -> list[Result]:
    """Bar spun about one end, no gravity: bearing load = m·ω²·r (r = distance pivot → centre of mass)."""
    p = engine.store.create("Rotating link")
    a, b = np.array([0.0, 0.0]), np.array([LINK_L, 0.0])
    p.commit("main", "link", YOU, changes={"parts/link.py": link_code(a, b, 0.0),
                                          "assembly.yaml": "parts:\n- id: link\n  file: parts/link.py\n  material: Aluminium\nmates: []\n"})
    man = await engine.geometry.build(p)
    meta = engine.geometry.meta(man["parts"][0]["key"])
    engine.mates.add(p, {"id": "pivot", "type": "revolute", "parts": ["ground", "link"], "faces": [_ref("link", _bore(meta["faces"], a))]})
    st = engine.sim.create(p, "Spin", "motion", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "motion": {
        "duration": 1.0, "gravity": [0, 0, 0], "drivers": [{"mate": "pivot", "kind": "speed", "value": LINK_RPM, "ramp": 0.3}]}}, None)
    s = await _wait(await engine.sim.run(p, st.id))
    state = await engine.sim.state(p, st.id)
    series = json.loads((engine.jobs.result_dir(state["key"]) / "series.json").read_text())
    f_end = float(np.mean(series["mates"]["pivot"]["force_mag"][-20:]))
    mass = s["bodies"][0]["mass_kg"]
    r = math.hypot(meta["com"][0] - a[0], meta["com"][2] - a[1]) / 1000
    w = LINK_RPM * 2 * math.pi / 60
    return [Result("Rotating link", "bearing load at constant speed (N)", f_end, mass * w * w * r, 0.01,
                   f"m = {mass:.4f} kg, r = {r * 1000:.2f} mm, ω = {w:.2f} rad/s")]


async def bearing_handoff(engine) -> list[Result]:
    """Phase 4 gate: the coupler's peak bearing load feeds a CalculiX static study without retyping."""
    from newcad_engine.sim.service import bearing_load
    p, _ = await four_bar_project(engine, "Four-bar to FEM")
    st = engine.sim.create(p, "Fast crank", "motion", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "motion": {
        "duration": 1.0, "drivers": [{"mate": "crank-pivot", "kind": "speed", "value": 240, "ramp": 0.2}]}}, None)
    s = await _wait(await engine.sim.run(p, st.id))
    row = next(m for m in s["mates"] if m["id"] == "crank-pin")
    peak = row["peak_force_on"]["coupler"]
    fem = await bearing_load(engine, p, st.id, "crank-pin", "coupler")
    load = next(b for b in fem.boundaries if b.type == "force")
    assert np.allclose(load.vector, peak, atol=1e-3), (load.vector, peak)
    assert any(b.type == "fixed" for b in fem.boundaries), "the coupler should be held at its other bearing"
    engine.sim.replace(p, fem.id, {**fem.to_yaml_dict(), "mesh": {"size": 2.0, "order": 2}}, None)
    r = await _wait(await engine.sim.run(p, fem.id))
    react = np.sum(np.asarray(r["reactions_n"], float).reshape(-1, 3), axis=0)
    return [Result("Bearing load → CalculiX", "support reaction vs. MuJoCo peak load (N)", float(np.linalg.norm(react)),
                   float(np.linalg.norm(peak)), 0.01,
                   f"peak {np.linalg.norm(peak):.1f} N at t = {row['peak_at_s']:.3f} s; static peak stress {r['max_von_mises_mpa']:.1f} MPa")]


MOTION_CASES = {"four_bar": four_bar, "rotating_link": rotating_link, "bearing_handoff": bearing_handoff}
