import asyncio
import json

import httpx
import numpy as np
import os
import shutil

import pytest
from mcp import Client

from newcad_engine.api.app import create_app
from newcad_engine.config import Config
from newcad_engine.core import Engine
from newcad_engine.jobs import scheduler
from newcad_engine.jobs.targets import RemoteTarget
from newcad_engine.project.store import YOU
from newcad_engine.results.fields import read_field_glb
from newcad_engine.sim import study as St

pytestmark = [
    pytest.mark.skipif(shutil.which(os.environ.get("NEWCAD_CCX") or "ccx") is None, reason="CalculiX (ccx) is not installed"),
    pytest.mark.asyncio(loop_scope="module"),
]

BEAM = """from build123d import *
L, B, H = 200, 20, 20
result = Box(L, B, H, align=(Align.MIN, Align.CENTER, Align.CENTER))
"""
STACK = """from build123d import *
result = Box(40, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
"""
TOP = """from build123d import *
result = Pos(0, 0, 10) * Box(20, 20, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
"""


async def wait(engine, job, timeout=120):
    end = asyncio.get_running_loop().time() + timeout
    while job.status in ("queued", "running"):
        assert asyncio.get_running_loop().time() < end, f"job stuck: {job.stage}"
        await asyncio.sleep(0.1)
    return job


async def faces_of(engine, p, part):
    man = await engine.geometry.build(p, None, [part])
    x = next(q for q in man["parts"] if q["id"] == part)
    return x["key"], engine.geometry.meta(x["key"])["faces"]


def pick(faces, axis, sign):
    return next(f for f in faces if f.get("normal") and f["normal"][axis] * sign > 0.99 and
                all(abs(f["normal"][k]) < 1e-6 for k in range(3) if k != axis) and
                f["center"][axis] * sign == max(g["center"][axis] * sign for g in faces if g.get("normal") and g["normal"][axis] * sign > 0.99))


def ref(part, f):
    return {"part": part, "tag": f["tag"], "sig": {k: v for k, v in f.items() if k != "tag"}}


async def beam_project(engine, name):
    p = engine.store.create(name)
    p.commit("main", "Beam", YOU, changes={"parts/beam.py": BEAM, "assembly.yaml": "parts:\n- id: beam\n  name: Beam\n  file: parts/beam.py\n  material: Steel\n"})
    key, faces = await faces_of(engine, p, "beam")
    return p, faces


async def test_scheduler_matches_solvers_and_devices():
    local = {"id": "local", "name": "Mac", "kind": "local", "online": True, "slots": 1,
             "devices": {"cpu": {"performance_cores": 10}, "gpus": [], "solvers": {"gmsh": "4", "calculix": "2.21"}}}
    gpu = {"id": "gpu", "name": "GPU box", "kind": "remote", "online": True, "slots": 2,
           "devices": {"cpu": {"performance_cores": 32}, "gpus": [{"name": "RTX"}], "solvers": {"gmsh": "4", "calculix": "2.21"}}}
    bare = {"id": "bare", "name": "Bare", "kind": "remote", "online": True, "slots": 1, "devices": {"cpu": {}, "gpus": [], "solvers": {}}}
    assert scheduler.choose("fem.static", [local, gpu], {}).target == "local"          # CPU FEM stays local
    assert scheduler.choose("fem.static", [local, gpu], {"local": 1}).target == "gpu"  # unless local is busy
    assert scheduler.choose("fem.static", [local, gpu], {}, pinned="gpu").target == "gpu"
    c = scheduler.choose("fem.static", [bare], {})
    assert c.target is None and "no Gmsh, CalculiX" in c.reason and not c.candidates
    assert scheduler.choose("fem.static", [local], {"local": 1}).candidates == ["local"]  # waits, doesn't fail


