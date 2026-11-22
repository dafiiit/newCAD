import time

import numpy as np
import pytest

from newcad_engine.geometry.facetags import assign_tags, rematch, tag_of
from newcad_engine.geometry.glb import read_glb
from newcad_engine.project.store import YOU

pytestmark = pytest.mark.asyncio(loop_scope="module")

BOX = "from build123d import *\nresult = Box(10, 20, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"


async def test_demo_assembly_builds_with_mass_and_face_tags(engine):
    p = engine.store.create("Geo demo", template="demo")
    man = await engine.geometry.build(p)
    assert man["ok"], man
    assert [x["id"] for x in man["parts"]] == ["plate", "upright", "gusset"]
    assert 4.0 < man["mass_kg"] < 5.0  # steel bracket, ~4.5 kg
    g = read_glb((engine.geometry.entry(man["parts"][0]["key"]) / "part.glb").read_bytes())
    tags = g["extras"]["faceTags"]
    assert len(tags) == man["parts"][0]["faces"] and len(set(tags)) == len(tags)
    assert g["face_ids"].min() == 0 and g["face_ids"].max() < len(tags)
    # Z-up coordinates survive the GLB round trip (the plate sits on Z = 0)
    assert abs(g["positions"][:, 2].min()) < 1e-3


async def test_unchanged_parts_come_from_cache_and_rebuild_is_fast(engine):
    p = engine.store.create("Geo cache", template="demo")
    await engine.geometry.build(p)
    src = p.read("parts/upright.py").replace("150", "160")
    p.commit("main", "taller", YOU, changes={"parts/upright.py": src})
    await engine.pool.wait_ready()  # a person takes longer than the worker warm-up to edit code
    t0 = time.perf_counter()
    man = await engine.geometry.build(p)
    dt = time.perf_counter() - t0
    cached = {x["id"]: x["cached"] for x in man["parts"]}
    assert cached == {"plate": True, "upright": False, "gusset": True}
    assert dt < 2.0, f"3-part rebuild after one edit took {dt:.2f} s"


@pytest.mark.parametrize("code,needle", [
    ("import socket\nsocket.create_connection(('example.com', 80))", "socket"),
    ("open('/tmp/newcad-evil.txt', 'w').write('x')", "writing /tmp/newcad-evil.txt"),
    ("import subprocess\nsubprocess.run(['true'])", "subprocess"),
    ("import os\nos.system('true')", "os.system"),
])
async def test_sandbox_blocks_network_files_and_processes(engine, code, needle):
    r = await engine.geometry.build_part("evil", "from build123d import *\n" + code + "\nresult = Box(1, 1, 1)\n")
    assert not r["ok"] and needle in r["error"] and "sandbox" in r["error"]


async def test_errors_report_the_line_and_prints_land_in_the_log(engine):
    r = await engine.geometry.build_part("bad", "from build123d import *\nprint('hi there')\nresult = Box(1, 1)\n")
    assert not r["ok"] and r["line"] == 3 and "TypeError" in r["error"]
    r = await engine.geometry.build_part("nores", "from build123d import *\nx = 1\n")
    assert not r["ok"] and "result" in r["error"]
    r = await engine.geometry.build_part("ok", "from build123d import *\nprint('hello log')\n" + BOX.split("\n", 1)[1])
    assert r["ok"] and "hello log" in r["log"]


async def test_runaway_code_is_stopped(engine):
    old = engine.pool.timeout_s
    engine.pool.timeout_s = 3
    try:
        t0 = time.perf_counter()
        r = await engine.geometry.build_part("loop", "while True:\n    pass\n")
        assert not r["ok"] and "stopped" in r["error"]
        assert time.perf_counter() - t0 < 10
    finally:
        engine.pool.timeout_s = old


async def test_export_measure_and_snapshot(engine):
    p = engine.store.create("Geo export", template="demo")
    step = await engine.geometry.export(p, None, "step")
    assert step["bytes"] > 1000 and step["path"].endswith(".step")
    stl = await engine.geometry.export(p, None, "stl", ["plate"])
    assert stl["bytes"] > 1000
    d = await engine.geometry.measure(p, None, "distance", "plate", "gusset")
    assert d["distance_mm"] == pytest.approx(0, abs=1e-6)  # gussets sit on the plate
    asm = p.read("assembly.yaml") + "- id: far\n  name: Far\n  file: parts/far.py\n"
    asm = asm.replace("mates: []\n", "") + "mates: []\n"
    p.commit("main", "far", YOU, changes={"parts/far.py": BOX.replace("result = Box", "result = Pos(300, 0, 0) * Box"), "assembly.yaml": asm})
    d = await engine.geometry.measure(p, None, "distance", "plate", "far")
    assert d["distance_mm"] == pytest.approx(300 - 110 - 5, abs=0.01)
    c = await engine.geometry.measure(p, None, "clash", "plate", "upright")
    assert c["clash"] is False
    png, man = await engine.geometry.snapshot(p, None, "iso", (320, 240))
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and man["ok"]


def test_face_tags_are_stable_and_rematch_moved_faces():
    a = {"type": "plane", "area": 200.0, "center": [0.0, 0.0, 10.0], "normal": [0.0, 0.0, 1.0]}
    b = {"type": "plane", "area": 200.0, "center": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, -1.0]}
    assert tag_of(dict(a)) == tag_of(a)
    tags = assign_tags([a, b, a])
    assert len(set(tags)) == 3
    moved = {**a, "center": [0.0, 0.0, 12.0]}
    m = rematch(a, [(tag_of(moved), moved), (tag_of(b), b)])
    assert m["tag"] == tag_of(moved) and not m["ambiguous"]
    far = {"type": "cylinder", "area": 5.0, "center": [500.0, 0, 0], "normal": None}
    assert rematch(a, [(tag_of(far), far)])["tag"] is None
    assert np.isclose(rematch(a, [(tag_of(a), a)])["score"], 0)
