import pytest
from mcp import Client

from newcad_engine.core import bot_actor, current_actor

pytestmark = pytest.mark.asyncio(loop_scope="module")

GROUPS = ("project_", "spec_", "geometry_", "view_", "notes_")


async def test_tool_groups_and_resources(engine):
    async with Client(engine.mcp) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        for g in GROUPS:
            assert any(n.startswith(g) for n in names), g
        for n in ("project_list", "project_open", "project_create_branch", "project_commit", "project_diff", "project_checkout",
                  "spec_read", "spec_answer", "spec_add_question", "spec_open_questions",
                  "geometry_write_part", "geometry_patch_part", "geometry_rebuild", "geometry_measure", "geometry_export",
                  "view_snapshot", "notes_list", "notes_resolve"):
            assert n in names
        templates = {t.uri_template for t in (await c.list_resource_templates()).resource_templates}
        assert {"newcad://projects/{project}/spec", "newcad://projects/{project}/assembly", "newcad://projects/{project}/snapshot"} <= templates


async def test_external_agent_lists_edits_rebuilds_and_commits(engine):
    async with Client(engine.mcp) as c:
        r = await c.call_tool("project_create", {"name": "MCP bracket", "template": "demo"})
        assert not r.is_error
        pid = "mcp-bracket"
        r = await c.call_tool("geometry_patch_part", {"project": pid, "part": "plate", "find": "Box(220, 140", "replace": "Box(200, 140"})
        assert not r.is_error, r.content[0].text
        r = await c.call_tool("geometry_rebuild", {"project": pid})
        text = r.content[0].text
        assert "plate OK" in text and "FAILED" not in text
        r = await c.call_tool("project_commit", {"project": pid, "message": "Shorter plate"})
        assert "Committed" in r.content[0].text
        log = (await c.call_tool("project_log", {"project": pid})).content[0].text
        assert "Agent: Shorter plate" in log
        snap = await c.call_tool("view_snapshot", {"project": pid, "view": "front"})
        assert [x.type for x in snap.content] == ["text", "image"]
        spec = await c.read_resource(f"newcad://projects/{pid}/spec")
        assert "categories" in spec.contents[0].text


async def test_errors_come_back_as_readable_tool_errors(engine):
    engine.store.create("MCP errors")
    async with Client(engine.mcp) as c:
        r = await c.call_tool("geometry_write_part", {"project": "mcp-errors", "part": "base", "code": "result = Box(1, 1)"})
        assert not r.is_error
        r = await c.call_tool("geometry_rebuild", {"project": "mcp-errors"})
        assert "base FAILED (line 3)" in r.content[0].text
        r = await c.call_tool("geometry_patch_part", {"project": "mcp-errors", "part": "nope", "find": "a", "replace": "b"})
        assert r.is_error and "No part 'nope'" in r.content[0].text
        r = await c.call_tool("spec_answer", {"project": "mcp-errors", "question_id": "zzz", "text": "x"})
        assert r.is_error and "No question" in r.content[0].text


async def test_bot_guard_pins_project_and_branch(engine):
    p = engine.store.create("MCP guard", template="demo")
    b = p.create_branch("bot/work")
    other = engine.store.create("Other project")
    tok = current_actor.set(bot_actor(p.id, b, "t1"))
    try:
        async with Client(engine.mcp) as c:
            r = await c.call_tool("geometry_patch_part", {"project": p.id, "part": "plate", "find": "Box(220", "replace": "Box(210", "branch": "main"})
            assert r.is_error and "only change branch bot/work" in r.content[0].text
            r = await c.call_tool("geometry_patch_part", {"project": p.id, "part": "plate", "find": "Box(220", "replace": "Box(210"})
            assert not r.is_error
            r = await c.call_tool("project_checkout", {"project": p.id, "ref": b})
            assert r.is_error
            r = await c.call_tool("project_open", {"project": other.id})
            assert r.is_error and "only" in r.content[0].text
            r = await c.call_tool("project_commit", {"project": p.id, "message": "bot edit"})
            assert "on bot/work" in r.content[0].text
    finally:
        current_actor.reset(tok)
    assert "Box(220" in p.read("parts/plate.py", "main")
    assert "Box(210" in p.read("parts/plate.py", b)
    assert p.head_ref() == "main"


async def test_notes_list_rematches_faces_after_a_rebuild(engine):
    from newcad_engine.project import spec as S
    from newcad_engine.project.store import YOU
    from newcad_engine.project.templates import dump
    p = engine.store.create("MCP notes", template="demo")
    man = await engine.geometry.build(p)
    plate = man["parts"][0]
    face = engine.geometry.meta(plate["key"])["faces"][0]
    notes = {"notes": []}
    S.add_note(notes, "plate", "Round this edge", "You", None, face["tag"], {k: v for k, v in face.items() if k != "tag"}, queued=True)
    p.commit("main", "Comment", YOU, changes={"notes.yaml": dump(notes)})
    async with Client(engine.mcp) as c:
        r = await c.call_tool("notes_list", {"project": p.id, "status": "queued"})
        assert '"face_now"' in r.content[0].text and face["tag"] in r.content[0].text
        r = await c.call_tool("notes_resolve", {"project": p.id, "note_id": 1, "reply": "Done"})
        assert not r.is_error
    assert p.read_yaml("notes.yaml")["notes"][0]["status"] == "resolved"
