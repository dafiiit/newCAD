"""Job queue: priorities, progress events, cancel, retry, and a result cache.

A job's result is stored under cache/results/<key>/, where key is a hash of
everything that determines the answer (geometry, materials, boundary
conditions, mesh settings, pipeline version). Submitting a job whose result
exists returns it at once, so re-opening a version never re-runs a solved
study. Identical jobs that are already queued or running are joined, not
duplicated.

Events on the engine bus: {"type": "job.update", "job": {...}}, and for motion
jobs {"type": "job.frame", "frame": {part: [x, y, z, qx, qy, qz, qw]}} with
the body poses while it runs (a few per second).
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import scheduler
from .targets import JobCancelled, JobFailed, TargetRegistry, TargetUnavailable

log = logging.getLogger("newcad.jobs")
ACTIVE = ("queued", "running")


@dataclass
class Job:
    id: str
    kind: str
    project: str
    study: str
    name: str
    ref: str
    commit: str
    key: str
    priority: int = 0
    target_pref: str = "auto"
    status: str = "queued"
    progress: float = 0.0
    stage: str = "Queued"
    target: str | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None
    cached: bool = False
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    attempts: int = 0
    inputs: dict[str, Any] = field(default_factory=dict, repr=False)
    breps: dict[str, str] = field(default_factory=dict, repr=False)
    exclude: set[str] = field(default_factory=set, repr=False)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    _last_pub: float = field(default=0.0, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "project": self.project, "study": self.study, "name": self.name, "ref": self.ref,
            "commit": self.commit, "key": self.key, "priority": self.priority, "status": self.status,
            "progress": round(self.progress, 3), "stage": self.stage, "target": self.target, "error": self.error,
            "summary": self.summary, "cached": self.cached, "created": self.created, "started": self.started,
            "finished": self.finished, "attempts": self.attempts,
        }


class JobManager:
    def __init__(self, cache_dir: Path, work_dir: Path, targets: TargetRegistry, publish):
        self.results = cache_dir / "results"
        self.work = work_dir
        self.targets = targets
        self.publish_event = publish
        self.jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self.results.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)

    # ---------- results ----------

    def result_dir(self, key: str) -> Path:
        if len(key) != 32 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("bad result key")
        return self.results / key

    def cached(self, key: str) -> dict[str, Any] | None:
        f = self.result_dir(key) / "result.json"
        return json.loads(f.read_text()) if f.exists() else None

    # ---------- queue ----------

    def _pub(self, job: Job, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - job._last_pub < 0.2:
            return
        job._last_pub = now
        self.publish_event({"type": "job.update", "project": job.project, "job": job.to_json()})

    async def submit(self, *, kind: str, project: str, study: str, name: str, ref: str, commit: str, key: str,
                     inputs: dict[str, Any], breps: dict[str, str], priority: int = 0, target: str = "auto",
                     force: bool = False) -> Job:
        scheduler.requirements(kind)  # unknown kinds fail here
        for j in self.jobs.values():
            if j.key == key and j.status in ACTIVE:
                if priority > j.priority:
                    j.priority = priority
                return j
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project=project, study=study, name=name, ref=ref, commit=commit,
                  key=key, priority=priority, target_pref=target or "auto", inputs=inputs, breps=breps)
        self.jobs[job.id] = job
        self._trim()
        if force:
            shutil.rmtree(self.result_dir(key), ignore_errors=True)
        summary = self.cached(key)
        if summary is not None:
            job.status, job.progress, job.stage, job.cached, job.summary = "done", 1.0, "Done (cached result)", True, summary
            job.finished = time.time()
            self._pub(job)
            return job
        self._pub(job)
        await self._dispatch()
        return job

    def _trim(self, keep: int = 300) -> None:
        done = [j for j in self.jobs.values() if j.status not in ACTIVE]
        for j in sorted(done, key=lambda j: j.created)[:-keep] if len(done) > keep else []:
            self.jobs.pop(j.id, None)

    async def _dispatch(self) -> None:
        async with self._lock:
            queued = sorted((j for j in self.jobs.values() if j.status == "queued"), key=lambda j: (-j.priority, j.created))
            if not queued:
                return
            descs = await self.targets.describe()
            busy: dict[str, int] = {}
            for j in self.jobs.values():
                if j.status == "running" and j.target:
                    busy[j.target] = busy.get(j.target, 0) + 1
            for job in queued:
                choice = scheduler.choose(job.kind, descs, busy, job.target_pref, job.exclude)
                if choice.target is None:
                    if not choice.candidates:
                        self._finish(job, "failed", error=choice.reason)
                    elif job.stage != choice.reason:
                        job.stage = choice.reason
                        self._pub(job)
                    continue
                target = self.targets.get(choice.target)
                assert target is not None
                busy[target.id] = busy.get(target.id, 0) + 1
                job.status, job.target, job.started, job.stage = "running", target.id, time.time(), choice.reason
                job.attempts += 1
                job.cancel_event = asyncio.Event()
                self._pub(job)
                job.task = asyncio.create_task(self._execute(job, target))

    def _finish(self, job: Job, status: str, error: str | None = None, summary: dict[str, Any] | None = None) -> None:
        job.status, job.error, job.finished = status, error, time.time()
        if summary is not None:
            job.summary = summary
        job.stage = {"done": "Done", "failed": "Failed", "cancelled": "Cancelled"}.get(status, job.stage)
        if status == "done":
            job.progress = 1.0
        self._pub(job)

    async def _execute(self, job: Job, target) -> None:
        jdir = self.work / job.id
        tmp = self.results / f".tmp-{job.key}-{job.id}"
        try:
            (jdir / "parts").mkdir(parents=True, exist_ok=True)
            (jdir / "job.json").write_text(json.dumps(job.inputs))
            for pid, src in job.breps.items():
                shutil.copyfile(src, jdir / "parts" / f"{pid}.brep")

            def progress(f: float, stage: str, frame: dict[str, Any] | None = None) -> None:
                job.progress, job.stage = max(job.progress, min(f, 0.99)), stage
                self._pub(job, force=False)
                if frame:  # live body poses of a motion job (viewport coordinates)
                    self.publish_event({"type": "job.frame", "project": job.project, "job": job.id, "study": job.study,
                                        "key": job.key, "frame": frame})

            summary = await target.run(jdir, tmp, progress, job.cancel_event)
            dest = self.result_dir(job.key)
            if dest.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                tmp.rename(dest)
            if not (dest / "result.json").exists():
                (dest / "result.json").write_text(json.dumps(summary))
            summary = {**summary, "target": target.id}
            self._finish(job, "done", summary=summary)
        except (JobCancelled, asyncio.CancelledError):
            self._finish(job, "cancelled")
        except TargetUnavailable as e:
            log.warning("target %s unavailable for job %s: %s", target.id, job.id, e)
            if job.attempts < 3 and job.target_pref in ("auto", None):
                job.exclude.add(target.id)
                job.status, job.target, job.stage = "queued", None, f"{e}; trying another target"
                self._pub(job)
            else:
                self._finish(job, "failed", error=str(e))
        except JobFailed as e:
            self._finish(job, "failed", error=str(e))
        except Exception as e:  # noqa: BLE001 - a job must never take the engine down
            log.exception("job %s crashed", job.id)
            self._finish(job, "failed", error=f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(jdir, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)
            # a slot is free (or the job was re-queued for another target): start what is waiting
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self._dispatch()))

    # ---------- user actions ----------

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def list(self, project: str | None = None) -> list[Job]:
        return sorted((j for j in self.jobs.values() if project is None or j.project == project), key=lambda j: -j.created)

    def latest(self, project: str, study: str, key: str | None = None) -> Job | None:
        for j in self.list(project):
            if j.study == study and (key is None or j.key == key):
                return j
        return None

    async def cancel(self, jid: str) -> Job:
        job = self.jobs[jid]
        if job.status == "queued":
            self._finish(job, "cancelled")
        elif job.status == "running":
            job.cancel_event.set()
            job.stage = "Cancelling"
            self._pub(job)
        return job

    async def retry(self, jid: str) -> Job:
        job = self.jobs[jid]
        if job.status in ACTIVE:
            return job
        if job.status == "done":
            return job
        job.status, job.error, job.progress, job.stage, job.target = "queued", None, 0.0, "Queued (retry)", None
        job.exclude = set()
        job.created = time.time()
        self._pub(job)
        await self._dispatch()
        return job

    async def close(self) -> None:
        for j in self.jobs.values():
            if j.status == "running":
                j.cancel_event.set()
        await asyncio.gather(*(j.task for j in self.jobs.values() if j.task and not j.task.done()), return_exceptions=True)
