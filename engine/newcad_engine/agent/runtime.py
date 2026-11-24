"""BuilderBot's tool-calling loop.

The runtime is an MCP client of the engine's own MCP server (connected
in-process), so BuilderBot uses exactly the tools an external agent sees.
Guard rails enforced here and in the server:
- the Bot is pinned to one project and to its own branches (never the user's
  HEAD, except interview mode which only edits the What? sheet); it can create
  more bot/* branches to try alternatives and switch between them
- tools that move HEAD or create projects are not offered
- a step budget and a token budget stop runaway loops
- generated code only runs in the sandboxed geometry worker
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from mcp import Client

from ..core import bot_actor, current_actor
from .adapters import AdapterError, Conversation, ToolCall, ToolOutput, ToolSpec

if TYPE_CHECKING:
    from ..core import Engine

log = logging.getLogger("newcad.bot")

HIDDEN_TOOLS = {"project_list", "project_create", "project_checkout"}
INTERVIEW_TOOLS = {"project_open", "spec_read", "spec_open_questions", "spec_answer", "spec_add_question", "spec_set_overview"}
INJECTED = ("project", "branch")

LocalTool = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass
class LoopResult:
    status: str  # done | failed | stopped
    text: str
    steps: int
    tokens: int
    calls: list[dict[str, Any]] = field(default_factory=list)
    problem: str = ""
    branch: str = ""  # the branch the Bot worked on last
    branches: list[str] = field(default_factory=list)  # every branch it wrote to (its first one plus any it created)


def label_for(call: ToolCall) -> str:
    a = call.args
    return {
        "spec_read": "Reading the spec",
        "spec_open_questions": "Looking at open questions",
        "spec_answer": f"Noting an answer for {a.get('question_id', '')}",
        "spec_add_question": "Adding a question",
        "spec_set_overview": "Updating the overview",
        "project_open": "Opening the project",
        "project_log": "Reading the history",
        "project_diff": "Comparing versions",
        "project_commit": "Saving a version",
        "geometry_read_part": f"Reading {a.get('part', 'a part')}",
        "geometry_write_part": f"Writing {a.get('part', 'a part')}",
        "geometry_patch_part": f"Editing {a.get('part', 'a part')}",
        "geometry_remove_part": f"Removing {a.get('part', 'a part')}",
        "geometry_rebuild": "Rebuilding the model",
        "geometry_measure": f"Measuring {a.get('kind', '')}".strip(),
        "geometry_export": "Exporting",
        "view_snapshot": f"Looking at the {a.get('view', 'iso')} view",
        "notes_list": "Reading comments",
        "notes_resolve": "Replying to a comment",
        "ask_user": "Asking you",
        "project_create_branch": f"Branching to try {a.get('name', 'a variant')}",
        "project_switch_branch": f"Switching to {a.get('to', 'another branch')}",
        "code_list_files": "Listing the project files",
        "code_read_file": f"Reading {a.get('path', 'a file')}",
        "code_write_module": f"Writing lib/{a.get('module', 'module')}.py",
        "code_patch_file": f"Editing {a.get('path', 'a file')}",
        "code_remove_module": f"Removing lib/{a.get('module', 'module')}.py",
        "assembly_read": "Reading the assembly",
        "assembly_set_mate": f"Setting a {a.get('type', '')} joint".replace("  ", " "),
        "assembly_remove_mate": f"Removing joint {a.get('id', '')}".strip(),
        "assembly_set_part": f"Updating {a.get('part', 'a part')}",
        "sim_create_study": "Setting up a simulation",
        "sim_add_boundary": "Adding a load or support",
        "sim_run": "Running the simulation",
        "sim_results": "Reading simulation results",
    }.get(call.name, call.name)


def to_spec(tool: Any) -> ToolSpec:
    schema = json.loads(json.dumps(tool.input_schema or {"type": "object", "properties": {}}))
    props = schema.get("properties", {})
    for k in INJECTED:
        props.pop(k, None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r not in INJECTED]
    schema.pop("title", None)
    return ToolSpec(tool.name, tool.description or "", schema)


async def run_loop(engine: "Engine", *, project: str, branch: str, task_id: str, conv_factory: Callable[[list[ToolSpec]], Conversation],
                   prompt: str, allowed: set[str] | None = None, local_tools: dict[str, tuple[ToolSpec, LocalTool]] | None = None,
                   max_steps: int = 40, max_tokens: int = 600_000,
                   on_step: Callable[[str, int], None] | None = None, on_text: Callable[[str], None] | None = None,
                   should_stop: Callable[[], bool] | None = None, stop_event: asyncio.Event | None = None,
                   trace: list[dict[str, Any]] | None = None, on_trace: Callable[[], None] | None = None) -> LoopResult:
    """`trace` collects what the user can watch live: the model's reasoning, its text between tool calls and
    each tool call with its result. `stop_event` stops the task at once, also in the middle of a model call."""
    local_tools = local_tools or {}
    actor = bot_actor(project, branch, task_id)
    token = current_actor.set(actor)
    calls_log: list[dict[str, Any]] = []
    try:
        tr = Trace(trace if trace is not None else [], on_trace)
        res = await _loop(engine, actor, project, conv_factory, prompt, allowed, local_tools, max_steps, max_tokens,
                          on_step, on_text, should_stop, calls_log, stop_event, tr)
        res.branch, res.branches = actor.branch or branch, list(actor.owned)
        return res
    finally:
        current_actor.reset(token)


async def _loop(engine: "Engine", actor: Any, project: str, conv_factory: Callable[[list[ToolSpec]], Conversation], prompt: str,
                allowed: set[str] | None, local_tools: dict[str, tuple[ToolSpec, LocalTool]], max_steps: int, max_tokens: int,
                on_step: Callable[[str, int], None] | None, on_text: Callable[[str], None] | None,
                should_stop: Callable[[], bool] | None, calls_log: list[dict[str, Any]],
                stop_event: asyncio.Event | None = None, tr: "Trace | None" = None) -> LoopResult:
    tr = tr or Trace([], None)
    steps = tokens = 0
    stopped = lambda: LoopResult("stopped", "", steps, tokens, calls_log, "Stopped by you")  # noqa: E731
    async with Client(engine.mcp) as client:
        listed = (await client.list_tools()).tools
        mcp_tools = {t.name: t for t in listed if t.name not in HIDDEN_TOOLS and (allowed is None or t.name in allowed)}
        injected_branch = {t.name: "branch" in (t.input_schema or {}).get("properties", {}) for t in mcp_tools.values()}
        specs = [to_spec(t) for t in mcp_tools.values()] + [s for s, _ in local_tools.values()]
        try:
            conv = conv_factory(specs)
            turn = await _until_stopped(conv.send_user(prompt), stop_event)
        except _Stopped:
            return stopped()
        except AdapterError as e:
            return LoopResult("failed", "", 0, 0, calls_log, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("model call failed")
            return LoopResult("failed", "", 0, 0, calls_log, f"Model call failed: {type(e).__name__}: {e}")
        while True:
            steps += 1
            tokens += turn.input_tokens + turn.output_tokens
            if turn.thinking.strip():
                tr.add({"kind": "thinking", "text": turn.thinking.strip()[:TRACE_TEXT]})
            if turn.text.strip() and turn.calls:
                tr.add({"kind": "text", "text": turn.text.strip()[:TRACE_TEXT]})
                if on_text:
                    on_text(turn.text.strip())
            if turn.stop == "refusal":
                return LoopResult("failed", turn.text, steps, tokens, calls_log, "The model declined this request" + (f" ({turn.detail})" if turn.detail else ""))
            if turn.stop == "max_tokens":
                return LoopResult("failed", turn.text, steps, tokens, calls_log, "The model's reply was cut off (output limit)")
            if not turn.calls:
                return LoopResult("done", turn.text.strip(), steps, tokens, calls_log)
            if (should_stop and should_stop()) or (stop_event and stop_event.is_set()):
                return LoopResult("stopped", turn.text, steps, tokens, calls_log, "Stopped by you")
            if steps >= max_steps:
                return LoopResult("stopped", turn.text, steps, tokens, calls_log, f"Stopped after {max_steps} steps (step budget)")
            if tokens >= max_tokens:
                return LoopResult("stopped", turn.text, steps, tokens, calls_log, f"Stopped after {tokens:,} tokens (token budget)")
            outputs: list[ToolOutput] = []
            for call in turn.calls:
                if stop_event and stop_event.is_set():
                    return stopped()
                label = label_for(call)
                if on_step:
                    on_step(label, steps)
                ev = tr.add({"kind": "tool", "tool": call.name, "label": label, "args": _short(call.args), "status": "running"})
                t0 = time.perf_counter()
                out = await _execute(client, call, project, actor.branch, mcp_tools, injected_branch, local_tools)
                ms = round((time.perf_counter() - t0) * 1000)
                calls_log.append({"tool": call.name, "args": _short(call.args), "ok": not out.is_error, "ms": ms, "result": out.text[:300]})
                tr.update(ev, status="error" if out.is_error else "ok", ms=ms, result=out.text[:TRACE_RESULT],
                          images=len(out.images) or None)
                outputs.append(out)
            try:
                turn = await _until_stopped(conv.send_tool_results(outputs), stop_event)
            except _Stopped:
                return stopped()
            except AdapterError as e:
                return LoopResult("failed", "", steps, tokens, calls_log, str(e))
            except Exception as e:  # noqa: BLE001 - a broken provider response must not crash the engine
                log.exception("model call failed")
                return LoopResult("failed", "", steps, tokens, calls_log, f"Model call failed: {type(e).__name__}: {e}")


async def _execute(client: Client, call: ToolCall, project: str, branch: str, mcp_tools: dict[str, Any],
                   injected_branch: dict[str, bool], local_tools: dict[str, tuple[ToolSpec, LocalTool]]) -> ToolOutput:
    if "__invalid_json__" in call.args:
        return ToolOutput(call.id, "The tool arguments were not valid JSON. Send them again as a JSON object.", is_error=True)
    if call.name in local_tools:
        try:
            return ToolOutput(call.id, await local_tools[call.name][1](call.args))
        except Exception as e:  # noqa: BLE001
            return ToolOutput(call.id, f"{type(e).__name__}: {e}", is_error=True)
    if call.name not in mcp_tools:
        return ToolOutput(call.id, f"Unknown tool {call.name}.", is_error=True)
    args = {k: v for k, v in call.args.items() if k not in INJECTED}
    args["project"] = project
    if injected_branch.get(call.name):
        args["branch"] = branch
    try:
        res = await client.call_tool(call.name, args)
    except Exception as e:  # noqa: BLE001 - surface protocol errors to the model
        return ToolOutput(call.id, f"Tool call failed: {e}", is_error=True)
    texts, images = [], []
    for c in res.content:
        if c.type == "text":
            texts.append(c.text)
        elif c.type == "image":
            images.append(base64.b64decode(c.data))
    return ToolOutput(call.id, "\n".join(texts), images, bool(res.is_error))


def _short(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if not isinstance(v, str) or len(v) < 120 else v[:117] + "...") for k, v in args.items()}


TRACE_TEXT = 4000
TRACE_RESULT = 1200


class Trace:
    def __init__(self, events: list[dict[str, Any]], on_change: Callable[[], None] | None):
        self.events, self.on_change = events, on_change

    def add(self, ev: dict[str, Any]) -> dict[str, Any]:
        ev = {"t": time.time(), **ev}
        self.events.append(ev)
        self._changed()
        return ev

    def update(self, ev: dict[str, Any], **kw: Any) -> None:
        ev.update({k: v for k, v in kw.items() if v is not None})
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()


class _Stopped(Exception):
    pass


async def _until_stopped(coro: Any, stop_event: asyncio.Event | None) -> Any:
    """Await a model call, but give up on it as soon as the user presses Stop."""
    if stop_event is None:
        return await coro
    if stop_event.is_set():
        coro.close()
        raise _Stopped
    call = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(stop_event.wait())
    try:
        done, _ = await asyncio.wait({call, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
    if call in done:
        return call.result()
    call.cancel()
    raise _Stopped
