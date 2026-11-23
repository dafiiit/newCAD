"""Study model: one YAML file per study in the project's git repository.

    studies/<id>.yaml

The UI edits it, BuilderBot edits it through the `sim_*` MCP tools, and both
see the same file. Boundary conditions point at B-rep faces by their stable
face tag, plus the face's geometric signature so a rebuild that renumbers or
moves faces can be re-matched (see geometry/facetags.py).

Units: mm, N, MPa, °C, W. Gravity is given in m/s².

Motion studies (`type: motion`) have no boundaries or mesh: their joints are
the mates in assembly.yaml, and `motion` holds drivers, springs, duration and
an optional parameter sweep (see sim/motion/model.py).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..geometry.facetags import rematch
from . import materials as M
from .motion.model import MotionSetup

StudyType = Literal["static", "modal", "thermal", "motion"]
BoundaryType = Literal["fixed", "force", "pressure", "gravity", "temperature", "heat_flux", "convection"]

ALLOWED: dict[str, set[str]] = {
    "static": {"fixed", "force", "pressure", "gravity"},
    "modal": {"fixed"},
    "thermal": {"temperature", "heat_flux", "convection"},
    "motion": set(),
}
NEEDS_FACES = {"fixed", "force", "pressure", "temperature", "heat_flux", "convection"}

SIM_VERSION = "2"


class FaceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    part: str
    tag: str
    sig: dict[str, Any] | None = Field(default=None, description="Geometric signature of the face when it was picked")


class Boundary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    type: BoundaryType
    label: str = ""
    faces: list[FaceRef] = Field(default_factory=list)
    vector: list[float] | None = Field(default=None, description="force: total force in N over all faces; gravity: acceleration in m/s²")
    value: float | None = Field(default=None, description="pressure MPa, temperature °C, heat_flux W total, convection W/(m²·K)")
    ambient: float | None = Field(default=None, description="convection: ambient temperature in °C")

    @field_validator("vector")
    @classmethod
    def _vec3(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and len(v) != 3:
            raise ValueError("vector needs three components [x, y, z]")
        return v


class MeshSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    size: float | None = Field(default=None, gt=0, description="Target element size in mm; empty = automatic")
    order: Literal[1, 2] = 2


class Study(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    type: StudyType = "static"
    parts: list[str] | None = Field(default=None, description="Parts in the study; empty = the whole assembly (parts are bonded where they touch)")
    materials: dict[str, str] = Field(default_factory=dict, description="Material per part id; default: the part's material")
    boundaries: list[Boundary] = Field(default_factory=list)
    mesh: MeshSettings = Field(default_factory=MeshSettings)
    modes: int = Field(default=6, ge=1, le=30)
    safety_target: float | None = Field(default=None, gt=0)
    target: str = Field(default="auto", description="Compute target id, or auto")
    motion: MotionSetup | None = Field(default=None, description="Motion studies: drivers, springs, duration, sweep")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", v):
            raise ValueError("study id: lower-case letters, digits, - and _")
        return v

    def next_boundary_id(self, kind: str) -> str:
        used = {b.id for b in self.boundaries}
        i = 1
        while f"{kind}-{i}" in used:
            i += 1
        return f"{kind}-{i}"

    def to_yaml_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, mode="json")


def path_of(sid: str) -> str:
    return f"studies/{sid}.yaml"


def from_files(files: dict[str, str]) -> list[Study]:
    import yaml
    out = []
    for path in sorted(files):
        if path.startswith("studies/") and path.endswith(".yaml"):
            data = yaml.safe_load(files[path]) or {}
            data.setdefault("id", path[len("studies/"):-5])
            try:
                out.append(Study.model_validate(data))
            except Exception:  # a broken file shouldn't hide the others
                continue
    return out


class StudyProblem(Exception):
    """The study can't run as set up; the message says what to fix."""