async def test_static_cantilever_matches_beam_theory_and_caches(engine):
    p, faces = await beam_project(engine, "Sim beam")
    fix, tip = pick(faces, 0, -1), pick(faces, 0, 1)
    st = engine.sim.create(p, "Tip load", "static", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "mesh": {"size": 5}, "boundaries": [
        {"id": "fixed-1", "type": "fixed", "faces": [ref("beam", fix)]},
        {"id": "force-1", "type": "force", "faces": [ref("beam", tip)], "vector": [0, 0, -1000]},
    ]}, None)
    job = await wait(engine, await engine.sim.run(p, st.id))
    assert job.status == "done", job.error
    s = job.summary
    E, I, L = 210_000, 20 * 20**3 / 12, 200
    assert s["max_displacement_mm"] == pytest.approx(1000 * L**3 / (3 * E * I), rel=0.02)
    assert s["max_von_mises_mpa"] == pytest.approx(1000 * L * 10 / I, rel=0.1)  # 150 MPa at the root (corner singularity aside)
    assert s["max_von_mises_at"]["part"] == "beam" and s["max_von_mises_at"]["point"][0] < 20
    assert s["reactions_n"] and s["reactions_n"][0][2] == pytest.approx(1000, rel=1e-3)
    assert s["min_safety_factor"] == pytest.approx(250 / s["max_von_mises_mpa"], rel=1e-3)
    # field GLB: raw values per vertex, face ids into "part/tag", Y-up
    g = read_field_glb((engine.jobs.result_dir(job.key) / "field.glb").read_bytes())
    a = g["attributes"]
    assert {"POSITION", "NORMAL", "_FACE_ID", "_VON_MISES", "_SAFETY", "_DISP"} <= set(a)
    assert a["_VON_MISES"].max() == pytest.approx(g["extras"]["fields"]["von_mises"]["max"], rel=1e-5)
    assert f"beam/{tip['tag']}" in g["extras"]["faceTags"]
    assert a["_DISP"][:, 1].min() < -0.5  # downward (-Z) load is -Y in glTF
    # outward normals: the top face (+Z model, +Y glTF) has normals pointing up
    top = g["extras"]["faceTags"].index(f"beam/{pick(faces, 2, 1)['tag']}")
    sel = a["_FACE_ID"] == top
    assert a["NORMAL"][sel][:, 1].mean() > 0.99
    # the same setup again comes from the cache
    again = await engine.sim.run(p, st.id)
    assert again.status == "done" and again.cached and again.key == job.key
    state = await engine.sim.state(p, st.id)
    assert state["status"] == "done" and state["files"]["field.glb"].endswith("/field.glb")


async def test_modal_and_thermal(engine):
    p, faces = await beam_project(engine, "Sim modal")
    fix = pick(faces, 0, -1)
    st = engine.sim.create(p, "Modes", "modal", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "modes": 4, "mesh": {"size": 5},
                                  "boundaries": [{"id": "fixed-1", "type": "fixed", "faces": [ref("beam", fix)]}]}, None)
    job = await wait(engine, await engine.sim.run(p, st.id))
    assert job.status == "done", job.error
    E, I, rho, A, L = 210_000, 20 * 20**3 / 12, 7850e-12, 400, 200
    f1 = 1.875104**2 / (2 * np.pi) * np.sqrt(E * I / (rho * A * L**4))
    assert job.summary["frequencies_hz"][0] == pytest.approx(f1, rel=0.02)
    assert len(job.summary["modes"]) == 4

    th = engine.sim.create(p, "Heat", "thermal", None)
    tip = pick(faces, 0, 1)
    engine.sim.replace(p, th.id, {**th.to_yaml_dict(), "mesh": {"size": 5}, "boundaries": [
        {"id": "t", "type": "temperature", "faces": [ref("beam", fix)], "value": 20},
        {"id": "q", "type": "heat_flux", "faces": [ref("beam", tip)], "value": 10},  # 10 W into the tip
    ]}, None)
    job = await wait(engine, await engine.sim.run(p, th.id))
    assert job.status == "done", job.error
    # 1D conduction: dT = P L / (k A) with k = 50 W/(m K): 10 W * 0.2 m / (50 * 4e-4 m²) = 100 K
    assert job.summary["max_temperature_c"] == pytest.approx(120, rel=0.01)
    assert job.summary["min_temperature_c"] == pytest.approx(20, abs=0.01)


