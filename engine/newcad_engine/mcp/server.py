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
from ..project.store import Project, StoreError, slugify, valid_part_id
from ..project.templates import PART_HEADER, dump

INSTRUCTIONS = """NewCAD is a CAD tool where designs are build123d Python scripts stored in a git repository per project.
- Units are millimetres, Z is up. Each part is one file parts/<id>.py that sets `result` to a build123d shape, placed in assembly coordinates.
- The What? spec (spec.yaml) holds the requirements as questions and answers. Read it before designing.
- Edits are staged on a branch; project_commit turns them into a version. Branches are concepts, commits are versions.
- After writing code, call geometry_rebuild and fix any error it reports before committing.
- view_snapshot returns a picture of the current state so you can check the result visually.
- Simulation: sim_create_study, then sim_list_faces to find face tags, sim_add_boundary for supports and loads, sim_run to solve (Gmsh + CalculiX). Units mm, N, MPa."""

ReadRef = Annotated[str | None, Field(description="Branch name or commit id to read. Default: the user's current version (HEAD).")]
WriteBranch = Annotated[str | None, Field(description="Branch to change. Default: the branch the user has checked out.")]
ProjectId = Annotated[str, Field(description="Project id from project_list.")]
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3, description="[x, y, z] in mm (assembly coordinates, Z up)")]
StudyId = Annotated[str, Field(description="Study id from sim_list_studies")]


