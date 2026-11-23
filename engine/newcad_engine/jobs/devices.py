"""What this machine can compute with: CPU cores, memory, CUDA GPUs, installed solvers."""
from __future__ import annotations

import functools
import importlib.metadata
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from typing import Any


def _sysctl(name: str) -> str | None:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=3).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _physical_cores_linux() -> int | None:
    try:
        cores = set()
        phys = core = None
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("physical id"):
                    phys = line.split(":")[1].strip()
                elif line.startswith("core id"):
                    core = line.split(":")[1].strip()
                elif not line.strip() and core is not None:
                    cores.add((phys, core))
                    phys = core = None
        return len(cores) or None
    except OSError:
        return None


def cpu() -> dict[str, Any]:
    logical = os.cpu_count() or 1
    try:
        usable = len(os.sched_getaffinity(0))  # containers often get fewer cores than the host has
    except AttributeError:
        usable = logical
    perf = None
    model = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        # Apple Silicon: performance cores do the solver work, efficiency cores keep the UI responsive
        p = _sysctl("hw.perflevel0.physicalcpu")
        perf = int(p) if p and p.isdigit() else None
        model = _sysctl("machdep.cpu.brand_string") or model
    elif sys.platform.startswith("linux"):
        pc = _physical_cores_linux()
        perf = min(pc, usable) if pc else None
    return {"arch": platform.machine(), "model": model, "logical_cores": usable,
            "performance_cores": perf or max(1, usable // 2 if usable > 2 else usable)}


def memory_gb() -> float | None:
    if sys.platform == "darwin":
        v = _sysctl("hw.memsize")
        return round(int(v) / 2**30, 1) if v and v.isdigit() else None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 2**20, 1)
    except OSError:
        pass
    return None


def cuda_gpus() -> list[dict[str, Any]]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = subprocess.run([smi, "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2:
            try:
                gpus.append({"name": parts[0], "memory_gb": round(float(parts[1]) / 1024, 1), "compute_capability": parts[2] if len(parts) > 2 else None})
            except ValueError:
                continue
    return gpus


def _gmsh_version() -> str | None:
    # don't import gmsh here: it is GPL and must stay out of the engine process
    if importlib.util.find_spec("gmsh") is None:
        return None
    try:
        return importlib.metadata.version("gmsh")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def solvers() -> dict[str, str | None]:
    from ..sim.fem.calculix import ccx_version
    return {"gmsh": _gmsh_version(), "calculix": ccx_version()}


@functools.lru_cache(maxsize=1)
def describe_local() -> dict[str, Any]:
    """Cached: hardware doesn't change while the engine runs. Call refresh() after installing a solver."""
    return {"cpu": cpu(), "memory_gb": memory_gb(), "gpus": cuda_gpus(), "platform": f"{sys.platform}-{platform.machine()}",
            "solvers": solvers()}


def refresh() -> dict[str, Any]:
    describe_local.cache_clear()
    return describe_local()
