"""Builds a project's parts through the worker pool and caches the results.

Derived files (BREP, GLB, metadata) live in a content-addressed cache outside
git: cache/<key>/, where key = hash(source, tessellation settings, engine
geometry version). Re-opening a version never rebuilds an unchanged part.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from ..config import density_of
from ..project.store import Project, StoreError
from .pool import WorkerPool

GEOMETRY_VERSION = "3"  # 2: face signatures carry the centre of mass; 3: rotation axes of round faces, mass properties
TOLERANCE = 0.1
ANGULAR = 0.3


def part_key(source: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([GEOMETRY_VERSION, TOLERANCE, ANGULAR]).encode())
    h.update(source.encode())
    return h.hexdigest()[:32]


class GeometryService:
    def __init__(self, cache_dir: Path, exports_dir: Path, pool: WorkerPool):
        self.cache = cache_dir
        self.exports = exports_dir
        self.pool = pool
        self._locks: dict[str, asyncio.Lock] = {}

    def entry(self, key: str) -> Path:
        if not all(c in "0123456789abcdef" for c in key) or len(key) != 32:
            raise StoreError("bad cache key")
        return self.cache / key

    async def build_part(self, part_id: str, source: str) -> dict[str, Any]:
        key = part_key(source)
        d = self.entry(key)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if (d / "meta.json").exists():
                return {"ok": True, "key": key, "cached": True, "meta": json.loads((d / "meta.json").read_text())}
            if (d / "error.json").exists():
                return {**json.loads((d / "error.json").read_text()), "key": key, "cached": True}
            tmp = self.cache / f".tmp-{key}-{time.time_ns()}"
            tmp.mkdir(parents=True)
            res = await self.pool.run({"job": "build", "source": source, "part_id": part_id, "out_dir": str(tmp),
                                       "filename": f"parts/{part_id}.py", "tolerance": TOLERANCE, "angular_tolerance": ANGULAR})
            if res.get("ok"):
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                tmp.rename(d)
                return {"ok": True, "key": key, "cached": False, "meta": res["meta"], "log": res.get("log", "")}
            shutil.rmtree(tmp, ignore_errors=True)
            err = {"ok": False, "error": res.get("error", "build failed"), "line": res.get("line"), "log": res.get("log", "")[-4000:]}
            # cache deterministic code errors, not timeouts or crashes
            if "line" in res and res.get("line") is not None:
                d.mkdir(parents=True, exist_ok=True)
                (d / "error.json").write_text(json.dumps(err))
            return {**err, "key": key, "cached": False}

    async def build(self, project: Project, ref: str | None = None, parts: list[str] | None = None) -> dict[str, Any]:
        """Build every part at a version (staged edits included on a branch) and return a manifest."""
        t0 = time.perf_counter()
        commit = project.resolve(ref)
        files = project.files(ref)
        asm = _assembly_from(files)
        todo = [p for p in asm["parts"] if not parts or p["id"] in parts]

        async def one(p: dict[str, Any]) -> dict[str, Any]:
            src = files.get(p.get("file") or f"parts/{p['id']}.py")
            base = {"id": p["id"], "name": p.get("name", p["id"]), "color": p.get("color", "#B4C2D6"), "material": p.get("material", "Steel"),
                    "file": p.get("file") or f"parts/{p['id']}.py"}
            if src is None:
                return {**base, "ok": False, "error": f"Missing file {base['file']}"}
            r = await self.build_part(p["id"], src)
            if not r["ok"]:
                return {**base, "ok": False, "key": r["key"], "error": r["error"], "line": r.get("line"), "log": r.get("log", "")}
            m = r["meta"]
            if p.get("mass_kg") is not None:  # bought-in part with a known mass
                mass = float(p["mass_kg"])
            else:
                mass = m["volume_mm3"] * density_of(p.get("material"))
            return {**base, "ok": True, "key": r["key"], "cached": r["cached"], "glb": f"/api/cache/{r['key']}/part.glb",
                    "mass_kg": mass, "volume_mm3": m["volume_mm3"], "center": m["center"], "bbox": m["bbox"],
                    "faces": len(m["faces"]), "triangles": m["triangles"], "log": r.get("log", "")}

        results = await asyncio.gather(*(one(p) for p in todo))
        ok = [r for r in results if r["ok"]]
        total = sum(r["mass_kg"] for r in ok)
        cg = [sum(r["mass_kg"] * r["center"][k] for r in ok) / total if total else 0.0 for k in range(3)]
        bb = None
        if ok:
            bb = {"min": [min(r["bbox"]["min"][k] for r in ok) for k in range(3)], "max": [max(r["bbox"]["max"][k] for r in ok) for k in range(3)]}
        return {
            "project": project.id, "ref": ref or project.head_ref(), "commit": str(commit.id), "parts": list(results),
            "ok": all(r["ok"] for r in results), "mass_kg": total, "cg": cg, "bbox": bb,
            "build_ms": round((time.perf_counter() - t0) * 1000),
        }

    async def snapshot(self, project: Project, ref: str | None = None, view: str = "iso",
                       size: tuple[int, int] = (800, 600), highlight: str | None = None) -> tuple[bytes, dict[str, Any]]:
        """PNG of the assembly from a named view, plus the build manifest it was drawn from."""
        from .glb import read_glb
        from .render import render
        man = await self.build(project, ref)
        meshes = []
        for p in man["parts"]:
            if not p["ok"]:
                continue
            g = read_glb((self.entry(p["key"]) / "part.glb").read_bytes())
            meshes.append({"id": p["id"], "color": p["color"], "positions": g["positions"], "indices": g["indices"]})
        png = await asyncio.to_thread(render, meshes, view, size, highlight)
        return png, man

    def meta(self, key: str) -> dict[str, Any] | None:
        f = self.entry(key) / "meta.json"
        return json.loads(f.read_text()) if f.exists() else None

    async def export(self, project: Project, ref: str | None, fmt: str, parts: list[str] | None = None) -> dict[str, Any]:
        man = await self.build(project, ref, parts)
        bad = [p for p in man["parts"] if not p["ok"]]
        if bad:
            raise StoreError(f"Can't export: {', '.join(p['id'] for p in bad)} failed to build")
        if not man["parts"]:
            raise StoreError("Nothing to export: the project has no parts yet")
        out_dir = self.exports / project.id
        out_dir.mkdir(parents=True, exist_ok=True)
        name = parts[0] if parts and len(parts) == 1 else project.id
        path = out_dir / f"{name}_{man['commit'][:7]}.{fmt}"
        res = await self.pool.run({"job": "export", "format": fmt, "path": str(path), "write_dir": str(out_dir),
                                   "breps": [str(self.entry(p["key"]) / "part.brep") for p in man["parts"]],
                                   "labels": [p["id"] for p in man["parts"]]})
        if not res.get("ok"):
            raise StoreError(res.get("error", "export failed"))
        return {"path": str(path), "bytes": res["bytes"], "file": path.name, "commit": man["commit"]}

    async def measure(self, project: Project, ref: str | None, kind: str, a: str, b: str) -> dict[str, Any]:
        man = await self.build(project, ref, [a, b])
        by = {p["id"]: p for p in man["parts"]}
        for x in (a, b):
            if x not in by:
                raise StoreError(f"No part {x}")
            if not by[x]["ok"]:
                raise StoreError(f"{x} failed to build: {by[x]['error']}")
        res = await self.pool.run({"job": "measure", "kind": kind, "write_dir": str(self.cache),
                                   "a": str(self.entry(by[a]["key"]) / "part.brep"), "b": str(self.entry(by[b]["key"]) / "part.brep")})
        if not res.get("ok"):
            raise StoreError(res.get("error", "measure failed"))
        res.pop("log", None)
        res.pop("ok", None)
        return res


def _assembly_from(files: dict[str, str]) -> dict[str, Any]:
    import yaml
    a = yaml.safe_load(files.get("assembly.yaml") or "") or {}
    a.setdefault("parts", [])
    return a
