"""NewCAD MCP server: the tools BuilderBot and external agents use to design.

Served over Streamable HTTP at /mcp by the engine and over stdio by
`newcad-mcp`. BuilderBot connects to the same server in-process as an MCP
client, so the Bot and an external agent see exactly the same tools.

Tool names use `group_action` (underscores) because the Anthropic and OpenAI
tool-name rules don't allow dots.
"""
from __future__ import annotations

import functools
import json
from typing import Annotated, Any, Awaitable, Callable, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from ..core import current_actor
from ..geometry.facetags import rematch
from ..project import spec as S
from ..project.store import Project, StoreError, valid_part_id
from ..project.templates import PART_HEADER, dump

INSTRUCTIONS = """NewCAD is a CAD tool where designs are build123d Python scripts stored in a git repository per project.
- Units are millimetres, Z is up. Each part is one file parts/<id>.py that sets `result` to a build123d shape, placed in assembly coordinates.
- The What? spec (spec.yaml) holds the requirements as questions and answers. Read it before designing.
- Edits are staged on a branch; project_commit turns them into a version. Branches are concepts, commits are versions.
- After writing code, call geometry_rebuild and fix any error it reports before committing.
- view_snapshot returns a picture of the current state so you can check the result visually."""

ReadRef = Annotated[str | None, Field(description="Branch name or commit id to read. Default: the user's current version (HEAD).")]
WriteBranch = Annotated[str | None, Field(description="Branch to change. Default: the branch the user has checked out.")]
ProjectId = Annotated[str, Field(description="Project id from project_list.")]