async def test_bonded_assembly_and_setup_problems(engine):
    p = engine.store.create("Sim stack")
    p.commit("main", "Stack", YOU, changes={"parts/base.py": STACK, "parts/post.py": TOP, "assembly.yaml":
             "parts:\n- id: base\n  file: parts/base.py\n  material: Steel\n- id: post\n  file: parts/post.py\n  material: Aluminium\n"})
    _, bf = await faces_of(engine, p, "base")
    _, pf = await faces_of(engine, p, "post")
    st = engine.sim.create(p, "Push", "static", None)
    with pytest.raises(Exception, match="fixed face"):
        await engine.sim.prepare(p, st.id)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "boundaries": [
        {"id": "fixed-1", "type": "fixed", "faces": [ref("base", pick(bf, 2, -1))]},
        {"id": "force-1", "type": "force", "faces": [ref("post", pick(pf, 2, 1))], "vector": [100, 0, 0]},
    ]}, None)
    job = await wait(engine, await engine.sim.run(p, st.id))
    assert job.status == "done", job.error
    assert job.summary["max_displacement_at"]["part"] == "post"
    # the base's top face is partly bonded to the post: its free part is still drawn in the result
    g = read_field_glb((engine.jobs.result_dir(job.key) / "field.glb").read_bytes())
    assert f"base/{pick(bf, 2, 1)['tag']}" in g["extras"]["faceTags"]
    # the load face moved with a taller post: it is re-matched by its signature and the user is told
    p.commit("main", "Taller", YOU, changes={"parts/post.py": TOP.replace("30", "45")})
    prep = await engine.sim.prepare(p, st.id)
    assert any("moved" in w for w in prep["inputs"]["warnings"])
    # a face that is gone beyond recognition asks for a new pick
    p.commit("main", "Round", YOU, changes={"parts/post.py": "from build123d import *\nresult = Pos(0, 0, 10) * Cylinder(5, 200, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"})
    with pytest.raises(Exception, match="Pick the face again"):
        await engine.sim.prepare(p, st.id)
    # wrong condition for the study type
    bad = St.Study(id="m", name="m", type="modal", boundaries=[St.Boundary(id="f", type="force", vector=[1, 0, 0])])
    with pytest.raises(St.StudyProblem, match="doesn't apply"):
        St.resolve(bad, {"parts": [{"id": "x", "ok": True}], "bbox": None}, {"x": {"faces": []}})


async def test_cancel_and_retry(engine):
    p, faces = await beam_project(engine, "Sim cancel")
    st = engine.sim.create(p, "Fine", "static", None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "mesh": {"size": 1.2}, "boundaries": [
        {"id": "fixed-1", "type": "fixed", "faces": [ref("beam", pick(faces, 0, -1))]},
        {"id": "force-1", "type": "force", "faces": [ref("beam", pick(faces, 0, 1))], "vector": [0, 0, -10]},
    ]}, None)
    job = await engine.sim.run(p, st.id)
    while job.status == "queued" or job.progress < 0.05:
        await asyncio.sleep(0.05)
    await engine.jobs.cancel(job.id)
    await wait(engine, job)
    assert job.status == "cancelled"
    assert engine.jobs.cached(job.key) is None
    # retry with a coarser mesh is a new key; retry of the same job re-runs it
    job.inputs["mesh"]["size"] = 8
    await engine.jobs.retry(job.id)
    await wait(engine, job)
    assert job.status == "done" and job.attempts == 2


async def test_remote_target_runs_the_same_pipeline(engine, tmp_path):
    worker = Engine(Config(home=tmp_path / "node", token="node-token-123", workers=1))
    app = create_app(worker)

    def client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node",
                                 headers={"Authorization": "Bearer node-token-123"}, timeout=60)

    remote = RemoteTarget("node", "Lab node", "http://node", "node-token-123", client_factory=client, poll_s=0.1)
    d = await remote.describe()
    assert d["online"] and d["devices"]["solvers"]["calculix"]
    # a wrong token is reported as unavailable, not as a crash
    bad = RemoteTarget("bad", "Bad", "http://node", "nope", client_factory=lambda: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://node", headers={"Authorization": "Bearer nope"}))
    assert (await bad.describe())["online"] is False

    engine.targets.remote["node"] = remote
    try:
        p, faces = await beam_project(engine, "Sim remote")
        st = engine.sim.create(p, "Remote", "static", None)
        engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "target": "node", "mesh": {"size": 6}, "boundaries": [
            {"id": "fixed-1", "type": "fixed", "faces": [ref("beam", pick(faces, 0, -1))]},
            {"id": "force-1", "type": "force", "faces": [ref("beam", pick(faces, 0, 1))], "vector": [0, 0, -500]},
        ]}, None)
        job = await wait(engine, await engine.sim.run(p, st.id))
        assert job.status == "done", job.error
        assert job.target == "node"
        assert (engine.jobs.result_dir(job.key) / "field.glb").exists()
    finally:
        engine.targets.remote.pop("node", None)
        await worker.worker.close()


