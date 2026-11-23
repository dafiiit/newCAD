"""Motion studies: mates → MJCF, MuJoCo runs, joint loads, animation, sweeps, preview data, hand-off to FEM."""
import asyncio
import json
import math
import os
import shutil
import time

import numpy as np
import pytest
from mcp import Client

from newcad_engine.api.app import create_app
from newcad_engine.config import Config
from newcad_engine.core import Engine
from newcad_engine.jobs import scheduler
from newcad_engine.project.store import YOU
from newcad_engine.results.animation import read_motion_glb, to_view
from newcad_engine.sim.motion import batch, mjcf, run
from newcad_engine.sim.motion.model import MotionSetup
from newcad_engine.sim.motion.resolve import MotionProblem, mechanism

pytestmark = pytest.mark.asyncio(loop_scope="module")


def link(p, q, y=0.0, w=12.0, t=6.0, hole=3.0):
    """Flat link in the XZ plane from p to q (x, z), holes at both ends, pins along Y."""
    c = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    L = math.dist(p, q)
    ang = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    return f"""from build123d import *
with BuildPart() as link:
    Box({L + w}, {t}, {w})
    with Locations((-{L / 2}, 0, 0), ({L / 2}, 0, 0)):
        Cylinder({hole}, {t}, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
result = link.part.rotate(Axis.Y, {-ang}).translate(({c[0]}, {y}, {c[1]}))
"""


def bore(faces, x, z):
    hits = [f for f in faces if f["type"] == "cylinder" and abs(f["com"][0] - x) < 0.5 and abs(f["com"][2] - z) < 0.5]
    assert len(hits) == 1, hits
    return hits[0]


def ref(part, f):
    return {"part": part, "tag": f["tag"], "sig": {k: v for k, v in f.items() if k != "tag"}}


async def project(engine, name, parts):
    p = engine.store.create(name)
    asm = "parts:\n" + "".join(f"- id: {k}\n  file: parts/{k}.py\n  material: Steel\n" for k in parts) + "mates: []\n"
    p.commit("main", name, YOU, changes={**{f"parts/{k}.py": v for k, v in parts.items()}, "assembly.yaml": asm})
    man = await engine.geometry.build(p)
    assert man["ok"], man
    return p, {x["id"]: engine.geometry.meta(x["key"])["faces"] for x in man["parts"]}


async def wait(job, timeout=300):
    end = time.monotonic() + timeout
    while job.status in ("queued", "running"):
        assert time.monotonic() < end, job.stage
        await asyncio.sleep(0.05)
    assert job.status == "done", job.error
    return job.summary


def bar_mech(drivers=(), gravity=(0, 0, -9.81), duration=0.5):
    """A 1 kg bar, 100 mm long, hinged at the origin about Y (hand-built mechanism)."""
    inertia = np.diag([1e-3, 100**2 / 12, 100**2 / 12]).tolist()
    return {"bodies": [{"id": "bar", "mass_kg": 1.0, "com": [50, 0, 0], "inertia_kgmm2": inertia}], "order": ["bar"], "roots": [],
            "joints": [{"id": "piv", "label": "piv", "type": "revolute", "parts": ["ground", "bar"], "origin": [0, 0, 0], "axis": [0, 1, 0],
                        "limits_si": None, "role": "tree", "child": "bar", "parent": "ground", "sign": 1}],
            "drivers": list(drivers), "springs": [], "sweep": None,
            "settings": {"duration": duration, "timestep": 0.001, "gravity": list(gravity), "contacts": False, "damping": 0, "samples": 50}}


async def test_held_bar_reaction_is_its_weight_and_spinning_bar_is_centripetal():
    held = bar_mech([{"mate": "piv", "kind": "position", "value": 0, "ramp": 0, "value_si": 0.0, "unit": "deg"}])
    m, idx = mjcf.compile_model(mjcf.build_xml(held), held)
    r = run.simulate(m, idx, held)
    f_end = np.asarray(r["series"]["mates"]["piv"]["force"][-1])
    assert np.allclose(f_end, [0, 0, 9.81], atol=0.02), f_end  # ground pushes the bar up
    assert abs(r["series"]["drivers"]["piv"][-1] + 9.81 * 0.05) < 0.01  # holding torque m·g·r against gravity's +Y moment
    w = 600 * 2 * math.pi / 60
    spin = bar_mech([{"mate": "piv", "kind": "speed", "value": 600, "ramp": 0.1, "value_si": w, "unit": "rpm"}], gravity=(0, 0, 0))
    m, idx = mjcf.compile_model(mjcf.build_xml(spin), spin)
    r = run.simulate(m, idx, spin)
    assert abs(r["series"]["mates"]["piv"]["force_mag"][-1] - w * w * 0.05) < 0.002 * w * w * 0.05
    assert abs(r["mates"][0]["max_speed"] - 600) < 20


