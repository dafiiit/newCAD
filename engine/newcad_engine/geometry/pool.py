"""Pool of pre-warmed, single-use geometry worker processes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("newcad.geometry")


@dataclass
class _Worker:
    proc: asyncio.subprocess.Process
    stderr: list[bytes]
    reader: asyncio.Task[None]


class WorkerPool:
    """Keeps `size` worker processes that have already imported build123d.

    Each job takes one worker and a replacement starts right away, so a build
    pays the kernel import only when more jobs arrive than warm workers.
    """

    def __init__(self, size: int = 3, timeout_s: float = 60, memory_mb: int = 4096):
        self.size = max(1, size)
        self.timeout_s = timeout_s
        self.memory_mb = memory_mb
        self._ready: asyncio.Queue[_Worker] = asyncio.Queue()
        self._spawning = 0
        self._closed = False
        self._sem: asyncio.Semaphore | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self._sem = asyncio.Semaphore(self.size * 2)
        for _ in range(self.size):
            self._spawn_bg()

    def _spawn_bg(self) -> None:
        if self._closed:
            return
        self._spawning += 1
        t = asyncio.create_task(self._spawn())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _spawn(self) -> None:
        try:
            w = await self._start_worker()
            if w is not None:
                await self._ready.put(w)
        finally:
            self._spawning -= 1

    async def _start_worker(self) -> _Worker | None:
        env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_TOKEN")) and k not in ("NEWCAD_TOKEN",)}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "newcad_engine.geometry.worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        stderr: list[bytes] = []

        async def drain() -> None:
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    return
                if sum(len(c) for c in stderr) < 64_000:
                    stderr.append(chunk)

        reader = asyncio.create_task(drain())
        assert proc.stdout is not None
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=120)
            msg = json.loads(line or b"{}")
        except (asyncio.TimeoutError, json.JSONDecodeError):
            msg = {}
        except asyncio.CancelledError:
            proc.kill()
            reader.cancel()
            await proc.wait()
            raise
        if not msg.get("ready"):
            log.error("geometry worker failed to start: %s %s", msg, b"".join(stderr)[-2000:])
            proc.kill()
            await asyncio.sleep(1.0)  # avoid a hot respawn loop when the kernel is broken
            return None
        return _Worker(proc, stderr, reader)

    async def _take(self) -> _Worker:
        if self._ready.empty() and self._spawning == 0:
            self._spawn_bg()
        w = await self._ready.get()
        self._spawn_bg()
        return w

    async def run(self, job: dict[str, Any], timeout_s: float | None = None) -> dict[str, Any]:
        """Run one job in a fresh worker. Always returns a dict with `ok`."""
        assert self._sem is not None, "pool not started"
        timeout = timeout_s or self.timeout_s
        job = {**job, "memory_mb": self.memory_mb, "cpu_s": int(timeout) + 2}
        async with self._sem:
            w = await self._take()
            assert w.proc.stdin is not None and w.proc.stdout is not None
            try:
                w.proc.stdin.write((json.dumps(job) + "\n").encode())
                await w.proc.stdin.drain()
                line = await asyncio.wait_for(w.proc.stdout.readline(), timeout=timeout)
                if line:
                    res = json.loads(line)
                else:
                    await asyncio.wait_for(w.proc.wait(), timeout=5)
                    rc = w.proc.returncode
                    why = "used too much CPU time" if rc in (-24, 152) else "ran out of memory or crashed"
                    res = {"ok": False, "error": f"The build {why} and was stopped (exit {rc})"}
            except asyncio.TimeoutError:
                w.proc.kill()
                res = {"ok": False, "error": f"Build took longer than {timeout:.0f} s and was stopped"}
            except (BrokenPipeError, ConnectionResetError, json.JSONDecodeError) as e:
                res = {"ok": False, "error": f"Geometry worker crashed: {e}"}
            finally:
                try:
                    await asyncio.wait_for(w.proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    w.proc.kill()
                try:
                    await asyncio.wait_for(w.reader, timeout=2)
                except asyncio.TimeoutError:
                    w.reader.cancel()
            res["log"] = b"".join(w.stderr).decode("utf-8", "replace")[-8000:]
            return res

    async def wait_ready(self, timeout: float = 60) -> None:
        """Wait until all warm workers are up (benchmarks and tests)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while self._ready.qsize() < self.size and loop.time() < end:
            await asyncio.sleep(0.1)

    async def close(self) -> None:
        self._closed = True
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        while not self._ready.empty():
            w = self._ready.get_nowait()
            try:
                w.proc.kill()
            except ProcessLookupError:
                pass
            w.reader.cancel()
            try:
                await asyncio.wait_for(w.proc.wait(), timeout=3)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
            if w.proc.stdin is not None:
                w.proc.stdin.close()
