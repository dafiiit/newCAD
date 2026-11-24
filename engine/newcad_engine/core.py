"""The Engine object: one per process, shared by the REST API, the MCP server and BuilderBot."""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .geometry.pool import WorkerPool
from .geometry.service import GeometryService
from .project.store import BOT, ProjectStore, StoreError

log = logging.getLogger("newcad")


@dataclass
class Actor:
    """Who is calling the tools. BuilderBot runs with a guard that pins it to one project and branch."""
    name: str
    email: str
    project: str | None = None  # guard: only this project
    branch: str | None = None   # guard: only write this branch
    task: str | None = None
    owned: list[str] = field(default_factory=list)  # guard: branches this task may write (it starts with one, can create more)

    @property
    def author(self) -> tuple[str, str]:
        return (self.name, self.email)

    @property
    def guarded(self) -> bool:
        return self.branch is not None


AGENT = Actor("Agent", "agent@newcad.local")
current_actor: contextvars.ContextVar[Actor] = contextvars.ContextVar("newcad_actor", default=AGENT)


def bot_actor(project: str, branch: str, task: str) -> Actor:
    return Actor(BOT[0], BOT[1], project=project, branch=branch, task=task, owned=[branch])


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


PROFILE_FIELDS = ("provider", "model", "base_url", "auth")


def _guess_profile_name(d: dict[str, Any]) -> str:
    url = d.get("base_url") or ""
    if ":1234" in url:
        return "LM Studio"
    if ":11434" in url:
        return "Ollama"
    return {"anthropic": "Claude", "openai": "OpenAI", "openai-compatible": "Local model", "scripted": "Scripted"}.get(d.get("provider") or "", "Model")


class Settings:
    """Engine-wide settings (Bot provider and model). API keys are never written here.

    BuilderBot can keep several model profiles (for example a local LM Studio model and a model on a
    server elsewhere) and switch between them. The top-level provider/model/base_url/auth always mirror
    the active profile, so everything that reads them keeps working. Each profile's API key lives in
    the OS keychain under its id (see keystore.py)."""

    DEFAULTS: dict[str, Any] = {
        "provider": "anthropic",
        "model": "",
        "base_url": "",
        "auth": "auto",  # how the key is sent: auto (provider default), bearer, x-api-key
        "effort": "high",
        "max_steps": 40,
        "max_tokens": 600_000,
        "vision": True,
        "build_while_interview": True,
        "profiles": [],
        "active_profile": "",
    }

    def __init__(self, cfg: Config):
        from .keystore import KeyStore

        self.cfg = cfg
        self.data = dict(self.DEFAULTS)
        if cfg.settings_file.exists():
            try:
                self.data.update(json.loads(cfg.settings_file.read_text()))
            except json.JSONDecodeError:
                pass
        self.session_keys: dict[str, str] = {}  # keys pasted in the UI for a provider, kept in memory only
        self.keystore = KeyStore()
        self._migrate()

    # ---------- profiles ----------

    def _migrate(self) -> None:
        """Settings from before profiles: turn the one configured model into the first profile."""
        profs = [p for p in self.data.get("profiles") or [] if isinstance(p, dict) and p.get("id")]
        self.data["profiles"] = profs
        if not profs:
            p = {"id": "default", "name": _guess_profile_name(self.data), **{k: self.data.get(k) or self.DEFAULTS[k] for k in PROFILE_FIELDS}}
            profs.append(p)
            self.data["active_profile"] = p["id"]
        if not self.active():
            self.data["active_profile"] = profs[0]["id"]
        self._mirror()

    def active(self) -> dict[str, Any] | None:
        aid = self.data.get("active_profile")
        return next((p for p in self.data["profiles"] if p["id"] == aid), None)

    def _mirror(self) -> None:
        a = self.active()
        if a:
            for k in PROFILE_FIELDS:
                self.data[k] = a.get(k) if a.get(k) is not None else self.DEFAULTS[k]

    def _save(self) -> None:
        self.cfg.settings_file.write_text(json.dumps(self.data, indent=2))

    def upsert_profile(self, prof: dict[str, Any]) -> dict[str, Any]:
        pid = prof.get("id") or ""
        cur = next((p for p in self.data["profiles"] if p["id"] == pid), None) if pid else None
        if cur is None:
            base = re.sub(r"[^a-z0-9]+", "-", (prof.get("name") or "model").lower()).strip("-") or "model"
            pid, n = base, 2
            while any(p["id"] == pid for p in self.data["profiles"]):
                pid, n = f"{base}-{n}", n + 1
            cur = {"id": pid, "name": prof.get("name") or "Model", "provider": "openai-compatible", "model": "", "base_url": "", "auth": "auto"}
            self.data["profiles"].append(cur)
        for k in ("name", *PROFILE_FIELDS):
            if prof.get(k) is not None:
                cur[k] = prof[k]
        if prof.get("activate"):
            self.data["active_profile"] = cur["id"]
        self._mirror()
        self._save()
        return cur

    def delete_profile(self, pid: str) -> None:
        profs = self.data["profiles"]
        if len(profs) <= 1:
            raise StoreError("Keep at least one model")
        if not any(p["id"] == pid for p in profs):
            raise StoreError(f"No model profile {pid!r}")
        self.data["profiles"] = [p for p in profs if p["id"] != pid]
        self.keystore.delete(f"profile:{pid}")
        if self.data["active_profile"] == pid:
            self.data["active_profile"] = self.data["profiles"][0]["id"]
        self._mirror()
        self._save()

    def set_profile_key(self, pid: str, key: str) -> bool:
        """Returns True when the key was saved in the OS keychain, False when it is kept in memory only."""
        if not any(p["id"] == pid for p in self.data["profiles"]):
            raise StoreError(f"No model profile {pid!r}")
        if not key:
            self.keystore.delete(f"profile:{pid}")
            return self.keystore.persistent()
        return self.keystore.set(f"profile:{pid}", key)

    def keys(self) -> dict[str, str]:
        """Keys by provider for the adapters: the active profile's key wins over one pasted for the provider."""
        out = dict(self.session_keys)
        a = self.active()
        if a:
            k = self.keystore.get(f"profile:{a['id']}")
            if k:
                out[a["provider"]] = k
        return out

    def public(self) -> dict[str, Any]:
        d = dict(self.data)
        d["profiles"] = [{**p, "has_key": self.keystore.has(f"profile:{p['id']}")} for p in self.data["profiles"]]
        d["session_keys"] = sorted(self.session_keys)
        d["keychain"] = self.keystore.persistent()
        return d

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if patch.get("active_profile"):
            if not any(p["id"] == patch["active_profile"] for p in self.data["profiles"]):
                raise StoreError(f"No model profile {patch['active_profile']!r}")
            self.data["active_profile"] = patch["active_profile"]
            self._mirror()
        a = self.active()
        for k, v in patch.items():
            if k in ("profiles", "active_profile") or k not in self.DEFAULTS:
                continue
            self.data[k] = v
            if a is not None and k in PROFILE_FIELDS:
                a[k] = v
        self._save()
        return self.data