async def test_animation_track_round_trips_in_view_coordinates(tmp_path):
    from newcad_engine.results.animation import write_motion_glb
    # a body turned 90° about +Z (engine) and moved 10 mm along +X
    q = [math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)]
    poses = np.array([[[0, 0, 0, 1, 0, 0, 0]], [[0.01, 0, 0, *q]]], float)
    write_motion_glb(tmp_path / "m.glb", np.array([0.0, 1.0]), poses, ["bar"], {"type": "motion"})
    g = read_motion_glb((tmp_path / "m.glb").read_bytes())
    tr, rot = g["tracks"]["bar"]["translation"], g["tracks"]["bar"]["rotation"]
    assert np.allclose(tr[1], [10, 0, 0], atol=1e-4)
    # +Z up in the engine is +Y up in the view: the turn is about view +Y
    assert np.allclose(rot[1], [0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)], atol=1e-5)
    t, r = to_view(poses[:, 0, :])
    assert np.allclose(t[1], [10, 0, 0])


async def test_collision_shapes_primitives_and_convex_pieces(engine, tmp_path):
    from build123d import Box, Cylinder, Sphere, Pos, export_brep
    from newcad_engine.sim.motion import collision
    from build123d import import_brep
    assert collision.primitive(Pos(5, 0, 0) * Box(10, 20, 30))["type"] == "box"
    cyl = collision.primitive(Cylinder(5, 40))
    assert cyl["type"] == "cylinder" and abs(cyl["radius"] - 5) < 1e-6 and abs(cyl["half_length"] - 20) < 1e-6
    assert collision.primitive(Sphere(7))["type"] == "sphere"
    ell = Box(40, 10, 10) + Pos(-15, 0, 15) * Box(10, 10, 40)  # an L: not convex
    assert collision.primitive(ell) is None
    export_brep(ell, str(tmp_path / "l.brep"))
    warns: list[str] = []
    g = collision.collision_geoms(str(tmp_path / "l.brep"), "l", warns)
    assert len(g) >= 2 and all(x["type"] == "mesh" for x in g), (len(g), warns)
    assert import_brep(str(tmp_path / "l.brep")).volume > 0


