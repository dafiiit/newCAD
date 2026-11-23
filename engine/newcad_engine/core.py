"""The Engine object: one per process, shared by the REST API, the MCP server and BuilderBot."""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from .config import Config
from .geometry.pool import WorkerPool
from .geometry.service import GeometryService
from .project.store import BOT, ProjectStore, StoreError

log = logging.getLogger("newcad")


@dataclass(frozen=True)
class Actor:
    """Who is calling the tools. BuilderBot runs with a guard that pins it to one project and branch."""
    name: str
    email: str
    project: str | None = None  # guard: only this project
    branch: str | None = None   # guard: only write this branch
    task: str | None = None

    @property
    def author(self) -> tuple[str, str]:
        return (self.name, self.email)

    @property
    def guarded(self) -> bool:
        return self.branch is not None


AGENT = Actor("Agent", "agent@newcad.local")
current_actor: contextvars.ContextVar[Actor] = contextvars.ContextVar("newcad_actor", default=AGENT)


def bot_actor(project: str, branch: str, task: str) -> Actor:
    return Actor(BOT[0], BOT[1], project=project, branch=branch, task=task)


class EventBus:
    """Fan-out of engine events to WebSocket clients. Safe to publish from worker threads."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}

        def push() -> None:
            for q in list(self._subs):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(event)

        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            push()
        else:
            loop.call_soon_threadsafe(push)


class Settings:
    """Engine-wide settings (Bot provider and model). API keys are never written here."""

    DEFAULTS: dict[str, Any] = {
        "provider": "anthropic",
        "model": "",
        "base_url": "",
        "effort": "high",
        "max_steps": 40,
        "max_tokens": 600_000,
        "vision": True,
        "build_while_interview": True,
    }

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data = dict(self.DEFAULTS)
        if cfg.settings_file.exists():
            try:
                self.data.update(json.loads(cfg.settings_file.read_text()))
            except json.JSONDecodeError:
                pass
        self.session_keys: dict[str, str] = {}  # keys pasted in the UI, kept in memory only

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        for k, v in patch.items():
            if k in self.DEFAULTS:
                self.data[k] = v
        self.cfg.settings_file.write_text(json.dumps(self.data, indent=2))
        return self.data


class Engine:
    def __init__(self, cfg: Config | None = None):
        self.cfg = (cfg or Config()).ensure()
        self.store = ProjectStore(self.cfg.projects_dir, self.cfg.staging_dir)
        self.pool = WorkerPool(self.cfg.workers, self.cfg.build_timeout_s, self.cfg.build_memory_mb)
        self.geometry = GeometryService(self.cfg.cache_dir, self.cfg.exports_dir, self.pool)
        self.events = EventBus()
        self.settings = Settings(self.cfg)
        self.store.listeners.append(self._on_store)
        from .jobs.manager import JobManager
        from .jobs.targets import LocalTarget, TargetRegistry
        from .jobs.worker_service import WorkerService
        from .sim.service import SimService
        self.targets = TargetRegistry(self.cfg.home / "targets.json", LocalTarget(timeout_s=self.cfg.sim_timeout_s))
        self.jobs = JobManager(self.cfg.cache_dir, self.cfg.home / "jobs", self.targets, self.events.publish)
        self.sim = SimService(self)
        self.worker = WorkerService(self.cfg.home / "worker", self.targets.local)
        self._watch: asyncio.Task[None] | None = None
        self._ref_seen: dict[str, str] = {}
        from .agent.tasks import BotManager  # late import: agent depends on core
        self.bot = BotManager(self)
        from .mcp.server import build_mcp
        self.mcp = build_mcp(self)

    def _on_store(self, pid: str, kind: str, data: dict[str, Any]) -> None:
        self.events.publish({"type": "project.changed", "project": pid, "kind": kind, **data})
        if kind in ("commit", "checkout", "branch", "created"):
            self._ref_seen[pid] = self._ref_signature(pid)

    def _ref_signature(self, pid: str) -> str:
        try:
            p = self.store.get(pid)
            return json.dumps([p.head_ref(), p.tips()])
        except Exception:
            return ""

    async def _watch_refs(self) -> None:
        """Notice commits made by another process (for example `newcad-mcp` driven by Claude Desktop)."""
        while True:
            await asyncio.sleep(2.0)
            try:
                for s in await asyncio.to_thread(self.store.list):
                    sig = await asyncio.to_thread(self._ref_signature, s["id"])
                    old = self._ref_seen.get(s["id"])
                    self._ref_seen[s["id"]] = sig
                    if old is not None and old != sig:
                        self.events.publish({"type": "project.changed", "project": s["id"], "kind": "external"})
            except Exception as e:  # keep watching
                log.debug("ref watch: %s", e)

    async def start(self) -> None:
        self.events.bind(asyncio.get_running_loop())
        await self.pool.start()
        self._watch = asyncio.create_task(self._watch_refs())

    async def stop(self) -> None:
        if self._watch:
            self._watch.cancel()
        await self.bot.cancel_all()
        await self.jobs.close()
        await self.worker.close()
        await self.pool.close()

    def project(self, pid: str):
        return self.store.get(pid)


__all__ = ["Engine", "Actor", "current_actor", "bot_actor", "AGENT", "StoreError"]
