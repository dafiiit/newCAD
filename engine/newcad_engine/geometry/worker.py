"""Sandboxed geometry worker. Runs in its own process, never inside the API.

Protocol: the parent starts `python -m newcad_engine.geometry.worker`. The
worker imports build123d (the slow part, done ahead of time so a rebuild
starts warm), prints `READY` on the protocol channel, reads exactly one JSON
job from stdin, answers with one JSON line and exits. One job per process,
so generated code can't leak state into the next build.

Sandbox (defence in depth, not a security boundary on its own):
- separate process, killed by the parent on timeout
- address-space and CPU-time limits (where the OS enforces them)
- an audit hook that blocks network access, starting programs and writing
  files outside the job's output directory
User code's print() goes to stderr, which the parent keeps as the build log.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

_PROTO = None  # protocol channel (the original stdout)


def _send(obj: dict[str, Any]) -> None:
    assert _PROTO is not None
    _PROTO.write(json.dumps(obj) + "\n")
    _PROTO.flush()


def _limits(memory_mb: int, cpu_s: int) -> None:
    try:
        import resource
        if memory_mb > 0 and sys.platform.startswith("linux"):
            b = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
        if cpu_s > 0:
            ru = resource.getrusage(resource.RUSAGE_SELF)
            used = int(ru.ru_utime + ru.ru_stime) + 1  # the kernel import already used some
            resource.setrlimit(resource.RLIMIT_CPU, (used + cpu_s, used + cpu_s + 5))
    except Exception:
        pass


def _sandbox(write_dir: Path) -> None:
    write_root = str(write_dir.resolve())
    blocked_prefixes = ("socket.", "subprocess.", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty", "pty.", "ctypes.dlopen", "webbrowser.")
    blocked = {"os.system", "os.kill", "os.killpg", "urllib.Request", "http.client.connect", "ftplib.connect", "smtplib.connect"}
    write_events = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.link", "os.symlink", "shutil.rmtree", "shutil.copyfile", "shutil.move"}

    def inside(p: Any) -> bool:
        try:
            return os.path.realpath(os.fsdecode(p)).startswith(write_root)
        except Exception:
            return False

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in blocked or event.startswith(blocked_prefixes):
            raise PermissionError(f"Blocked in the geometry sandbox: {event}")
        if event == "open" and args:
            path, mode = args[0], args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing and isinstance(path, (str, bytes, os.PathLike)) and not inside(path):
                raise PermissionError(f"Blocked in the geometry sandbox: writing {os.fsdecode(path)}")
        elif event in write_events and args and not inside(args[0]):
            raise PermissionError(f"Blocked in the geometry sandbox: {event} {args[0]!r}")

    sys.addaudithook(hook)


# ---------- jobs ----------

def _find_shape(ns: dict[str, Any]) -> Any:
    from build123d import BuildPart, Shape
    for key in ("result", "part"):
        v = ns.get(key)
        if isinstance(v, BuildPart):
            return v.part
        if isinstance(v, Shape):
            return v
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, Shape) for x in v):
            from build123d import Compound
            return Compound(children=list(v))
    builders = [v for k, v in ns.items() if isinstance(v, BuildPart) and not k.startswith("_")]
    if len(builders) == 1:
        return builders[0].part
    raise ValueError("The part script must set `result` to a build123d shape (for example `result = my_part.part`).")


def _tessellate(shape: Any, tolerance: float, angular: float) -> dict[str, Any]:
    import numpy as np
    from .facetags import assign_tags

    pos, nor, idx, fid, sigs = [], [], [], [], []
    base = 0
    for i, face in enumerate(shape.faces()):
        verts, tris = face.tessellate(tolerance, angular)
        try:
            normal = face.normal_at()
            nvec = [normal.X, normal.Y, normal.Z]
        except Exception:
            nvec = None
        c = face.center()
        gt = str(face.geom_type).split(".")[-1].lower()
        try:  # centre of mass (differs from `center` on curved faces); the mesher matches faces by it
            from build123d import CenterOf
            m = face.center(CenterOf.MASS)
            com = [m.X, m.Y, m.Z]
        except Exception:
            com = [c.X, c.Y, c.Z]
        sigs.append({"type": gt, "area": float(face.area), "center": [c.X, c.Y, c.Z], "normal": nvec if gt == "plane" else None, "com": com})
        if not tris:
            continue
        v = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=np.float64)
        t = np.array(tris, dtype=np.int64)
        # per-vertex normals from the surface, falling back to triangle normals
        vn = np.zeros_like(v)
        tri_n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        for k in range(3):
            np.add.at(vn, t[:, k], tri_n)
        ln = np.linalg.norm(vn, axis=1, keepdims=True)
        vn = np.divide(vn, ln, out=np.zeros_like(vn), where=ln > 0)
        pos.append(v)
        nor.append(vn)
        idx.append(t + base)
        fid.append(np.full(len(v), i, dtype=np.int32))
        base += len(v)
    if not pos:
        raise ValueError("The shape has no faces to draw")
    tags = assign_tags(sigs)
    return {
        "positions": np.concatenate(pos), "normals": np.concatenate(nor), "indices": np.concatenate(idx),
        "face_ids": np.concatenate(fid), "sigs": sigs, "tags": tags,
    }


def job_build(job: dict[str, Any]) -> dict[str, Any]:
    from build123d import export_brep
    from .glb import write_glb

    out = Path(job["out_dir"])
    t0 = time.perf_counter()
    ns: dict[str, Any] = {"__name__": "__newcad_part__"}
    code = compile(job["source"], job.get("filename", "part.py"), "exec")
    exec(code, ns)  # noqa: S102 - this is the sandboxed worker's purpose
    shape = _find_shape(ns)
    t_exec = time.perf_counter() - t0
    if not shape.is_valid:
        raise ValueError("The resulting shape is not a valid solid (check for self-intersections or zero-thickness walls)")
    export_brep(shape, str(out / "part.brep"))
    tess = _tessellate(shape, job.get("tolerance", 0.1), job.get("angular_tolerance", 0.3))
    bb = shape.bounding_box()
    c = shape.center() if shape.volume > 0 else bb.center()
    extras = {"part": job.get("part_id"), "faceTags": tess["tags"]}
    glb = write_glb(job.get("part_id", "part"), tess["positions"], tess["normals"], tess["indices"], tess["face_ids"], extras)
    (out / "part.glb").write_bytes(glb)
    meta = {
        "volume_mm3": float(shape.volume),
        "area_mm2": float(shape.area),
        "center": [c.X, c.Y, c.Z],
        "bbox": {"min": [bb.min.X, bb.min.Y, bb.min.Z], "max": [bb.max.X, bb.max.Y, bb.max.Z]},
        "solids": len(shape.solids()),
        "faces": [{"tag": t, **s} for t, s in zip(tess["tags"], tess["sigs"])],
        "triangles": int(len(tess["indices"])),
        "exec_s": round(t_exec, 3),
        "total_s": round(time.perf_counter() - t0, 3),
    }
    (out / "meta.json").write_text(json.dumps(meta))
    return {"ok": True, "meta": meta}


def _load(paths: list[str]) -> list[Any]:
    from build123d import import_brep
    return [import_brep(p) for p in paths]


def job_export(job: dict[str, Any]) -> dict[str, Any]:
    from build123d import Compound, export_step, export_stl
    shapes = _load(job["breps"])
    shape = shapes[0] if len(shapes) == 1 else Compound(children=shapes)
    if job.get("labels") and len(shapes) > 1:
        for s, lab in zip(shapes, job["labels"]):
            s.label = lab
    fmt, path = job["format"], job["path"]
    if fmt == "step":
        export_step(shape, path)
    elif fmt == "stl":
        export_stl(shape, path, tolerance=job.get("tolerance", 0.05))
    else:
        raise ValueError(f"Unknown export format {fmt}")
    return {"ok": True, "path": path, "bytes": os.path.getsize(path)}


def job_measure(job: dict[str, Any]) -> dict[str, Any]:
    a, b = _load([job["a"], job["b"]])
    kind = job["kind"]
    if kind == "distance":
        return {"ok": True, "distance_mm": float(a.distance_to(b))}
    if kind == "clash":
        inter = a.intersect(b)
        vol = float(inter.volume) if inter is not None else 0.0
        return {"ok": True, "overlap_mm3": vol, "clash": vol > 1e-3, "distance_mm": 0.0 if vol > 1e-3 else float(a.distance_to(b))}
    raise ValueError(f"Unknown measure {kind}")


JOBS = {"build": job_build, "export": job_export, "measure": job_measure}


def main() -> None:
    global _PROTO
    # keep the real stdout for the protocol; everything user code prints goes to stderr
    _PROTO = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        import build123d  # noqa: F401  (warm import: this is what makes rebuilds fast)
        import numpy  # noqa: F401
        from . import glb, facetags  # noqa: F401
    except Exception as e:
        _send({"ok": False, "error": f"Geometry kernel failed to load: {e}"})
        return
    _send({"ready": True})
    line = sys.stdin.readline()
    if not line:
        return
    job = json.loads(line)
    out = Path(job.get("out_dir") or job.get("write_dir") or ".")
    sys.dont_write_bytecode = True
    _limits(int(job.get("memory_mb", 0)), int(job.get("cpu_s", 0)))
    _sandbox(out)
    try:
        res = JOBS[job["job"]](job)
    except BaseException as e:  # noqa: BLE001 - report every failure of generated code
        tb = traceback.extract_tb(e.__traceback__)
        user = [f for f in tb if f.filename == job.get("filename", "part.py")]
        line_no = user[-1].lineno if user else None
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "line": line_no, "trace": traceback.format_exc(limit=6)[-2000:]}
    _send(res)


if __name__ == "__main__":
    main()