def build_mcp(engine: Any) -> MCPServer:
    mcp = MCPServer("newcad", title="NewCAD", instructions=INSTRUCTIONS, version="0.3.0")
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
            if branch in (None, "HEAD", a.branch):
                return a.branch  # type: ignore[return-value]
            if branch in a.owned:
                return branch
            raise StoreError(f"You can only change your own branches in this task: {', '.join(a.owned)}")
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
                ef = r.get("errorFile")
                where = (f" ({ef} line {r['line']})" if ef and ef != r["file"] else f" (line {r['line']})") if r.get("line") else ""
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
        """Create a branch (a concept) from a version. BuilderBot: the new branch is named bot/<name>, starts from your
        current branch unless from_ref is given, and becomes the branch you work on (go back with project_switch_branch)."""
        a = current_actor.get()
        p = proj(project)
        if a.guarded:
            base = from_ref or a.branch
            if a.branch and p.staged(a.branch):
                p.commit(a.branch, "Bot: work in progress", a.author)
            nm = name if name.startswith("bot/") else f"bot/{slugify(name, 'variant')[:30]}"
            b = p.create_branch(nm, base, unique=True)
            a.owned.append(b)
            a.branch = b
            return f"Created branch {b} from {base} at {str(p.resolve(b).id)[:7]}. You now work on {b}. Your branches: {', '.join(a.owned)}."
        b = p.create_branch(name, from_ref)
        return f"Created branch {b} at {str(p.resolve(b).id)[:7]}"

    @tool("project_switch_branch")
    async def project_switch_branch(project: ProjectId, to: Annotated[str, Field(description="One of the branches this task created or started on")]) -> str:
        """BuilderBot only: switch which of your own branches your edits go to. Staged edits on the current branch are committed first."""
        a = current_actor.get()
        p = proj(project)
        if not a.guarded:
            raise StoreError("Only for Bot tasks. To change the user's view use project_checkout.")
        if to not in a.owned:
            raise StoreError(f"You can only switch between your branches: {', '.join(a.owned)}")
        if a.branch and p.staged(a.branch):
            p.commit(a.branch, "Bot: work in progress", a.author)
        a.branch = to
        return f"You now work on {to}."

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

    # ---------- code.* (every file of the project) ----------

    def code_path(path: str) -> str:
        path = path.strip().lstrip("/")
        if path.startswith(("parts/", "lib/")) and path.endswith(".py") and path.count("/") == 1 and valid_module(path.split("/")[1][:-3]):
            return path
        raise StoreError("Editable code files are parts/<id>.py and lib/<name>.py (lower-case letters, digits, _)")

    def valid_module(name: str) -> bool:
        try:
            valid_part_id(name)
            return True
        except StoreError:
            return False

    @tool("code_list_files", read_only=True)
    async def code_list_files(project: ProjectId, ref: ReadRef = None) -> str:
        """List every file of the project with its size: part scripts, shared modules (lib/), assembly.yaml, spec.yaml, notes and studies."""
        p = proj(project)
        files = p.files(rref(p, ref))
        lines = [f"{path}  ({src.count(chr(10)) + 1} lines)" for path, src in sorted(files.items())]
        return "\n".join(lines) + "\n\nPart scripts can import shared modules: `from params import *` imports lib/params.py."

    @tool("code_read_file", read_only=True)
    async def code_read_file(project: ProjectId, path: Annotated[str, Field(description="File path, e.g. parts/plate.py, lib/params.py or assembly.yaml")],
                             ref: ReadRef = None) -> str:
        """Read any file of the project."""
        p = proj(project)
        src = p.read(path.strip().lstrip("/"), rref(p, ref))
        if src is None:
            raise StoreError(f"No file {path}. Use code_list_files.")
        return src

    @tool("code_write_module")
    async def code_write_module(project: ProjectId,
                                module: Annotated[str, Field(description="Module name: lower-case letters, digits, _ (e.g. params)")],
                                code: Annotated[str, Field(description="Complete Python source of lib/<module>.py")],
                                branch: WriteBranch = None) -> str:
        """Create or replace a shared module lib/<module>.py (staged). Part scripts import it with `from <module> import *`.
        Use it for dimensions or helper functions that several parts share, so one edit changes all of them."""
        p = proj(project)
        b = wbranch(p, branch)
        valid_part_id(module)
        p.stage(b, {f"lib/{module}.py": code if code.endswith("\n") else code + "\n"})
        return f"Staged lib/{module}.py on {b}. Run geometry_rebuild to rebuild the parts that use it."

    @tool("code_patch_file")
    async def code_patch_file(project: ProjectId,
                              path: Annotated[str, Field(description="parts/<id>.py or lib/<name>.py")],
                              find: Annotated[str, Field(description="Exact text to replace; must occur once")],
                              replace: str, branch: WriteBranch = None) -> str:
        """Replace one exact snippet in a part script or shared module (staged)."""
        p = proj(project)
        b = wbranch(p, branch)
        path = code_path(path)
        src = p.read(path, b)
        if src is None:
            raise StoreError(f"No file {path} on {b}")
        n = src.count(find)
        if n != 1:
            raise StoreError(f"`find` occurs {n} times in {path}; it must occur exactly once. Read the file and use a longer snippet.")
        p.stage(b, {path: src.replace(find, replace)})
        return f"Patched {path} on {b}. Run geometry_rebuild to check it."

    @tool("code_remove_module", destructive=True)
    async def code_remove_module(project: ProjectId, module: str, branch: WriteBranch = None) -> str:
        """Delete the shared module lib/<module>.py (staged)."""
        p = proj(project)
        b = wbranch(p, branch)
        if p.read(f"lib/{module}.py", b) is None:
            raise StoreError(f"No module lib/{module}.py")
        p.stage(b, {f"lib/{module}.py": None})
        return f"Removed lib/{module}.py on {b} (staged)."

    # ---------- assembly.* (parts and joints) ----------


    def asm_text(asm: dict[str, Any]) -> str:
        out = {"parts": [{k: v for k, v in e.items() if k in ("id", "name", "material", "color", "mass_kg", "file")} for e in asm["parts"]],
               "mates": asm.get("mates") or []}
        return dump(out)

    @tool("assembly_read", read_only=True)
    async def assembly_read(project: ProjectId, ref: ReadRef = None) -> str:
        """The assembly: every part (id, name, material, colour, file) and every joint (mate) between parts."""
        p = proj(project)
        return asm_text(p.assembly(rref(p, ref)))

    @tool("assembly_set_mate")
    async def assembly_set_mate(project: ProjectId,
                                type: Annotated[Literal["fixed", "revolute", "slider", "cylindrical", "planar", "ball"],
                                                Field(description="fixed: no motion (bolted, welded). revolute: rotates about axis. slider: moves along axis. cylindrical: rotates and slides along axis. planar: slides in the plane normal to axis. ball: rotates about origin.")],
                                a: Annotated[str, Field(description="First part id")],
                                b: Annotated[str, Field(description="Second part id")],
                                origin: Vec3,
                                axis: Annotated[list[float] | None, Field(description="Joint axis direction [x, y, z]; default [0, 0, 1]")] = None,
                                limits: Annotated[list[float] | None, Field(description="[min, max] travel: degrees for revolute, mm for slider")] = None,
                                name: Annotated[str | None, Field(description="Short label, e.g. 'Hinge pin'")] = None,
                                id: Annotated[str | None, Field(description="Id of an existing mate to change; omit to add a new one")] = None,
                                branch: WriteBranch = None) -> str:
        """Add or change a joint (mate) between two parts (staged). Parts stay where their scripts put them; the mate records how they connect and move."""
        p = proj(project)
        br = wbranch(p, branch)
        asm = p.assembly(br)
        ids = {e["id"] for e in asm["parts"]}
        for x in (a, b):
            if x not in ids:
                raise StoreError(f"No part {x!r}. Parts: {', '.join(sorted(ids)) or 'none yet'}")
        if a == b:
            raise StoreError("A mate connects two different parts")
        if limits is not None and (len(limits) != 2 or limits[0] > limits[1]):
            raise StoreError("limits must be [min, max]")
        ax = axis or [0.0, 0.0, 1.0]
        if len(ax) != 3 or not any(abs(v) > 1e-9 for v in ax):
            raise StoreError("axis must be a non-zero [x, y, z]")
        mates = asm.setdefault("mates", []) or []
        asm["mates"] = mates
        m = next((x for x in mates if x.get("id") == id), None) if id else None
        if id and m is None:
            raise StoreError(f"No mate {id!r}. Mates: {', '.join(x['id'] for x in mates) or 'none'}")
        if m is None:
            n = 1 + max([int(str(x.get("id", "mate-0")).rsplit("-", 1)[-1]) for x in mates if str(x.get("id", "")).rsplit("-", 1)[-1].isdigit()] or [0])
            m = {"id": f"mate-{n}"}
            mates.append(m)
        m.update({"type": type, "a": a, "b": b, "origin": [float(v) for v in origin], "axis": [float(v) for v in ax],
                  "name": name or m.get("name") or f"{a} – {b}"})
        if limits is not None:
            m["limits"] = [float(v) for v in limits]
        elif type == "fixed":
            m.pop("limits", None)
        p.stage(br, {"assembly.yaml": dump(asm)})
        return f"{'Changed' if id else 'Added'} {m['id']}: {type} between {a} and {b} at {m['origin']} (staged on {br}). Commit with project_commit."

    @tool("assembly_remove_mate", destructive=True)
    async def assembly_remove_mate(project: ProjectId, id: Annotated[str, Field(description="Mate id, e.g. mate-1")], branch: WriteBranch = None) -> str:
        """Remove a joint (mate) (staged)."""
        p = proj(project)
        br = wbranch(p, branch)
        asm = p.assembly(br)
        mates = asm.get("mates") or []
        if not any(x.get("id") == id for x in mates):
            raise StoreError(f"No mate {id!r}")
        asm["mates"] = [x for x in mates if x.get("id") != id]
        p.stage(br, {"assembly.yaml": dump(asm)})
        return f"Removed {id} (staged on {br})."

    @tool("assembly_set_part")
    async def assembly_set_part(project: ProjectId, part: str,
                                name: Annotated[str | None, Field(description="Display name")] = None,
                                color: Annotated[str | None, Field(description="Hex colour like #B4C2D6")] = None,
                                material: Annotated[str | None, Field(description="Steel, Aluminium, Stainless, PLA, PETG, ABS, Nylon, Brass, Titanium, Wood")] = None,
                                mass_kg: Annotated[float | None, Field(description="Fixed mass for bought-in parts")] = None,
                                branch: WriteBranch = None) -> str:
        """Change a part's name, colour, material or fixed mass without touching its code (staged)."""
        p = proj(project)
        br = wbranch(p, branch)
        asm = p.assembly(br)
        e = next((x for x in asm["parts"] if x["id"] == part), None)
        if e is None:
            raise StoreError(f"No part {part!r}. Parts: {', '.join(x['id'] for x in asm['parts']) or 'none yet'}")
        for k, v in (("name", name), ("color", color), ("material", material), ("mass_kg", mass_kg)):
            if v is not None:
                e[k] = v
        p.stage(br, {"assembly.yaml": dump(asm)})
        return f"Updated {part} (staged on {br})."

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

    # ---------- sim.* ----------

    sim = engine.sim
    from ..sim import materials as MAT
    from ..sim.service import summary_text

    AXES = {"+x": (0, 1), "-x": (0, -1), "+y": (1, 1), "-y": (1, -1), "+z": (2, 1), "-z": (2, -1)}

    @tool("sim_list_studies", read_only=True)
    async def sim_list_studies(project: ProjectId, ref: ReadRef = None) -> str:
        """Simulation studies of the project (static stress, modal, thermal) with their setup and whether a result exists."""
        p = proj(project)
        ref = rref(p, ref)
        out = []
        for st in sim.list(p, ref):
            state = await sim.state(p, st.id, ref)
            out.append({"id": st.id, "name": st.name, "type": st.type, "boundaries": [b.model_dump(exclude_none=True, exclude={"faces": {"__all__": {"sig"}}}) for b in st.boundaries],
                        "materials": st.materials, "mesh": st.mesh.model_dump(), "status": state["status"],
                        **({"problem": state["problem"]} if state.get("problem") else {})})
        return json.dumps(out, indent=1) if out else "No studies yet. Create one with sim_create_study."

    @tool("sim_list_faces", read_only=True)
    async def sim_list_faces(project: ProjectId, part: str, ref: ReadRef = None,
                             facing: Annotated[Literal["+x", "-x", "+y", "-y", "+z", "-z"] | None,
                                               Field(description="Only planar faces whose outward normal points this way")] = None) -> str:
        """Faces of a part with their stable tags, surface type, area (mm²), centre and normal. Use the tags to place boundary conditions."""
        p = proj(project)
        ref = rref(p, ref)
        man = await geo.build(p, ref, [part])
        x = next((q for q in man["parts"] if q["id"] == part), None)
        if x is None:
            raise StoreError(f"No part {part!r}")
        if not x["ok"]:
            raise StoreError(f"{part} doesn't build: {x['error']}")
        faces = (geo.meta(x["key"]) or {"faces": []})["faces"]
        if facing:
            ax, sgn = AXES[facing]
            faces = [f for f in faces if f.get("normal") and f["normal"][ax] * sgn > 0.98]
        rows = [{"tag": f["tag"], "type": f["type"], "area": round(f["area"], 2), "center": [round(c, 2) for c in f["center"]],
                 **({"normal": [round(c, 3) for c in f["normal"]]} if f.get("normal") else {})} for f in faces]
        return json.dumps(rows) if rows else "No matching faces."

    @tool("sim_create_study")
    async def sim_create_study(project: ProjectId, name: Annotated[str, Field(description="e.g. 'Bracket under shelf load'")],
                               type: Literal["static", "modal", "thermal"] = "static", branch: WriteBranch = None) -> str:
        """Create an empty study. Then add boundary conditions with sim_add_boundary and run it with sim_run."""
        p = proj(project)
        b = wbranch(p, branch)
        st = sim.create(p, name, type, b, current_actor.get().author)
        return f"Created study {st.id} ({type}) on {b}."

    @tool("sim_add_boundary")
    async def sim_add_boundary(project: ProjectId, study: StudyId,
                               type: Annotated[Literal["fixed", "force", "pressure", "gravity", "temperature", "heat_flux", "convection"],
                                               Field(description="static: fixed, force, pressure, gravity. modal: fixed. thermal: temperature, heat_flux, convection")],
                               part: Annotated[str | None, Field(description="Part the faces belong to (not needed for gravity)")] = None,
                               faces: Annotated[list[str] | None, Field(description="Face tags from sim_list_faces")] = None,
                               vector: Annotated[list[float] | None, Field(description="force: total N [x,y,z] shared over the faces; gravity: m/s², e.g. [0,0,-9.81]")] = None,
                               value: Annotated[float | None, Field(description="pressure MPa, temperature °C, heat_flux W total, convection W/(m²·K)")] = None,
                               ambient: Annotated[float | None, Field(description="convection: ambient °C")] = None,
                               label: Annotated[str, Field(description="Short name, e.g. 'Wall bolts'")] = "",
                               branch: WriteBranch = None) -> str:
        """Add a boundary condition (support or load) on faces of a part."""
        p = proj(project)
        b = wbranch(p, branch)
        st = sim.read(p, study, b)
        refs = []
        if faces:
            if not part:
                raise StoreError("Give the part the faces belong to")
            man = await geo.build(p, b, [part])
            x = next((q for q in man["parts"] if q["id"] == part), None)
            if x is None or not x["ok"]:
                raise StoreError(f"Part {part} is missing or doesn't build")
            meta = {f["tag"]: f for f in (geo.meta(x["key"]) or {"faces": []})["faces"]}
            for t in faces:
                if t not in meta:
                    raise StoreError(f"No face {t} on {part}. Use sim_list_faces to get current tags.")
                refs.append({"part": part, "tag": t, "sig": {k: v for k, v in meta[t].items() if k != "tag"}})
        d = st.to_yaml_dict()
        bid = st.next_boundary_id(type)
        d.setdefault("boundaries", []).append({"id": bid, "type": type, "label": label, "faces": refs, "vector": vector,
                                               "value": value, "ambient": ambient})
        sim.replace(p, study, {**d, "boundaries": [{k: v for k, v in x.items() if v is not None} for x in d["boundaries"]]},
                    b, current_actor.get().author)
        return f"Added {type} {bid} to {study}."

    @tool("sim_remove_boundary", destructive=True)
    async def sim_remove_boundary(project: ProjectId, study: StudyId, boundary: Annotated[str, Field(description="Boundary id, e.g. force-1")],
                                  branch: WriteBranch = None) -> str:
        """Remove one boundary condition from a study."""
        p = proj(project)
        b = wbranch(p, branch)
        d = sim.read(p, study, b).to_yaml_dict()
        before = len(d.get("boundaries", []))
        d["boundaries"] = [x for x in d.get("boundaries", []) if x.get("id") != boundary]
        if len(d["boundaries"]) == before:
            raise StoreError(f"No boundary {boundary} in {study}")
        sim.replace(p, study, d, b, current_actor.get().author)
        return f"Removed {boundary}."

    @tool("sim_configure")
    async def sim_configure(project: ProjectId, study: StudyId,
                            materials: Annotated[dict[str, str] | None, Field(description="Part id → material, overrides the part's material in this study")] = None,
                            mesh_size: Annotated[float | None, Field(description="Element size in mm (smaller = more accurate and slower). 0 = automatic")] = None,
                            modes: Annotated[int | None, Field(description="modal: number of modes")] = None,
                            safety_target: Annotated[float | None, Field(description="static: required safety factor against yield")] = None,
                            parts: Annotated[list[str] | None, Field(description="Only these parts (default all, bonded where they touch)")] = None,
                            branch: WriteBranch = None) -> str:
        """Change study settings: materials, mesh size, number of modes, safety target, parts included."""
        p = proj(project)
        b = wbranch(p, branch)
        d = sim.read(p, study, b).to_yaml_dict()
        if materials:
            bad = [m for m in materials.values() if m.lower() not in {n.lower() for n in MAT.names()} | {"aluminum", "stainless steel"}]
            if bad:
                raise StoreError(f"Unknown material {bad[0]}. Known: {', '.join(MAT.names())}")
            d["materials"] = {**d.get("materials", {}), **materials}
        if mesh_size is not None:
            d.setdefault("mesh", {})
            if mesh_size > 0:
                d["mesh"]["size"] = mesh_size
            else:
                d["mesh"].pop("size", None)
        if modes is not None:
            d["modes"] = modes
        if safety_target is not None:
            d["safety_target"] = safety_target
        if parts is not None:
            d["parts"] = parts or None
        sim.replace(p, study, d, b, current_actor.get().author)
        return f"Updated {study}."

    @tool("sim_run")
    async def sim_run(project: ProjectId, study: StudyId, ref: ReadRef = None,
                      wait_s: Annotated[float, Field(description="Seconds to wait for the result (0 = return at once)")] = 600) -> str:
        """Mesh and solve a study on a compute target. Waits for the result and returns the key numbers and where the peak is."""
        import asyncio
        p = proj(project)
        ref = rref(p, ref)
        job = await sim.run(p, study, ref)
        loop = asyncio.get_running_loop()
        end = loop.time() + max(0.0, wait_s)
        while job.status in ("queued", "running") and loop.time() < end:
            await asyncio.sleep(0.25)
        if job.status == "done":
            return ("(cached result) " if job.cached else "") + summary_text(job.summary or {}, job.name) + f" [job {job.id} on {job.target or 'cache'}]"
        if job.status == "failed":
            raise StoreError(f"The study failed: {job.error}")
        if job.status == "cancelled":
            return f"Job {job.id} was cancelled."
        return f"Job {job.id} is {job.status} ({job.stage}, {job.progress:.0%}). Call sim_results later."

    @tool("sim_results", read_only=True)
    async def sim_results(project: ProjectId, study: StudyId, ref: ReadRef = None) -> str:
        """Result of a study at a version: peak stress and where, safety factor, displacement, frequencies or temperatures."""
        p = proj(project)
        ref = rref(p, ref)
        st = await sim.state(p, study, ref)
        if st["status"] == "done":
            return summary_text(st["summary"], sim.read(p, study, ref).name)
        if st["status"] == "problem":
            return f"The study can't run yet: {st['problem']}"
        if st.get("job"):
            j = st["job"]
            return f"Status {st['status']}: {j['stage']}" + (f" Error: {j['error']}" if j.get("error") else "")
        return "Not run on this version yet. Use sim_run."

    @tool("sim_targets", read_only=True)
    async def sim_targets() -> str:
        """Compute targets (this computer, remote compute nodes) with their cores, GPUs and installed solvers."""
        out = []
        for t in await engine.targets.describe():
            d = t.get("devices") or {}
            out.append({"id": t["id"], "name": t["name"], "kind": t["kind"], "online": t.get("online"),
                        "cores": (d.get("cpu") or {}).get("performance_cores"), "gpus": [g["name"] for g in d.get("gpus", [])],
                        "solvers": d.get("solvers")})
        return json.dumps(out, indent=1)

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