def build_mcp(engine: Any) -> MCPServer:
    mcp = MCPServer("newcad", title="NewCAD", instructions=INSTRUCTIONS, version="0.2.0")
    store = engine.store
    geo = engine.geometry

    # ---------- helpers ----------

    def tool(name: str, read_only: bool = False, destructive: bool = False, title: str | None = None):
        """Register a tool and turn store errors into tool errors the caller can read."""
        def deco(fn: Callable[..., Awaitable[Any]]):
            @functools.wraps(fn)
            async def wrapped(*a: Any, **kw: Any) -> Any:
                try:
                    return await fn(*a, **kw)
                except StoreError as e:
                    raise ToolError(str(e)) from None
            mcp.add_tool(wrapped, name=name, title=title, description=(fn.__doc__ or "").strip(),
                         annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive, idempotentHint=read_only),
                         structured_output=False)
            return fn
        return deco

    def proj(pid: str) -> Project:
        a = current_actor.get()
        if a.project and pid != a.project:
            raise StoreError(f"This task works on project {a.project} only")
        return store.get(pid)

    def wbranch(p: Project, branch: str | None) -> str:
        """Branch a write goes to. A guarded actor (BuilderBot) can only write its own branch."""
        a = current_actor.get()
        if a.guarded:
            if branch not in (None, "HEAD", a.branch):
                raise StoreError(f"You can only change branch {a.branch} in this task")
            return a.branch  # type: ignore[return-value]
        return p._branch_for_write(branch)

    def rref(p: Project, ref: str | None) -> str | None:
        a = current_actor.get()
        if a.guarded and ref in (None, "HEAD"):
            return a.branch
        return ref

    def spec_of(p: Project, ref: str | None) -> dict[str, Any]:
        return p.read_yaml("spec.yaml", ref) or {"categories": []}

    def save_yaml(p: Project, branch: str, path: str, data: Any, message: str) -> None:
        """Spec and notes edits commit right away (small edits fold into one version)."""
        p.commit(branch, message, current_actor.get().author, changes={path: dump(data)}, include_staged=False)

    def part_entry(p: Project, ref: str | None, part: str) -> dict[str, Any]:
        for e in p.assembly(ref)["parts"]:
            if e["id"] == part:
                return e
        raise StoreError(f"No part {part!r}. Parts: {', '.join(x['id'] for x in p.assembly(ref)['parts']) or 'none yet'}")

    def manifest_text(man: dict[str, Any]) -> str:
        lines = [f"Built {man['ref']} ({man['commit'][:7]}) in {man['build_ms']} ms. Total mass {man['mass_kg']:.3f} kg, "
                 f"CG ({', '.join(f'{x:.1f}' for x in man['cg'])}) mm."]
        if man["bbox"]:
            mn, mx = man["bbox"]["min"], man["bbox"]["max"]
            lines.append(f"Overall size {mx[0]-mn[0]:.1f} x {mx[1]-mn[1]:.1f} x {mx[2]-mn[2]:.1f} mm (X x Y x Z).")
        for r in man["parts"]:
            if r["ok"]:
                mn, mx = r["bbox"]["min"], r["bbox"]["max"]
                lines.append(f"- {r['id']} OK: {r['mass_kg']:.3f} kg {r['material']}, bbox [{', '.join(f'{v:.1f}' for v in mn)}] to [{', '.join(f'{v:.1f}' for v in mx)}], {r['faces']} faces")
            else:
                where = f" (line {r['line']})" if r.get("line") else ""
                lines.append(f"- {r['id']} FAILED{where}: {r['error']}")
                if r.get("log", "").strip():
                    lines.append("  log: " + r["log"].strip()[-600:].replace("\n", "\n  "))
        if not man["parts"]:
            lines.append("The assembly has no parts yet. Add one with geometry_write_part.")
        return "\n".join(lines)

    # ---------- project.* ----------

    @tool("project_list", read_only=True)
    async def project_list() -> str:
        """List all projects with their branches and current version."""
        a = current_actor.get()
        items = [s for s in store.list() if not a.project or s["id"] == a.project]
        return json.dumps(items, indent=1)

    @tool("project_open", read_only=True)
    async def project_open(project: ProjectId, ref: ReadRef = None) -> str:
        """Overview of a project: goal, branches, parts, open questions and uncommitted changes."""
        p = proj(project)
        ref = rref(p, ref)
        s = p.summary()
        spec = spec_of(p, ref)
        s["viewing"] = ref or p.head_ref()
        s["parts"] = p.assembly(ref)["parts"]
        s["openQuestions"] = len(S.open_questions(spec))
        try:
            br = ref if p.is_branch(ref) else p.head_branch()
            s["uncommitted"] = sorted(p.staged(br)) if br else []
        except StoreError:
            s["uncommitted"] = []
        return json.dumps(s, indent=1)

    @tool("project_create")
    async def project_create(name: Annotated[str, Field(description="Project name")],
                             goal: Annotated[str, Field(description="What it should do, in a sentence or two")] = "",
                             template: Annotated[Literal["blank", "demo"], Field(description="blank, or demo (a 3-part bracket)")] = "blank") -> str:
        """Create a new project. It starts with the generic What? questions and no parts."""
        if current_actor.get().guarded:
            raise StoreError("A Bot task can't create projects")
        p = store.create(name, goal, template, current_actor.get().author)
        return json.dumps(p.summary(), indent=1)

    @tool("project_create_branch")
    async def project_create_branch(project: ProjectId, name: Annotated[str, Field(description="New branch name, e.g. concept-d")],
                                    from_ref: ReadRef = None) -> str:
        """Create a branch (a concept) from a version without switching to it."""
        if current_actor.get().guarded:
            raise StoreError("A Bot task works on its own branch and can't create others")
        p = proj(project)
        b = p.create_branch(name, from_ref)
        return f"Created branch {b} at {str(p.resolve(b).id)[:7]}"

    @tool("project_commit")
    async def project_commit(project: ProjectId, message: Annotated[str, Field(description="What changed and why, one line")],
                             branch: WriteBranch = None) -> str:
        """Commit the staged edits on a branch as a new version."""
        p = proj(project)
        b = wbranch(p, branch)
        info = p.commit(b, message, current_actor.get().author)
        return f"Nothing to commit on {b}." if info is None else f"Committed {info.short} on {b}: {info.message} ({', '.join(info.files)})"

    @tool("project_diff", read_only=True)
    async def project_diff(project: ProjectId, a: Annotated[str, Field(description="Base branch or commit")],
                           b: Annotated[str, Field(description="Other branch or commit")]) -> str:
        """Unified diff of every file between two versions."""
        p = proj(project)
        d = p.diff(a, b)
        return "\n\n".join(x["diff"] for x in d) or "No differences."

    @tool("project_log", read_only=True)
    async def project_log(project: ProjectId, limit: int = 30) -> str:
        """Version history across all branches: id, branch, author, time and message."""
        p = proj(project)
        return "\n".join(f"{c.short} [{c.branch}] {c.author}: {c.message}" for c in p.log()[-limit:])

    @tool("project_checkout")
    async def project_checkout(project: ProjectId, ref: Annotated[str, Field(description="Branch or commit to switch the user's view to")]) -> str:
        """Switch the user's current version (HEAD). Not available to BuilderBot."""
        if current_actor.get().guarded:
            raise StoreError("BuilderBot can't switch the user's version; the user checks out branches")
        p = proj(project)
        return f"HEAD is now {p.checkout(ref)}"

    # ---------- spec.* ----------

    @tool("spec_read", read_only=True)
    async def spec_read(project: ProjectId, ref: ReadRef = None) -> str:
        """The full What? spec as YAML: goal, overview, every question with its answers and ids."""
        p = proj(project)
        return dump(spec_of(p, rref(p, ref)))

    @tool("spec_open_questions", read_only=True)
    async def spec_open_questions(project: ProjectId, ref: ReadRef = None) -> str:
        """Questions without an answer yet, with example answers and the default assumption."""
        p = proj(project)
        return json.dumps(S.open_questions(spec_of(p, rref(p, ref))), indent=1)

    @tool("spec_answer")
    async def spec_answer(project: ProjectId, question_id: str, text: str,
                          assumption: Annotated[bool, Field(description="True when you are assuming, not quoting the user")] = False,
                          branch: WriteBranch = None) -> str:
        """Record an answer to a What? question. Mark your own guesses as assumptions."""
        p = proj(project)
        b = wbranch(p, branch)
        spec = spec_of(p, b)
        actor = current_actor.get()
        q = S.answer(spec, question_id, text, "bot" if actor.name == "Bot" else "you" if actor.name == "You" else "agent", assumption)
        save_yaml(p, b, "spec.yaml", spec, "Spec: answers")
        return f"Answered {q['id']}: {q['text']}"

    @tool("spec_add_question")
    async def spec_add_question(project: ProjectId, category: Annotated[str, Field(description="Category id or name, e.g. function")],
                                text: str, parent: Annotated[str | None, Field(description="Question id this follows up on")] = None,
                                examples: list[str] | None = None, assume: Annotated[str, Field(description="What you assume if the user skips it")] = "",
                                branch: WriteBranch = None) -> str:
        """Add a question to the What? sheet, optionally as a follow-up to another one."""
        p = proj(project)
        b = wbranch(p, branch)
        spec = spec_of(p, b)
        q = S.add_question(spec, category, text, "bot" if current_actor.get().name == "Bot" else "agent", parent, examples, assume)
        save_yaml(p, b, "spec.yaml", spec, "Spec: questions")
        return f"Added {q['id']}: {q['text']}"

    @tool("spec_set_overview")
    async def spec_set_overview(project: ProjectId, overview: str, branch: WriteBranch = None) -> str:
        """Replace the short overview paragraph at the top of the What? sheet."""
        p = proj(project)
        b = wbranch(p, branch)
        spec = spec_of(p, b)
        spec["overview"] = overview.strip()
        save_yaml(p, b, "spec.yaml", spec, "Spec: overview")
        return "Overview updated."

    # ---------- geometry.* ----------

    @tool("geometry_read_part", read_only=True)
    async def geometry_read_part(project: ProjectId, part: str, ref: ReadRef = None) -> str:
        """Source code of one part script."""
        p = proj(project)
        ref = rref(p, ref)
        e = part_entry(p, ref, part)
        src = p.read(e.get("file") or f"parts/{part}.py", ref)
        return src if src is not None else f"(missing file for {part})"

    @tool("geometry_write_part")
    async def geometry_write_part(project: ProjectId,
                                  part: Annotated[str, Field(description="Part id: lower-case letters, digits, _ (e.g. base_plate)")],
                                  code: Annotated[str, Field(description="Complete build123d script that sets `result`")],
                                  name: Annotated[str | None, Field(description="Display name")] = None,
                                  color: Annotated[str | None, Field(description="Hex colour like #B4C2D6")] = None,
                                  material: Annotated[str | None, Field(description="Steel, Aluminium, Stainless, PLA, PETG, ABS, Nylon, Brass, Titanium, Wood")] = None,
                                  mass_kg: Annotated[float | None, Field(description="Fixed mass for bought-in parts")] = None,
                                  branch: WriteBranch = None) -> str:
        """Create or replace a part script (staged, not committed). Call geometry_rebuild next."""
        p = proj(project)
        b = wbranch(p, branch)
        valid_part_id(part)
        asm = p.assembly(b)
        entry = next((e for e in asm["parts"] if e["id"] == part), None)
        if entry is None:
            entry = {"id": part, "name": name or part.replace("_", " ").capitalize(), "file": f"parts/{part}.py",
                     "color": color or "#B4C2D6", "material": material or "Steel"}
            asm["parts"].append(entry)
        for k, v in (("name", name), ("color", color), ("material", material), ("mass_kg", mass_kg)):
            if v is not None:
                entry[k] = v
        if "from build123d" not in code:
            code = PART_HEADER + code
        p.stage(b, {entry["file"]: code if code.endswith("\n") else code + "\n", "assembly.yaml": dump(asm)})
        return f"Staged {entry['file']} on {b}. Run geometry_rebuild to check it."

    @tool("geometry_patch_part")
    async def geometry_patch_part(project: ProjectId, part: str,
                                  find: Annotated[str, Field(description="Exact text to replace; must occur once")],
                                  replace: str, branch: WriteBranch = None) -> str:
        """Replace one exact snippet in a part script (staged). Good for small parameter changes."""
        p = proj(project)
        b = wbranch(p, branch)
        e = part_entry(p, b, part)
        path = e.get("file") or f"parts/{part}.py"
        src = p.read(path, b) or ""
        n = src.count(find)
        if n != 1:
            raise StoreError(f"`find` occurs {n} times in {path}; it must occur exactly once. Read the part and use a longer snippet.")
        p.stage(b, {path: src.replace(find, replace)})
        return f"Patched {path} on {b}. Run geometry_rebuild to check it."

    @tool("geometry_remove_part", destructive=True)
    async def geometry_remove_part(project: ProjectId, part: str, branch: WriteBranch = None) -> str:
        """Remove a part from the assembly and delete its script (staged)."""
        p = proj(project)
        b = wbranch(p, branch)
        asm = p.assembly(b)
        e = part_entry(p, b, part)
        asm["parts"] = [x for x in asm["parts"] if x["id"] != part]
        p.stage(b, {e.get("file") or f"parts/{part}.py": None, "assembly.yaml": dump(asm)})
        return f"Removed {part} on {b} (staged)."

    @tool("geometry_rebuild")
    async def geometry_rebuild(project: ProjectId, ref: ReadRef = None,
                               parts: Annotated[list[str] | None, Field(description="Only these part ids (default: all)")] = None) -> str:
        """Build the parts in the sandboxed geometry kernel and report mass, size and errors with line numbers."""
        p = proj(project)
        man = await geo.build(p, rref(p, ref), parts)
        engine.events.publish({"type": "build.done", "project": p.id, "ref": man["ref"], "ok": man["ok"]})
        return manifest_text(man)

    @tool("geometry_measure", read_only=True)
    async def geometry_measure(project: ProjectId,
                               kind: Annotated[Literal["mass", "cg", "bbox", "distance", "clash"], Field(description="mass/cg/bbox for the assembly; distance/clash between parts a and b")],
                               a: str | None = None, b: str | None = None, ref: ReadRef = None) -> str:
        """Measure the model: mass, centre of gravity, bounding box, distance between two parts, or clash check."""
        p = proj(project)
        ref = rref(p, ref)
        if kind in ("distance", "clash"):
            if not a or not b:
                raise StoreError("distance and clash need parts a and b")
            return json.dumps(await geo.measure(p, ref, kind, a, b))
        man = await geo.build(p, ref)
        ok = [x for x in man["parts"] if x["ok"]]
        if kind == "mass":
            return json.dumps({"total_kg": man["mass_kg"], "parts": {x["id"]: round(x["mass_kg"], 4) for x in ok}})
        if kind == "cg":
            return json.dumps({"cg_mm": man["cg"]})
        return json.dumps({"bbox_mm": man["bbox"], "parts": {x["id"]: x["bbox"] for x in ok}})

    @tool("geometry_export")
    async def geometry_export(project: ProjectId, format: Literal["step", "stl"] = "step",
                              parts: list[str] | None = None, ref: ReadRef = None) -> str:
        """Export the assembly (or some parts) as STEP or STL. Returns the file path on the engine machine."""
        p = proj(project)
        r = await geo.export(p, rref(p, ref), format, parts)
        return f"Wrote {r['path']} ({r['bytes']} bytes) from {r['commit'][:7]}"

    # ---------- view.* ----------

    @tool("view_snapshot", read_only=True)
    async def view_snapshot(project: ProjectId,
                            view: Literal["iso", "front", "back", "left", "right", "top", "bottom"] = "iso",
                            ref: ReadRef = None, highlight: Annotated[str | None, Field(description="Part id to tint blue")] = None) -> list[Any]:
        """Render a picture of the assembly from a named view so you can check the shape visually."""
        p = proj(project)
        png, man = await geo.snapshot(p, rref(p, ref), view, (800, 600), highlight)
        failed = [x["id"] for x in man["parts"] if not x["ok"]]
        note = f"{view} view of {man['ref']} ({man['commit'][:7]}), Z up." + (f" Not drawn because they failed: {', '.join(failed)}." if failed else "")
        return [note, Image(data=png, format="png")]

    # ---------- notes.* ----------

    @tool("notes_list", read_only=True)
    async def notes_list(project: ProjectId, status: Literal["open", "queued", "resolved", "all"] = "all", ref: ReadRef = None) -> str:
        """3D comments with their part, face tag, position and messages. Queued ones are waiting for the Bot."""
        p = proj(project)
        ref = rref(p, ref)
        notes = (p.read_yaml("notes.yaml", ref) or {}).get("notes", [])
        out = []
        faces_cache: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        man = None
        for n in notes:
            if status != "all" and n.get("status") != status:
                continue
            item = {k: n.get(k) for k in ("id", "part", "status", "point", "face", "msgs")}
            if n.get("face_sig"):
                if man is None:
                    man = await geo.build(p, ref)
                part = next((x for x in man["parts"] if x["id"] == n["part"] and x["ok"]), None)
                if part:
                    if part["key"] not in faces_cache:
                        meta = geo.meta(part["key"]) or {"faces": []}
                        faces_cache[part["key"]] = [(f["tag"], f) for f in meta["faces"]]
                    item["face_now"] = rematch(n["face_sig"], faces_cache[part["key"]])
            out.append(item)
        return json.dumps(out, indent=1) if out else "No comments."

    @tool("notes_resolve")
    async def notes_resolve(project: ProjectId, note_id: int, reply: Annotated[str, Field(description="Short reply explaining what you changed")],
                            branch: WriteBranch = None) -> str:
        """Reply to a 3D comment and mark it resolved."""
        p = proj(project)
        b = wbranch(p, branch)
        notes = p.read_yaml("notes.yaml", b) or {"notes": []}
        n = S.find_note(notes, note_id)
        n["msgs"].append({"who": current_actor.get().name, "text": reply})
        n["status"] = "resolved"
        save_yaml(p, b, "notes.yaml", notes, f"Resolve comment {note_id}")
        return f"Comment {note_id} resolved."

    # ---------- resources ----------

    @mcp.resource("newcad://projects", name="projects", mime_type="application/json", description="All projects")
    def res_projects() -> str:
        return json.dumps(store.list())

    def _res_project(pid: str) -> Project:
        try:
            return store.get(pid)
        except StoreError as e:
            raise ResourceNotFoundError(str(e)) from None

    @mcp.resource("newcad://projects/{project}/spec", name="spec", mime_type="text/yaml", description="The What? spec of a project at HEAD")
    def res_spec(project: str) -> str:
        return dump(_res_project(project).read_yaml("spec.yaml") or {})

    @mcp.resource("newcad://projects/{project}/assembly", name="assembly", mime_type="text/yaml", description="Assembly tree: parts with files, materials and colours")
    def res_assembly(project: str) -> str:
        p = _res_project(project)
        asm = p.assembly()
        return dump({"project": p.id, "head": p.head_ref(), **asm})

    @mcp.resource("newcad://projects/{project}/snapshot", name="snapshot", mime_type="image/png", description="Isometric picture of HEAD")
    async def res_snapshot(project: str) -> bytes:
        png, _ = await geo.snapshot(_res_project(project), None, "iso")
        return png

    return mcp
