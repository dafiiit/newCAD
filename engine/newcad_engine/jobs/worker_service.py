"""The compute-node side of a remote target: accepts job bundles and runs them on this machine.

Served under /api/worker by every engine (token-protected like the rest of
the API). `newcad-engine --worker` starts an engine that only does this, for
a GPU box or a lab machine; see compute-node/.
"""
from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from .targets import JobCancelled, JobFailed, LocalTarget, pack, unpack


@dataclass
class WorkerJob:
    id: str
    status: str = "queued"
    progress: float = 0.0
    stage: str = "Queued"
    error: str | None = None
    summary: dict[str, Any] | None = None
    created: float = field(default_factory=time.time)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "progress": round(self.progress, 3), "stage": self.stage,
                "error": self.error, "summary": self.summary}


class WorkerService:
    KEEP_S = 3600  # finished jobs are kept this long for the client to fetch results

    def __init__(self, root: Path, local: LocalTarget):
        self.root = root
        self.local = local
        self.jobs: dict[str, WorkerJob] = {}
        self._sem = asyncio.Semaphore(local.slots)
        root.mkdir(parents=True, exist_ok=True)

    async def info(self) -> dict[str, Any]:
        d = await self.local.describe()
        return {"version": __version__, "slots": self.local.slots, "devices": d["devices"],
                "running": sum(1 for j in self.jobs.values() if j.status == "running")}

    def _dirs(self, jid: str) -> tuple[Path, Path]:
        return self.root / jid / "in", self.root / jid / "out"

    async def submit(self, bundle: bytes) -> WorkerJob:
        self._gc()
        jid = uuid.uuid4().hex[:16]
        jin, _ = self._dirs(jid)
        try:
            await asyncio.to_thread(unpack, bundle, jin)
        except Exception as e:
            shutil.rmtree(self.root / jid, ignore_errors=True)
            raise ValueError(f"Bad job bundle: {e}") from None
        if not (jin / "job.json").exists():
            shutil.rmtree(self.root / jid, ignore_errors=True)
            raise ValueError("Bad job bundle: no job.json")
        job = WorkerJob(jid)
        self.jobs[jid] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: WorkerJob) -> None:
        jin, jout = self._dirs(job.id)
        async with self._sem:
            if job.cancel.is_set():
                job.status = "cancelled"
                return
            job.status, job.stage = "running", "Starting"

            def progress(f: float, s: str) -> None:
                job.progress, job.stage = f, s

            try:
                job.summary = await self.local.run(jin, jout, progress, job.cancel)
                job.status, job.progress, job.stage = "done", 1.0, "Done"
            except JobCancelled:
                job.status, job.stage = "cancelled", "Cancelled"
            except JobFailed as e:
                job.status, job.error = "failed", str(e)
            except Exception as e:  # noqa: BLE001
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"

    def get(self, jid: str) -> WorkerJob | None:
        return self.jobs.get(jid)

    async def result(self, jid: str) -> bytes | None:
        j = self.jobs.get(jid)
        if not j or j.status != "done":
            return None
        return await asyncio.to_thread(pack, self._dirs(jid)[1])

    def cancel(self, jid: str) -> bool:
        j = self.jobs.get(jid)
        if not j:
            return False
        j.cancel.set()
        if j.status in ("done", "failed", "cancelled"):
            self.jobs.pop(jid, None)
            shutil.rmtree(self.root / jid, ignore_errors=True)
        return True

    def _gc(self) -> None:
        now = time.time()
        for jid, j in list(self.jobs.items()):
            if j.status in ("done", "failed", "cancelled") and now - j.created > self.KEEP_S:
                self.jobs.pop(jid, None)
                shutil.rmtree(self.root / jid, ignore_errors=True)

    async def close(self) -> None:
        for j in self.jobs.values():
            j.cancel.set()
        await asyncio.gather(*(j.task for j in self.jobs.values() if j.task), return_exceptions=True)