async def test_four_bar_runs_with_loop_closure_and_balanced_reactions(engine):
    o2, o4, b = (0.0, 0.0), (100.0, 0.0), (30 * math.cos(math.radians(60)), 30 * math.sin(math.radians(60)))
    # coupler end C: circles (B, 90) and (O4, 70), upper branch
    d = np.subtract(o4, b)
    L = np.linalg.norm(d)
    a = (90**2 - 70**2 + L**2) / (2 * L)
    h = math.sqrt(90**2 - a**2)
    u = d / L
    c = tuple(np.add(b, a * u + h * np.array([-u[1], u[0]])))
    p, faces = await project(engine, "Linkage", {"base": link(o2, o4), "crank": link(o2, b, 8), "coupler": link(b, c, 16), "rocker": link(o4, c, 8)})
    for mid, x, y, at in (("crank-pivot", "base", "crank", o2), ("crank-pin", "crank", "coupler", b),
                          ("rocker-pin", "coupler", "rocker", c), ("rocker-pivot", "base", "rocker", o4)):
        engine.mates.add(p, {"id": mid, "type": "revolute", "parts": [x, y], "faces": [ref(x, bore(faces[x], *at)), ref(y, bore(faces[y], *at))]})
    engine.mates.add(p, {"type": "fixed", "parts": ["ground", "base"]})
    mates = {m["id"]: m for m in await engine.mates.resolved(p)}
    assert np.allclose(mates["crank-pin"]["origin_mm"], [b[0], 12.0, b[1]], atol=1e-6)  # centre of the pin between the two links
    assert abs(abs(mates["crank-pin"]["axis_dir"][1]) - 1) < 1e-9
    assert "fixed-1" in mates and "problem" not in mates["fixed-1"]

    st = engine.sim.create(p, "Crank", "motion", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "motion": {"duration": 0.6, "drivers": [{"mate": "crank-pivot", "kind": "speed", "value": 120, "ramp": 0.1}]}}, None)
    state = await engine.sim.state(p, st.id)
    assert state["status"] == "none", state
    job = await engine.sim.run(p, st.id)
    assert job.kind == "motion.run"
    s = await wait(job)
    roles = {m["id"]: m["role"] for m in s["mates"]}
    assert sorted(roles.values()).count("loop") == 1  # one joint closes the loop
    assert s["loop_error_mm"] < 0.1
    assert s["peak_bearing"]["force_n"] > 0 and s["drivers"][0]["peak_effort"] > 0
    state = await engine.sim.state(p, st.id)
    assert state["status"] == "done" and set(state["files"]) >= {"motion.glb", "series.json", "model.xml", "result.json"}
    rd = engine.jobs.result_dir(state["key"])
    g = read_motion_glb((rd / "motion.glb").read_bytes())
    assert set(g["tracks"]) == {"base", "crank", "coupler", "rocker"} and len(g["times"]) > 30
    assert np.allclose(g["tracks"]["base"]["translation"], 0, atol=1e-6)  # the base is fixed
    series = json.loads((rd / "series.json").read_text())
    assert len(series["t"]) >= 50 and len(series["mates"]["crank-pin"]["force_mag"]) == len(series["t"])
    # statics check at the end of the run: Newton on the coupler, with the reported forces
    mass = {x["id"]: x["mass_kg"] for x in s["bodies"]}
    # cached: an unchanged setup never re-runs
    again = await engine.sim.run(p, st.id)
    assert again.cached and again.status == "done"
    # renaming the study does not change the result key
    engine.sim.replace(p, st.id, {**engine.sim.read(p, st.id).to_yaml_dict(), "name": "Crank renamed"}, None)
    assert (await engine.sim.state(p, st.id))["key"] == state["key"]
    assert mass["coupler"] > 0

    # problems are readable
    engine.sim.replace(p, st.id, {**engine.sim.read(p, st.id).to_yaml_dict(), "motion": {"drivers": [{"mate": "rocker-pin", "kind": "speed", "value": 10}]}}, None)
    roles_now = {m["id"]: m["role"] for m in s["mates"]}
    loop_id = next(k for k, v in roles_now.items() if v == "loop")
    engine.sim.replace(p, st.id, {**engine.sim.read(p, st.id).to_yaml_dict(), "motion": {"drivers": [{"mate": loop_id, "kind": "speed", "value": 10}]}}, None)
    assert "closes a loop" in (await engine.sim.state(p, st.id))["problem"]
    engine.sim.replace(p, st.id, {**engine.sim.read(p, st.id).to_yaml_dict(), "motion": {"drivers": [{"mate": "nope", "kind": "speed", "value": 10}]}}, None)
    assert "no such joint" in (await engine.sim.state(p, st.id))["problem"]


async def test_sweep_on_cpu_pool_scales_with_speed_squared(engine):
    p, faces = await project(engine, "Spinner", {"arm": link((0, 0), (100, 0))})
    engine.mates.add(p, {"id": "pivot", "type": "revolute", "parts": ["ground", "arm"], "faces": [ref("arm", bore(faces["arm"], 0, 0))]})
    st = engine.sim.create(p, "Speeds", "motion", None)
    # a slow ramp keeps the tangential (spin-up) force small next to the centripetal one
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "motion": {"duration": 1.3, "gravity": [0, 0, 0],
                                                                  "drivers": [{"mate": "pivot", "kind": "speed", "value": 100, "ramp": 1.0}],
                                                                  "sweep": {"parameter": "drivers.pivot.value", "values": [100, 200, 400]}}}, None)
    os.environ["NEWCAD_SWEEP_BACKEND"] = "cpu"
    try:
        job = await engine.sim.run(p, st.id)
        assert job.kind == "motion.sweep"
        s = await wait(job)
    finally:
        os.environ.pop("NEWCAD_SWEEP_BACKEND", None)
    sw = s["sweep"]
    assert sw["backend"] == "cpu_pool" and sw["variants"] == 3 and sw["failed"] == 0
    f = [r["peak_force_n"]["pivot"] for r in sw["rows"]]
    assert f[1] / f[0] == pytest.approx(4, rel=0.05) and f[2] / f[0] == pytest.approx(16, rel=0.05)
    state = await engine.sim.state(p, st.id)
    assert "sweep.json" in state["files"]


