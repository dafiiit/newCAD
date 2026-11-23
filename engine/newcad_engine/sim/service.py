"""Studies on top of the project store, the geometry service and the job queue.

Shared by the REST API (the Check tab) and the `sim_*` MCP tools (BuilderBot
and external agents), so both edit the same studies/<id>.yaml files.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..project.store import YOU, Project, StoreError, slugify
from ..project.templates import dump
from . import study as St

KIND = {"static": "fem.static", "modal": "fem.modal", "thermal": "fem.thermal"}


class SimService:
    def __init__(self, engine: Any):
        self.engine = engine

    @property
    def jobs(self):
        return self.engine.jobs

    # ---------- study files ----------

    def list(self, p: Project, ref: str | None = None) -> list[St.Study]:
        return St.from_files(p.files(ref))

    def read(self, p: Project, sid: str, ref: str | None = None) -> St.Study:
        for s in self.list(p, ref):
            if s.id == sid:
                return s
        raise StoreError(f"No study {sid!r}")

    def save(self, p: Project, study: St.Study, branch: str | None, author: tuple[str, str] = YOU, message: str | None = None) -> St.Study:
        b = p._branch_for_write(branch) if branch is None or branch == "HEAD" else branch
        p.commit(b, message or f"Study: {study.name}", author, changes={St.path_of(study.id): dump(study.to_yaml_dict())},
                 include_staged=False)
        return study

    def create(self, p: Project, name: str, kind: str, branch: str | None, author: tuple[str, str] = YOU,
               template: dict[str, Any] | None = None) -> St.Study:
        if kind not in St.ALLOWED:
            raise StoreError(f"Study type must be one of {', '.join(St.ALLOWED)}")
        used = {s.id for s in self.list(p, branch)}
        base = slugify(name, kind)[:30].replace(".", "-") or kind
        sid, i = base, 2
        while sid in used:
            sid, i = f"{base}-{i}", i + 1
        data = {**(template or {}), "id": sid, "name": name.strip() or kind.capitalize(), "type": kind}
        try:
            study = St.Study.model_validate(data)
        except Exception as e:
            raise StoreError(f"Invalid study: {e}") from None
        return self.save(p, study, branch, author, f"New study: {study.name}")

    def replace(self, p: Project, sid: str, data: dict[str, Any], branch: str | None, author: tuple[str, str] = YOU) -> St.Study:
        try:
            study = St.Study.model_validate({**data, "id": sid})
        except Exception as e:
            raise StoreError(f"Invalid study: {e}") from None
        return self.save(p, study, branch, author)

    def delete(self, p: Project, sid: str, branch: str | None, author: tuple[str, str] = YOU) -> None:
        self.read(p, sid, branch)
        b = p._branch_for_write(branch) if branch is None or branch == "HEAD" else branch
        p.commit(b, f"Remove study {sid}", author, changes={St.path_of(sid): None}, include_staged=False)

    # ---------- running ----------

    async def prepare(self, p: Project, sid: str, ref: str | None = None) -> dict[str, Any]:
        """Build the model at ref and resolve the study into solver input. Raises StoreError with what to fix."""
        study = self.read(p, sid, ref)
        geo = self.engine.geometry
        man = await geo.build(p, ref, study.parts)
        metas = {}
        for part in man["parts"]:
            if part["ok"]:
                metas[part["id"]] = geo.meta(part["key"])
        try:
            inputs = St.resolve(study, man, metas)
        except St.StudyProblem as e:
            raise StoreError(str(e)) from None
        breps = {x["id"]: str(geo.entry(x["key"]) / "part.brep") for x in inputs["parts"]}
        stable = {k: v for k, v in inputs.items() if k not in ("warnings", "name")}
        key = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:32]
        return {"study": study, "inputs": inputs, "breps": breps, "key": key, "manifest": man}

    async def run(self, p: Project, sid: str, ref: str | None = None, priority: int = 0, target: str | None = None,
                  force: bool = False):
        prep = await self.prepare(p, sid, ref)
        study: St.Study = prep["study"]
        man = prep["manifest"]
        return await self.jobs.submit(kind=KIND[study.type], project=p.id, study=sid, name=study.name, ref=man["ref"],
                                      commit=man["commit"], key=prep["key"], inputs=prep["inputs"], breps=prep["breps"],
                                      priority=priority, target=target or study.target, force=force)

    async def state(self, p: Project, sid: str, ref: str | None = None) -> dict[str, Any]:
        """Run state and result of a study at a version: none / queued / running / done / failed / problem."""
        try:
            prep = await self.prepare(p, sid, ref)
        except StoreError as e:
            return {"status": "problem", "problem": str(e)}
        key = prep["key"]
        job = self.jobs.latest(p.id, sid, key)
        summary = self.jobs.cached(key)
        out: dict[str, Any] = {"status": "none", "key": key, "commit": prep["manifest"]["commit"], "warnings": prep["inputs"]["warnings"]}
        if summary is not None:
            out.update(status="done", summary=summary, files=files_of(key))
        if job is not None:
            out["job"] = job.to_json()
            if job.status in ("queued", "running", "failed") and summary is None:
                out["status"] = job.status
        return out


def files_of(key: str) -> dict[str, str]:
    return {f: f"/api/results/{key}/{f}" for f in ("field.glb", "result.json", "result.vtu", "mesh.msh")}


def summary_text(s: dict[str, Any], study_name: str = "") -> str:
    """Plain-language result summary for agents."""
    head = f"{study_name}: " if study_name else ""
    m = s.get("mesh", {})
    mesh = f"Mesh {m.get('elements', 0):,} elements (min quality {m.get('min_quality', 0):.2f})."
    lines = []
    if s["type"] == "static":
        at = s["max_von_mises_at"]
        sf = s["min_safety_factor"]
        tgt = s.get("safety_target")
        lines.append(f"{head}peak von Mises stress {s['max_von_mises_mpa']:.1f} MPa on face {at['face']} of {at['part']} "
                     f"near ({', '.join(f'{v:.1f}' for v in at['point'])}) mm.")
        lines.append(f"Minimum safety factor against yield {sf:.2f}" + (f" (target {tgt})" if tgt else "") + ".")
        lines.append(f"Max displacement {s['max_displacement_mm']:.4g} mm at ({', '.join(f'{v:.1f}' for v in s['max_displacement_at']['point'])}).")
        if s.get("reactions_n"):
            lines.append("Reaction forces at fixed faces (N): " + "; ".join("[" + ", ".join(f"{v:.1f}" for v in r) + "]" for r in s["reactions_n"]))
    elif s["type"] == "modal":
        fr = s.get("frequencies_hz", [])
        lines.append(f"{head}natural frequencies " + ", ".join(f"{f:.1f}" for f in fr) + " Hz.")
        for md in s.get("modes", [])[:3]:
            at = md["max_at"]
            lines.append(f"Mode {md['index']} ({md['frequency_hz']:.1f} Hz) moves most at {at['part']} face {at['face']}.")
    else:
        lines.append(f"{head}temperature {s['min_temperature_c']:.1f} to {s['max_temperature_c']:.1f} °C; hottest at {s['max_temperature_at']['part']} "
                     f"face {s['max_temperature_at']['face']}.")
    lines.append(mesh)
    for w in s.get("warnings", []):
        lines.append(f"Note: {w}")
    return " ".join(lines)