class Engine:
    def __init__(self, cfg: Config | None = None):
        self.cfg = (cfg or Config()).ensure()
        self.store = ProjectStore(self.cfg.projects_dir, self.cfg.staging_dir)
        self.pool = WorkerPool(self.cfg.workers, self.cfg.build_timeout_s, self.cfg.build_memory_mb)
        self.geometry = GeometryService(self.cfg.cache_dir, self.cfg.exports_dir, self.pool)
        self.events = EventBus()
        self.settings = Settings(self.cfg)
        from .feedback import FeedbackStore
        self.feedback = FeedbackStore(self.cfg.home)
        self.store.listeners.append(self._on_store)
        from .jobs.manager import JobManager
        from .jobs.targets import LocalTarget, TargetRegistry
        from .jobs.worker_service import WorkerService
        from .sim.service import MateService, SimService
        self.targets = TargetRegistry(self.cfg.home / "targets.json", LocalTarget(timeout_s=self.cfg.sim_timeout_s))
        self.jobs = JobManager(self.cfg.cache_dir, self.cfg.home / "jobs", self.targets, self.events.publish)
        self.sim = SimService(self)
        self.mates = MateService(self)
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
        self._feedback_retry = asyncio.create_task(self.feedback.retry_pending())  # send reports left over from offline runs

    async def stop(self) -> None:
        if self._watch:
            self._watch.cancel()
        if getattr(self, "_feedback_retry", None):
            self._feedback_retry.cancel()
        await self.bot.cancel_all()
        await self.jobs.close()
        await self.worker.close()
        await self.pool.close()

    def project(self, pid: str):
        return self.store.get(pid)


__all__ = ["Engine", "Actor", "current_actor", "bot_actor", "AGENT", "StoreError"]