def resolve(study: Study, manifest: dict[str, Any], metas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Turn a study plus a build of the model into a solver-ready job description.

    `metas` maps part id to that part's build metadata (faces with tags and signatures).
    Raises StudyProblem with a readable message when the setup is incomplete.
    """
    by = {p["id"]: p for p in manifest["parts"]}
    ids = study.parts or [p["id"] for p in manifest["parts"]]
    if not ids:
        raise StudyProblem("The model has no parts yet")
    for pid in ids:
        if pid not in by:
            raise StudyProblem(f"Part {pid} is not in the model")
        if not by[pid]["ok"]:
            raise StudyProblem(f"Part {pid} doesn't build: {by[pid].get('error')}")
    allowed = ALLOWED[study.type]
    warnings: list[str] = []
    bcs = []
    scale = 100.0
    if manifest.get("bbox"):
        mn, mx = manifest["bbox"]["min"], manifest["bbox"]["max"]
        scale = max(1.0, max(mx[k] - mn[k] for k in range(3)))
    for b in study.boundaries:
        name = b.label or b.id or b.type
        if b.type not in allowed:
            raise StudyProblem(f"{name}: a {b.type} condition doesn't apply to a {study.type} study")
        faces: list[tuple[str, str]] = []
        for f in b.faces:
            if f.part not in ids:
                raise StudyProblem(f"{name}: part {f.part} is not in this study")
            cands = [(x["tag"], {k: v for k, v in x.items() if k != "tag"}) for x in metas[f.part]["faces"]]
            if any(t == f.tag for t, _ in cands):
                faces.append((f.part, f.tag))
                continue
            if not f.sig:
                raise StudyProblem(f"{name}: face {f.tag} on {f.part} no longer exists. Pick the face again.")
            m = rematch(f.sig, cands, scale)
            if m["tag"] is None or m["ambiguous"]:
                raise StudyProblem(f"{name}: the picked face on {f.part} changed too much to find it again. Pick the face again.")
            warnings.append(f"{name}: face {f.tag} on {f.part} moved; using {m['tag']} (match score {m['score']})")
            faces.append((f.part, m["tag"]))
        if b.type in NEEDS_FACES and not faces:
            raise StudyProblem(f"{name}: pick at least one face")
        if b.type in ("force", "gravity") and not b.vector:
            raise StudyProblem(f"{name}: needs a vector")
        if b.type in ("pressure", "temperature", "heat_flux", "convection") and b.value is None:
            raise StudyProblem(f"{name}: needs a value")
        bcs.append({"id": b.id, "label": name, "type": b.type, "faces": faces, "vector": b.vector, "value": b.value,
                    "ambient": b.ambient if b.ambient is not None else 20.0})
    if study.type == "static" and not any(b["type"] == "fixed" for b in bcs):
        raise StudyProblem("A static study needs at least one fixed face, otherwise the model can move freely")
    if study.type == "static" and not any(b["type"] in ("force", "pressure", "gravity") for b in bcs):
        raise StudyProblem("Add a load (force, pressure or gravity)")
    if study.type == "thermal" and not any(b["type"] in ("temperature", "convection") for b in bcs):
        raise StudyProblem("A thermal study needs a fixed temperature or a convection face, so heat has somewhere to go")
    if study.type == "modal" and not any(b["type"] == "fixed" for b in bcs):
        warnings.append("No fixed faces: the first six modes are rigid-body modes near 0 Hz")
    parts = []
    for pid in ids:
        p = by[pid]
        mat = M.lookup(study.materials.get(pid) or p.get("material"))
        parts.append({"id": pid, "name": p.get("name", pid), "key": p["key"], "material": mat,
                      "faces": [{"tag": f["tag"], "area": f["area"], "center": f.get("com") or f["center"]} for f in metas[pid]["faces"]]})
    bb = manifest.get("bbox")
    size = study.mesh.size
    if size is None:
        # automatic: about 25 elements across the largest dimension, at least two through thin walls is up to the user
        size = round(max(0.5, scale / 25), 2)
    return {
        "version": SIM_VERSION, "study": study.id, "name": study.name, "type": study.type, "parts": parts, "boundaries": bcs,
        "mesh": {"size": size, "order": study.mesh.order}, "modes": study.modes, "safety_target": study.safety_target,
        "bbox": bb, "warnings": warnings,
    }
