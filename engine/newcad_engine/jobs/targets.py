"""Compute targets: places that run jobs.

- `local`: pipeline processes on this machine.
- `remote`: another machine running `newcad-engine --worker` (the compute
  node, see compute-node/), reached over HTTP(S) with a token. Job inputs go
  up as a tar.gz, progress is polled, results come back as a tar.gz.

Every target runs the same pipeline (sim/pipeline.py), so a study gives the
same result wherever it runs.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import signal
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import devices

log = logging.getLogger("newcad.jobs")
Progress = Callable[[float, str], None]


class JobFailed(Exception):
    """The job ran and failed; retrying on the same input gives the same error."""


class JobCancelled(Exception):
    """The user cancelled the job."""


class TargetUnavailable(Exception):
    """The target couldn't be reached or broke off; the job can go to another target."""


def pack(d: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                tf.add(p, arcname=str(p.relative_to(d)))
    return buf.getvalue()


def unpack(data: bytes, d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(d, filter="data")  # refuses absolute paths, .. and links out of d


class Target:
    id: str
    name: str
    kind: str
    slots: int

    async def describe(self) -> dict[str, Any]:
        raise NotImplementedError

    async def run(self, job_dir: Path, out_dir: Path, progress: Progress, cancel: asyncio.Event) -> dict[str, Any]:
        raise NotImplementedError

    def config(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind}


class LocalTarget(Target):
    kind = "local"

    def __init__(self, slots: int | None = None, timeout_s: float = 3600):
        self.id = "local"
        self.name = "This computer"
        self.slots = slots or int(os.environ.get("NEWCAD_SIM_SLOTS", "1"))
        self.timeout_s = timeout_s

    def threads(self) -> int:
        perf = devices.describe_local()["cpu"]["performance_cores"]
        return max(1, perf // max(1, self.slots))

    async def describe(self) -> dict[str, Any]:
        d = await asyncio.to_thread(devices.describe_local)
        return {**self.config(), "online": True, "slots": self.slots, "devices": d}

    async def run(self, job_dir: Path, out_dir: Path, progress: Progress, cancel: asyncio.Event) -> dict[str, Any]:
        job = json.loads((job_dir / "job.json").read_text())
        job.setdefault("threads", self.threads())
        job.setdefault("timeout_s", self.timeout_s)
        (job_dir / "job.json").write_text(json.dumps(job))
        env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_TOKEN")) and k != "NEWCAD_TOKEN"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "newcad_engine.sim.pipeline", str(job_dir), str(out_dir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True,
        )
        err_tail: list[bytes] = []

        async def drain_err() -> None:
            assert proc.stderr is not None
            while chunk := await proc.stderr.read(4096):
                err_tail.append(chunk)
                del err_tail[:-8]

        err_task = asyncio.create_task(drain_err())
        final: dict[str, Any] | None = None

        async def read_out() -> None:
            nonlocal final
            assert proc.stdout is not None
            while line := await proc.stdout.readline():
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("done"):
                    final = msg
                elif "progress" in msg:
                    progress(float(msg["progress"]), str(msg.get("stage", "")))

        reader = asyncio.create_task(read_out())
        stopper = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait({reader, stopper}, timeout=self.timeout_s + 60, return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                raise JobCancelled()
            if not done:
                raise JobFailed(f"The job took longer than {self.timeout_s:.0f} s and was stopped")
            await proc.wait()
        except BaseException:
            _kill(proc)
            raise
        finally:
            stopper.cancel()
            reader.cancel()
            await asyncio.gather(err_task, return_exceptions=True)
        if final is None:
            tail = b"".join(err_tail).decode(errors="replace")[-1500:]
            raise JobFailed(f"The simulation process stopped unexpectedly (exit {proc.returncode}). {tail}".strip())
        if not final.get("ok"):
            if final.get("trace"):
                log.warning("pipeline failed: %s", final["trace"])
            raise JobFailed(final.get("error") or "The simulation failed")
        return final["summary"]


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the pipeline and the solver it started
    except (ProcessLookupError, PermissionError, AttributeError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class RemoteTarget(Target):
    kind = "remote"

    def __init__(self, id: str, name: str, url: str, token: str, slots: int = 1,
                 client_factory: Callable[[], Any] | None = None, poll_s: float = 0.5):
        self.id, self.name, self.url, self.token, self.slots = id, name, url.rstrip("/"), token, slots
        self._client_factory = client_factory
        self.poll_s = poll_s
        self._info: dict[str, Any] | None = None
        self._info_t = 0.0

    def config(self) -> dict[str, Any]:
        return {**super().config(), "url": self.url, "slots": self.slots}

    def _client(self):
        import httpx
        if self._client_factory:
            return self._client_factory()
        return httpx.AsyncClient(base_url=self.url, headers={"Authorization": f"Bearer {self.token}"}, timeout=30)

    async def _call(self, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        import httpx
        try:
            async with self._client() as c:
                return await fn(c)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise TargetUnavailable(f"{self.name} refused the token") from None
            raise TargetUnavailable(f"{self.name} answered {e.response.status_code}") from None
        except (httpx.TransportError, OSError) as e:
            raise TargetUnavailable(f"{self.name} is not reachable: {e}") from None

    async def describe(self) -> dict[str, Any]:
        if self._info and time.monotonic() - self._info_t < 15:
            return self._info
        try:
            async def get(c):
                r = await c.get("/api/worker/info")
                r.raise_for_status()
                return r.json()
            info = await self._call(get)
            d = {**self.config(), "online": True, "slots": int(info.get("slots", self.slots)), "devices": info["devices"],
                 "version": info.get("version")}
        except TargetUnavailable as e:
            d = {**self.config(), "online": False, "problem": str(e), "devices": None}
        self._info, self._info_t = d, time.monotonic()
        return d

    async def run(self, job_dir: Path, out_dir: Path, progress: Progress, cancel: asyncio.Event) -> dict[str, Any]:
        bundle = await asyncio.to_thread(pack, job_dir)
        progress(0.01, f"Uploading to {self.name}")

        async def submit(c):
            r = await c.post("/api/worker/jobs", content=bundle, headers={"Content-Type": "application/gzip"})
            r.raise_for_status()
            return r.json()["id"]

        rid = await self._call(submit)
        try:
            while True:
                if cancel.is_set():
                    raise JobCancelled()

                async def status(c):
                    r = await c.get(f"/api/worker/jobs/{rid}")
                    r.raise_for_status()
                    return r.json()

                st = await self._call(status)
                if st["status"] == "running":
                    progress(float(st.get("progress", 0)), f"{st.get('stage', '')} on {self.name}")
                elif st["status"] == "failed":
                    raise JobFailed(st.get("error") or "The simulation failed on the compute node")
                elif st["status"] == "done":
                    progress(0.96, f"Downloading results from {self.name}")

                    async def fetch(c):
                        r = await c.get(f"/api/worker/jobs/{rid}/result.tar.gz")
                        r.raise_for_status()
                        return r.content

                    data = await self._call(fetch)
                    await asyncio.to_thread(unpack, data, out_dir)
                    return st["summary"]
                elif st["status"] == "cancelled":
                    raise TargetUnavailable(f"{self.name} cancelled the job")
                try:
                    await asyncio.wait_for(cancel.wait(), timeout=self.poll_s)
                except asyncio.TimeoutError:
                    pass
        except BaseException:
            async def stop(c):
                await c.delete(f"/api/worker/jobs/{rid}")
            try:
                await asyncio.shield(self._call(stop))
            except Exception:
                pass
            raise


class TargetRegistry:
    """The local target plus remote targets the user added (stored in <home>/targets.json)."""

    def __init__(self, file: Path, local: LocalTarget | None = None):
        self.file = file
        self.local = local or LocalTarget()
        self.remote: dict[str, RemoteTarget] = {}
        if file.exists():
            try:
                for t in json.loads(file.read_text()):
                    self.remote[t["id"]] = RemoteTarget(t["id"], t["name"], t["url"], t["token"], int(t.get("slots", 1)))
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("ignoring broken %s: %s", file, e)

    def all(self) -> list[Target]:
        return [self.local, *self.remote.values()]

    def get(self, tid: str) -> Target | None:
        return self.local if tid == "local" else self.remote.get(tid)

    def _save(self) -> None:
        data = [{"id": t.id, "name": t.name, "url": t.url, "token": t.token, "slots": t.slots} for t in self.remote.values()]
        self.file.write_text(json.dumps(data, indent=1))
        try:
            self.file.chmod(0o600)  # holds compute-node tokens
        except OSError:
            pass

    def add(self, target: RemoteTarget) -> RemoteTarget:
        self.remote[target.id] = target
        self._save()
        return target

    def remove(self, tid: str) -> bool:
        if self.remote.pop(tid, None) is None:
            return False
        self._save()
        return True

    async def describe(self) -> list[dict[str, Any]]:
        return list(await asyncio.gather(*(t.describe() for t in self.all())))
