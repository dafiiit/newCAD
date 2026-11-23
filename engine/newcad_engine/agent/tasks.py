"""BuilderBot tasks: chat changes, comments, three concepts, drafts and the interview."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

from ..project import spec as S
from ..project.store import BOT, StoreError, slugify
from . import adapters
from .adapters import ToolSpec
from .prompts import CONCEPT_DIRECTIONS, system_prompt
from .runtime import INTERVIEW_TOOLS, LoopResult, run_loop

if TYPE_CHECKING:
    from ..core import Engine

log = logging.getLogger("newcad.bot")


@dataclass
class BotTask:
    id: str
    project: str
    mode: str
    goal: str
    branch: str
    base: str
    status: str = "running"  # running | done | failed | stopped
    label: str = "Starting"
    step: int = 0
    max_steps: int = 40
    started: float = field(default_factory=time.time)
    finished: float | None = None
    reply: str = ""
    problem: str = ""
    commits: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    group: str | None = None
    thread: str | None = None  # the conversation this task continues (the first task's id)
    notes: list[int] = field(default_factory=list)  # 3D comments this task works on
    concept: str | None = None
    mass_kg: float | None = None
    builds: bool | None = None
    branches: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)  # reasoning, text and tool calls, live
    stop_requested: bool = False
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def to_json(self) -> dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("stop_requested", "stop_event")}
        d["trace"] = self.trace[-TRACE_KEEP:]
        return json.loads(json.dumps(d, default=str))

    def trace_brief(self) -> list[dict[str, Any]]:
        """A shorter copy of the trace kept with the Bot's reply in the chat log."""
        out = []
        for ev in self.trace[-TRACE_KEEP:]:
            ev = dict(ev)
            for k, n in (("text", 1500), ("result", 400)):
                if isinstance(ev.get(k), str) and len(ev[k]) > n:
                    ev[k] = ev[k][:n] + "…"
            out.append(ev)
        return out


TRACE_KEEP = 150