async def test_bot_tools_set_up_run_and_explain(engine):
    p, _ = await beam_project(engine, "Sim mcp")
    async with Client(engine.mcp) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"sim_list_studies", "sim_create_study", "sim_list_faces", "sim_add_boundary", "sim_run", "sim_results"} <= names
        r = await c.call_tool("sim_create_study", {"project": p.id, "name": "Shelf load"})
        sid = r.content[0].text.split()[2]
        low = json.loads((await c.call_tool("sim_list_faces", {"project": p.id, "part": "beam", "facing": "-x"})).content[0].text)
        high = json.loads((await c.call_tool("sim_list_faces", {"project": p.id, "part": "beam", "facing": "+x"})).content[0].text)
        assert len(low) == 1 and len(high) == 1
        r = await c.call_tool("sim_add_boundary", {"project": p.id, "study": sid, "type": "fixed", "part": "beam", "faces": [low[0]["tag"]], "label": "Wall"})
        assert not r.is_error, r.content[0].text
        await c.call_tool("sim_add_boundary", {"project": p.id, "study": sid, "type": "force", "part": "beam", "faces": [high[0]["tag"]], "vector": [0, 0, -200]})
        await c.call_tool("sim_configure", {"project": p.id, "study": sid, "mesh_size": 6})
        r = await c.call_tool("sim_run", {"project": p.id, "study": sid})
        text = r.content[0].text
        assert not r.is_error, text
        assert "peak von Mises stress" in text and "safety factor" in text and "beam" in text
        assert "peak von Mises" in (await c.call_tool("sim_results", {"project": p.id, "study": sid})).content[0].text
    # the study is a file in git
    assert f"studies/{sid}.yaml" in p.files()


async def test_rest_api_for_the_check_tab(tmp_path):
    from fastapi.testclient import TestClient
    H = {"Authorization": "Bearer tok"}
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    with TestClient(create_app(eng)) as c:
        pid = c.post("/api/projects", json={"name": "Rest sim"}, headers=H).json()["id"]
        c.put(f"/api/projects/{pid}/parts/beam", json={"code": BEAM}, headers=H)
        man = c.post(f"/api/projects/{pid}/build", headers=H).json()
        key = man["parts"][0]["key"]
        faces = c.get(f"/api/cache/{key}/faces", headers=H).json()["faces"]
        st = c.post(f"/api/projects/{pid}/studies", json={"name": "Check", "type": "static"}, headers=H).json()
        assert st["id"] == "check"
        sid = st["id"]
        st = c.post(f"/api/projects/{pid}/studies/{sid}/boundaries", json={"type": "fixed", "faces": [{"part": "beam", "tag": pick(faces, 0, -1)["tag"], "key": key}]}, headers=H).json()
        assert st["state"]["status"] == "problem" and "load" in st["state"]["problem"]
        assert st["boundaries"][0]["faces"][0]["sig"]["type"] == "plane"
        st = c.post(f"/api/projects/{pid}/studies/{sid}/boundaries", json={"type": "pressure", "value": 1.0, "faces": [{"part": "beam", "tag": pick(faces, 2, 1)["tag"], "key": key}]}, headers=H).json()
        assert st["state"]["status"] == "none"
        st = c.patch(f"/api/projects/{pid}/studies/{sid}", json={"mesh": {"size": 6}, "materials": {"beam": "Aluminium"}}, headers=H).json()
        assert st["mesh"]["size"] == 6 and st["materials"] == {"beam": "Aluminium"}
        job = c.post(f"/api/projects/{pid}/studies/{sid}/run", json={}, headers=H).json()
        for _ in range(600):
            j = next(x for x in c.get("/api/jobs", params={"project": pid}, headers=H).json() if x["id"] == job["id"])
            if j["status"] not in ("queued", "running"):
                break
            import time
            time.sleep(0.1)
        assert j["status"] == "done", j
        st = c.get(f"/api/projects/{pid}/studies/{sid}", headers=H).json()
        assert st["state"]["status"] == "done"
        glb = c.get(st["state"]["files"]["field.glb"], headers=H)
        assert glb.status_code == 200 and glb.content[:4] == b"glTF"
        assert c.get(f"/api/results/{st['state']['key']}/../../etc", headers=H).status_code == 404
        t = c.get("/api/targets", headers=H).json()
        assert t[0]["id"] == "local" and t[0]["devices"]["solvers"]["calculix"]
        assert c.get("/api/materials", headers=H).json()[0]["name"] == "Steel"
        # the study is versioned: a commit on main by You
        log = c.get(f"/api/projects/{pid}/log", headers=H).json()
        assert any(f"studies/{sid}.yaml" in x["files"] for x in log["commits"])