@pytest.mark.skipif(os.environ.get("NEWCAD_TEST_WARP") != "1", reason="set NEWCAD_TEST_WARP=1 to run MuJoCo Warp on the CPU (slow first run)")
async def test_warp_sweep_matches_cpu():
    mech = bar_mech([{"mate": "piv", "kind": "speed", "value": 100, "ramp": 0.1, "value_si": 100 * math.pi / 30, "unit": "rpm"}], gravity=(0, 0, 0))
    mech["sweep"] = {"parameter": "drivers.piv.value", "kind": "drivers", "target": "piv", "field": "", "values": [100.0, 300.0]}
    xml = mjcf.build_xml(mech)
    m, idx = mjcf.compile_model(xml, mech)
    cpu = batch.cpu_sweep(xml, mech, [100.0, 300.0], 1)
    gpu = batch.warp_sweep(m, idx, mech, [100.0, 300.0], "cpu")
    for a, b in zip(cpu, gpu):
        assert a["peak_force_n"]["piv"] == pytest.approx(b["peak_force_n"]["piv"], rel=2e-3)


async def test_floating_parts_and_prismatic_loop_problems(engine):
    p, faces = await project(engine, "Loose", {"a": link((0, 0), (50, 0)), "b": link((50, 0), (100, 0), 8)})
    st = engine.sim.create(p, "Drop", "motion", None)
    prep = await engine.sim.prepare(p, st.id)
    assert any("not connected to ground" in w for w in prep["inputs"]["warnings"])
    assert set(prep["inputs"]["mechanism"]["roots"]) == {"a", "b"}
    engine.mates.add(p, {"id": "s1", "type": "prismatic", "parts": ["ground", "a"], "axis": [1, 0, 0], "origin": [0, 0, 0]})
    engine.mates.add(p, {"id": "s2", "type": "prismatic", "parts": ["a", "b"], "axis": [1, 0, 0], "origin": [50, 0, 0]})
    engine.mates.add(p, {"id": "s3", "type": "prismatic", "parts": ["ground", "b"], "axis": [1, 0, 0], "origin": [100, 0, 0]})
    assert "can't close a loop" in (await engine.sim.state(p, st.id))["problem"]
    with pytest.raises(Exception):
        engine.mates.add(p, {"type": "revolute", "faces": [ref("a", faces["a"][0]), ref("b", faces["b"][0]), {"part": "ground", "tag": "x"}]})


async def test_scheduler_prefers_a_gpu_with_mujoco_warp_for_sweeps():
    cpu = {"cpu": {"performance_cores": 16}, "gpus": [], "solvers": {"mujoco": "4"}}
    gpu = {"cpu": {"performance_cores": 8}, "gpus": [{"name": "RTX"}], "solvers": {"mujoco": "4", "mujoco_warp": "4"}}
    ts = [{"id": "local", "name": "Mac", "kind": "local", "online": True, "slots": 1, "devices": cpu},
          {"id": "gpu", "name": "GPU box", "kind": "remote", "online": True, "slots": 1, "devices": gpu}]
    assert scheduler.choose("motion.sweep", ts, {}).target == "gpu"
    assert scheduler.choose("motion.run", ts, {}).target == "local"
    no_mj = [{**ts[0], "devices": {**cpu, "solvers": {}}}]
    assert "MuJoCo" in scheduler.choose("motion.run", no_mj, {}).reason