class BotManager:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.tasks: dict[str, BotTask] = {}
        self._running: dict[str, asyncio.Task[Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}
        self._interview_lock: dict[str, asyncio.Lock] = {}
        self.script: Any = None  # tests can inject a scripted conversation

    # ---------- config ----------

    def model_settings(self, pid: str | None = None) -> dict[str, Any]:
        s = dict(self.engine.settings.data)
        if pid:
            try:
                override = (self.engine.store.get(pid).meta().get("bot") or {})
                s.update({k: v for k, v in override.items() if v not in (None, "")})
            except StoreError:
                pass
        return s

    def status(self, pid: str | None = None) -> dict[str, Any]:
        s = self.model_settings(pid)
        r = adapters.resolve(s, self.engine.settings.session_keys)
        r["providers"] = [{"id": k, "label": v["label"], "defaultModel": v["default_model"], "keyEnv": v["key_env"]}
                          for k, v in adapters.PROVIDERS.items() if k != "scripted" or adapters.scripted_allowed()]
        r["effort"] = s.get("effort")
        r["max_steps"] = s.get("max_steps")
        return r

    def _conv_factory(self, pid: str, system: str):
        settings = self.model_settings(pid)
        extra = {"script": self.script} if self.script else None

        def make(tools: list[ToolSpec]):
            return adapters.make_conversation(settings, self.engine.settings.session_keys, system, tools, extra)
        return make

    def _check_ready(self, pid: str) -> None:
        r = adapters.resolve(self.model_settings(pid), self.engine.settings.session_keys)
        if not r["ready"]:
            raise StoreError(f"BuilderBot isn't set up: {r['problem']}")

    # ---------- events and chat log ----------

    def _emit(self, t: BotTask) -> None:
        self.engine.events.publish({"type": "bot.task", "project": t.project, "task": t.to_json()})

    def _chat_file(self, pid: str):
        d = self.engine.cfg.home / "chats"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{pid}.json"

    def chat(self, pid: str) -> list[dict[str, Any]]:
        f = self._chat_file(pid)
        try:
            return json.loads(f.read_text()) if f.exists() else []
        except json.JSONDecodeError:
            return []

    def say(self, pid: str, who: str, text: str, **extra: Any) -> dict[str, Any]:
        msg = {"who": who, "text": text, "t": time.time(), **extra}
        log_ = self.chat(pid)[-199:] + [msg]
        self._chat_file(pid).write_text(json.dumps(log_))
        self.engine.events.publish({"type": "bot.message", "project": pid, "message": msg})
        return msg

    def _recent(self, pid: str, n: int = 8, thread: str | None = None) -> str:
        msgs = [m for m in self.chat(pid) if m.get("who") in ("you", "bot")
                and (not thread or thread in (m.get("thread"), m.get("task")))][-n:]
        return "\n".join(f"{'User' if m['who'] == 'you' else 'Bot'}: {m['text']}" for m in msgs)

    # ---------- running a task ----------

    def _new_task(self, pid: str, mode: str, goal: str, branch: str, base: str, **kw: Any) -> BotTask:
        t = BotTask(id=secrets.token_hex(4), project=pid, mode=mode, goal=goal, branch=branch, base=base,
                    max_steps=int(self.model_settings(pid).get("max_steps", 40)), **kw)
        self.tasks[t.id] = t
        self._emit(t)
        return t

    def _launch(self, t: BotTask, prompt: str) -> None:
        async def run() -> None:
            try:
                await self._run(t, prompt)
            except Exception as e:  # noqa: BLE001
                log.exception("bot task failed")
                t.status, t.problem = "failed", f"{type(e).__name__}: {e}"
            finally:
                t.finished = time.time()
                self._emit(t)
                self._running.pop(t.id, None)
                await self._after(t)
        self._running[t.id] = asyncio.create_task(run())

    async def _run(self, t: BotTask, prompt: str) -> LoopResult:
        p = self.engine.store.get(t.project)
        system = system_prompt(t.mode, p.meta().get("name", p.id), t.branch, t.base)
        settings = self.model_settings(t.project)

        def on_step(label: str, step: int) -> None:
            t.label, t.step = label, step
            self._emit(t)

        res = await run_loop(self.engine, project=t.project, branch=t.branch, task_id=t.id,
                             conv_factory=self._conv_factory(t.project, system), prompt=prompt,
                             max_steps=t.max_steps, max_tokens=int(settings.get("max_tokens", 600_000)),
                             on_step=on_step, should_stop=lambda: t.stop_requested, stop_event=t.stop_event,
                             trace=t.trace, on_trace=lambda: self._emit(t))
        t.calls, t.tokens, t.reply, t.problem = res.calls, res.tokens, res.text, res.problem
        t.status = res.status
        first = t.branch
        branches = res.branches or [first]
        # anything the Bot staged but didn't commit is saved, so no work is lost
        for b in branches:
            if p.is_branch(b) and p.staged(b):
                p.commit(b, f"Bot: {t.goal[:60]}", BOT)
        base = p.resolve(t.base)
        kept = []
        for b in branches:
            if not p.is_branch(b):
                continue
            if p.resolve(b).id != base.id:
                kept.append(b)
            elif t.mode in ("change", "comment") and b != p.head_branch():
                p.delete_branch(b)  # a question with no changes leaves no branch behind
        t.branches = kept
        t.branch = res.branch if res.branch in kept else (kept[-1] if kept else "")
        if t.branch:
            t.commits = [c.to_json() for c in p.log() if c.branch in kept][-10:]
            man = await self.engine.geometry.build(p, t.branch)
            t.mass_kg, t.builds = man["mass_kg"], man["ok"]
        return res

    async def _after(self, t: BotTask) -> None:
        if t.group:
            return  # the group reports for its concepts
        if t.mode == "interview":
            return
        text = t.reply or ""
        if t.status != "done":
            text = (text + "\n\n" if text else "") + (t.problem or "The task stopped.")
        if t.branch and t.commits and t.mode in ("change", "comment", "draft"):
            others = [b for b in t.branches if b != t.branch]
            text += f"\n\nIt's on branch {t.branch}. Review it, then apply it or check it out."
            if others:
                text += f" I also tried {', '.join(others)}; you'll find {'them' if len(others) > 1 else 'it'} in the version history."
        self.say(t.project, "bot", text.strip() or "Done.", task=t.id, thread=t.thread, branch=t.branch or None, source="comment" if t.mode == "comment" else "chat",
                 actions=["apply", "checkout"] if t.branch and t.commits else [], trace=t.trace_brief(), status=t.status)

    def _bot_branch(self, pid: str, name: str, from_ref: str | None = None) -> tuple[str, str]:
        p = self.engine.store.get(pid)
        base = str(p.resolve(from_ref).id)
        b = p.create_branch(name, base, unique=True)
        return b, base

    # ---------- public entry points ----------

    def start_change(self, pid: str, message: str, selected: str | None = None, from_ref: str | None = None,
                     thread: str | None = None) -> BotTask:
        """A chat request. With `thread`, it continues that conversation: it starts from the branch the
        conversation's last task produced and its messages stay in the same thread."""
        self._check_ready(pid)
        p = self.engine.store.get(pid)
        recent = self._recent(pid, thread=thread)
        if thread and from_ref is None:
            prev = [x for x in self.tasks.values() if x.project == pid and (x.id == thread or x.thread == thread) and x.branch]
            if prev and p.is_branch(prev[-1].branch):
                from_ref = prev[-1].branch
        b, base = self._bot_branch(pid, f"bot/{slugify(message, 'change')[:24]}", from_ref)
        t = self._new_task(pid, "change", message, b, base, thread=thread)
        self.say(pid, "you", message, ctx=selected, task=t.id, source="chat", thread=thread)
        spec = p.read_yaml("spec.yaml", b) or {}
        prompt = (f"User request: {message}\n"
                  + (f"The user has the part '{selected}' selected; the request is probably about it.\n" if selected else "")
                  + (f"\nRecent conversation:\n{recent}\n" if recent else "")
                  + f"\nCurrent spec:\n{S.spec_text_summary(spec)}\n")
        self._launch(t, prompt)
        return t

    def start_comments(self, pid: str, note_ids: list[int]) -> BotTask:
        self._check_ready(pid)
        p = self.engine.store.get(pid)
        notes = (p.read_yaml("notes.yaml") or {}).get("notes", [])
        chosen = [n for n in notes if n["id"] in note_ids]
        if not chosen:
            raise StoreError("No such comments")
        # a follow-up on a comment continues its conversation and builds on its branch
        ids = [n["id"] for n in chosen]
        prev = [x for x in self.tasks.values() if x.project == pid and x.mode == "comment" and set(x.notes) & set(ids)]
        thread = (prev[0].thread or prev[0].id) if prev else None
        from_ref = prev[-1].branch if prev and prev[-1].branch and p.is_branch(prev[-1].branch) else None
        b, base = self._bot_branch(pid, f"bot/comment-{chosen[0]['id']}", from_ref)
        t = self._new_task(pid, "comment", f"Comment {', '.join('#' + str(n['id']) for n in chosen)}", b, base, thread=thread, notes=ids)
        for n in chosen:
            last = next((m["text"] for m in reversed(n["msgs"]) if m.get("who") != "Bot"), n["msgs"][-1]["text"] if n["msgs"] else "")
            self.say(pid, "you", last, ctx=n["part"], task=t.id, thread=thread, source="comment", note=n["id"])
        lines = [f"#{n['id']} on part {n['part']}" + (f" (face {n['face']}, point {n.get('point')})" if n.get("face") else "") + ": "
                 + " / ".join(f"{m['who']}: {m['text']}" for m in n["msgs"]) for n in chosen]
        self._launch(t, "Queued 3D comments:\n" + "\n".join(lines))
        return t

    def generate(self, pid: str, count: int = 3, from_ref: str | None = None) -> dict[str, Any]:
        """'Generate 3 prototypes': one branch per concept, built in parallel."""
        self._check_ready(pid)
        p = self.engine.store.get(pid)
        gid = secrets.token_hex(4)
        spec = p.read_yaml("spec.yaml", from_ref) or {}
        letters = list(CONCEPT_DIRECTIONS)[:max(1, min(count, 3))]
        group: dict[str, Any] = {"id": gid, "project": pid, "tasks": [], "status": "running", "started": time.time()}
        self.groups[gid] = group
        self.say(pid, "you", f"Generate {len(letters)} prototypes", group=gid, source="generate")
        for L in letters:
            b, base = self._bot_branch(pid, f"concept-{L.lower()}", from_ref)
            t = self._new_task(pid, "concept", CONCEPT_DIRECTIONS[L], b, base, group=gid, concept=L)
            group["tasks"].append(t.id)
            prompt = (f"{CONCEPT_DIRECTIONS[L]}\nBuild this concept on your branch.\n\nSpec:\n{S.spec_text_summary(spec)}\n")
            self._launch(t, prompt)
        asyncio.create_task(self._watch_group(gid))
        self.engine.events.publish({"type": "bot.group", "group": self.group_json(gid)})
        return self.group_json(gid)

    def group_json(self, gid: str) -> dict[str, Any]:
        g = self.groups[gid]
        return {**{k: v for k, v in g.items() if k != "tasks"}, "tasks": [self.tasks[i].to_json() for i in g["tasks"]]}

    async def _watch_group(self, gid: str) -> None:
        g = self.groups[gid]
        while any(i in self._running for i in g["tasks"]):
            await asyncio.sleep(0.3)
        await asyncio.sleep(0)  # let the tasks' finally blocks finish
        ts = [self.tasks[i] for i in g["tasks"]]
        g["status"] = "done" if any(t.builds for t in ts) else "failed"
        g["finished"] = time.time()
        lines = []
        for t in ts:
            if t.builds:
                lines.append(f"Concept {t.concept} ({t.branch}): {t.mass_kg:.2f} kg. {t.reply.splitlines()[0] if t.reply else ''}".strip())
            else:
                lines.append(f"Concept {t.concept} ({t.branch or 'no branch'}): didn't finish. {t.problem}".strip())
        ok = [t for t in ts if t.builds]
        head = (f"{len(ok)} of {len(ts)} concepts are ready, each on its own branch. Nothing was applied to your version; "
                "open the history to compare them and check one out.") if ok else "None of the concepts built. " + (ts[0].problem if ts else "")
        self.say(g["project"], "bot", head + "\n\n" + "\n".join(lines), group=gid, source="generate", actions=["history"] if ok else [])
        self.engine.events.publish({"type": "bot.group", "group": self.group_json(gid)})

    def start_draft(self, pid: str) -> BotTask | None:
        """Background draft while the user answers questions (one at a time)."""
        if any(t.project == pid and t.mode == "draft" and t.status == "running" for t in self.tasks.values()):
            return None
        try:
            self._check_ready(pid)
        except StoreError:
            return None
        p = self.engine.store.get(pid)
        b, base = self._bot_branch(pid, "bot/draft")
        t = self._new_task(pid, "draft", "Draft while you answer", b, base)
        spec = p.read_yaml("spec.yaml") or {}
        self._launch(t, f"Build a first draft from this spec:\n{S.spec_text_summary(spec)}\n")
        return t

    async def interview_step(self, pid: str, answered: str | None = None) -> dict[str, Any]:
        """One interview turn: Bot updates the sheet from the latest answer and picks the next question."""
        self._check_ready(pid)
        p = self.engine.store.get(pid)
        head = p.head_branch()
        if not head:
            raise StoreError("Check out a branch to continue the interview")
        lock = self._interview_lock.setdefault(pid, asyncio.Lock())
        async with lock:
            asked: dict[str, Any] = {}

            async def ask_user(args: dict[str, Any]) -> str:
                asked["question_id"] = args.get("question_id") or None
                asked["message"] = (args.get("message") or "").strip()
                return "Shown to the user. End your turn now."

            spec_tool = ToolSpec("ask_user", "Show the user the next question to answer on the What? sheet. Call exactly once, then stop.",
                                 {"type": "object", "properties": {
                                     "question_id": {"type": "string", "description": "Id of the open question to ask, or empty when the sheet is complete"},
                                     "message": {"type": "string", "description": "One short sentence shown above the question"}},
                                  "required": ["question_id", "message"]})
            t = self._new_task(pid, "interview", "Interview", head, str(p.resolve(head).id))
            system = system_prompt("interview", p.meta().get("name", p.id), head, head)
            spec = p.read_yaml("spec.yaml") or {}
            prompt = (f"The user just answered {answered}.\n" if answered else "The interview starts now.\n") + f"Spec:\n{S.spec_text_summary(spec)}\n"

            def on_step(label: str, step: int) -> None:
                t.label, t.step = label, step
                self._emit(t)

            res = await run_loop(self.engine, project=pid, branch=head, task_id=t.id, conv_factory=self._conv_factory(pid, system),
                                 prompt=prompt, allowed=INTERVIEW_TOOLS, local_tools={"ask_user": (spec_tool, ask_user)},
                                 max_steps=10, max_tokens=150_000, on_step=on_step, should_stop=lambda: "question_id" in asked or t.stop_requested,
                                 stop_event=t.stop_event, trace=t.trace, on_trace=lambda: self._emit(t))
            t.status = "failed" if res.status == "failed" and "question_id" not in asked else "done"
            t.problem, t.tokens, t.calls, t.finished = res.problem if t.status == "failed" else "", res.tokens, res.calls, time.time()
            self._emit(t)
            if t.status == "failed":
                raise StoreError(res.problem or "The interview step failed")
            spec = p.read_yaml("spec.yaml") or {}
            open_list = [q["id"] for q in S.open_questions(spec)]
            open_ids = set(open_list)
            qid = asked.get("question_id")
            if qid and qid not in open_ids:  # model picked an answered or unknown id: take the first open one
                qid = open_list[0] if open_list else None
            if not asked and open_ids:
                qid = open_list[0]
            done = qid is None
            msg = asked.get("message") or ("That's everything I need." if done else "")
            if msg:
                self.say(pid, "bot", msg, question=qid, source="interview")
            settings = self.model_settings(pid)
            answered_n = sum(1 for _, q in S.questions(spec) if q.get("answers"))
            if settings.get("build_while_interview") and (done or (answered_n and answered_n % 4 == 0)):
                self.start_draft(pid)
            return {"question_id": qid, "message": msg, "done": done, "open": len(open_ids)}

    # ---------- control ----------

    def stop(self, task_id: str) -> BotTask:
        t = self.tasks.get(task_id)
        if not t:
            raise StoreError("No such task")
        t.stop_requested = True
        t.stop_event.set()
        if t.status == "running":
            t.label = "Stopping"
            self._emit(t)
        return t

    def list(self, pid: str | None = None) -> list[dict[str, Any]]:
        return [t.to_json() for t in sorted(self.tasks.values(), key=lambda x: x.started) if not pid or t.project == pid][-50:]

    async def wait(self, task_id: str, timeout: float = 600) -> BotTask:
        task = self._running.get(task_id)
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        return self.tasks[task_id]

    async def cancel_all(self) -> None:
        for t in list(self._running.values()):
            t.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)