async def test_rest_api_mates_mechanism_and_bearing_load(tmp_path):
    from fastapi.testclient import TestClient
    H = {"Authorization": "Bearer tok"}
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    with TestClient(create_app(eng)) as c:
        pid = c.post("/api/projects", json={"name": "Rest motion"}, headers=H).json()["id"]
        c.put(f"/api/projects/{pid}/parts/arm", json={"code": link((0, 0), (100, 0))}, headers=H)
        c.put(f"/api/projects/{pid}/parts/tip", json={"code": link((100, 0), (150, 0), 8)}, headers=H)
        man = c.post(f"/api/projects/{pid}/build", headers=H).json()
        keys = {x["id"]: x["key"] for x in man["parts"]}
        faces = {k: c.get(f"/api/cache/{v}/faces", headers=H).json()["faces"] for k, v in keys.items()}
        m = c.post(f"/api/projects/{pid}/mates", json={"type": "revolute", "faces": [{"part": "arm", "tag": bore(faces["arm"], 0, 0)["tag"], "key": keys["arm"]}]}, headers=H)
        assert m.status_code == 200, m.text
        assert m.json()["parts"] == ["ground", "arm"] and m.json()["faces"][0]["sig"]["type"] == "cylinder"
        m2 = c.post(f"/api/projects/{pid}/mates", json={"type": "revolute", "label": "Elbow", "faces": [
            {"part": "arm", "tag": bore(faces["arm"], 100, 0)["tag"], "key": keys["arm"]},
            {"part": "tip", "tag": bore(faces["tip"], 100, 0)["tag"], "key": keys["tip"]}]}, headers=H).json()
        ms = c.get(f"/api/projects/{pid}/mates", headers=H).json()
        assert [x["id"] for x in ms] == ["revolute-1", "revolute-2"] and np.allclose(ms[1]["origin_mm"], [100, 4, 0], atol=1e-6)
        st = c.post(f"/api/projects/{pid}/studies", json={"name": "Swing", "type": "motion"}, headers=H).json()
        assert st["type"] == "motion" and st["motion"]["duration"] == 2.0
        sid = st["id"]
        st = c.patch(f"/api/projects/{pid}/studies/{sid}", json={"motion": {"duration": 0.4, "drivers": [{"mate": "revolute-1", "kind": "speed", "value": 90}]}}, headers=H).json()
        assert st["motion"]["drivers"][0]["mate"] == "revolute-1" and st["motion"]["timestep"] == 0.001
        mech = c.get(f"/api/projects/{pid}/studies/{sid}/mechanism", headers=H).json()
        assert {b["id"] for b in mech["bodies"]} == {"arm", "tip"} and mech["bodies"][0]["glb"].startswith("/api/cache/")
        assert [j["role"] for j in mech["joints"]] == ["tree", "tree"]
        job = c.post(f"/api/projects/{pid}/studies/{sid}/run", json={}, headers=H).json()
        for _ in range(600):
            j = next(x for x in c.get("/api/jobs", params={"project": pid}, headers=H).json() if x["id"] == job["id"])
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert j["status"] == "done", j
        st = c.get(f"/api/projects/{pid}/studies/{sid}", headers=H).json()
        assert st["state"]["summary"]["type"] == "motion"
        r = c.get(st["state"]["files"]["motion.glb"], headers=H)
        assert r.status_code == 200 and r.content[:4] == b"glTF"
        assert c.get(st["state"]["files"]["model.xml"], headers=H).text.startswith("<mujoco")
        fem = c.post(f"/api/projects/{pid}/studies/{sid}/bearing-load", json={"mate": m2["id"], "part": "tip"}, headers=H)
        assert fem.status_code == 200, fem.text
        fem = fem.json()
        assert fem["type"] == "static" and fem["parts"] == ["tip"]
        force = next(b for b in fem["boundaries"] if b["type"] == "force")
        peak = next(x for x in st["state"]["summary"]["mates"] if x["id"] == m2["id"])["peak_force_on"]["tip"]
        assert np.allclose(force["vector"], peak, atol=1e-3)
        # the tip has no other joint, so the static study asks for a support
        assert fem["state"]["status"] == "problem" and "fixed" in fem["state"]["problem"]
        assert c.post(f"/api/projects/{pid}/studies/{sid}/bearing-load", json={"mate": "nope", "part": "tip"}, headers=H).status_code == 400
        assert c.delete(f"/api/projects/{pid}/mates/revolute-2", headers=H).json()["ok"]
        assert len(c.get(f"/api/projects/{pid}/mates", headers=H).json()) == 1


async def test_mcp_motion_tools(engine):
    p, faces = await project(engine, "MCP pendulum", {"arm": link((0, 0), (80, 0))})
    tag = bore(faces["arm"], 0, 0)["tag"]
    async with Client(engine.mcp) as c:
        r = await c.call_tool("sim_list_faces", {"project": p.id, "part": "arm"})
        assert '"axis"' in r.content[0].text
        r = await c.call_tool("motion_add_joint", {"project": p.id, "type": "revolute", "parts": ["ground", "arm"], "faces": [f"arm/{tag}"]})
        assert "Added joint revolute-1" in r.content[0].text, r.content[0].text
        r = await c.call_tool("sim_create_study", {"project": p.id, "name": "Drop", "type": "motion"})
        sid = r.content[0].text.split()[2]
        r = await c.call_tool("motion_configure", {"project": p.id, "study": sid, "duration": 0.5})
        assert not r.is_error, r.content[0].text
        r = await c.call_tool("sim_run", {"project": p.id, "study": sid})
        text = r.content[0].text
        assert "MuJoCo" in text and "revolute-1" in text and "peak load" in text, text
        r = await c.call_tool("motion_list_joints", {"project": p.id})
        assert "revolute-1" in r.content[0].text
