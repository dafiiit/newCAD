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
from .motion import model as MM
from .motion.resolve import MOTION_VERSION, MotionProblem, mechanism

KIND = {"static": "fem.static", "modal": "fem.modal", "thermal": "fem.thermal", "motion": "motion.run"}


def kind_of(study: St.Study) -> str:
    if study.type == "motion" and study.motion and study.motion.sweep:
        return "motion.sweep"
    return KIND[study.type]


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
        if kind == "motion":
            data.setdefault("motion", {})
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
        if study.type == "motion":
            return self._prepare_motion(p, study, man, metas, ref)
        try:
            inputs = St.resolve(study, man, metas)
        except St.StudyProblem as e:
            raise StoreError(str(e)) from None
        breps = {x["id"]: str(geo.entry(x["key"]) / "part.brep") for x in inputs["parts"]}
        stable = {k: v for k, v in inputs.items() if k not in ("warnings", "name")}
        key = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:32]
        return {"study": study, "inputs": inputs, "breps": breps, "key": key, "manifest": man}

    def _prepare_motion(self, p: Project, study: St.Study, man: dict[str, Any], metas: dict[str, Any], ref: str | None) -> dict[str, Any]:
        geo = self.engine.geometry
        mates = MM.mates_from(_assembly(p, ref))
        try:
            mech = mechanism(study, man, metas, mates)
        except MotionProblem as e:
            raise StoreError(str(e)) from None
        warnings = mech.pop("warnings")
        inputs = {"version": f"{St.SIM_VERSION}.{MOTION_VERSION}", "study": study.id, "name": study.name, "type": "motion",
                  "mechanism": mech, "warnings": warnings}
        breps = {b["id"]: str(geo.entry(b["key"]) / "part.brep") for b in mech["bodies"]} if mech["settings"]["contacts"] else {}
        # names and colours don't change the answer
        stable = {"version": inputs["version"], "study": study.id,
                  "mechanism": {**mech, "bodies": [{k: v for k, v in b.items() if k not in ("name", "color")} for b in mech["bodies"]],
                                "joints": [{k: v for k, v in j.items() if k != "label"} for j in mech["joints"]]}}
        key = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:32]
        return {"study": study, "inputs": inputs, "breps": breps, "key": key, "manifest": man}

    async def run(self, p: Project, sid: str, ref: str | None = None, priority: int = 0, target: str | None = None,
                  force: bool = False):
        prep = await self.prepare(p, sid, ref)
        study: St.Study = prep["study"]
        man = prep["manifest"]
        return await self.jobs.submit(kind=kind_of(study), project=p.id, study=sid, name=study.name, ref=man["ref"],
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
            out.update(status="done", summary=summary, files=files_of(key, summary.get("type", ""), self.jobs.result_dir(key)))
        if job is not None:
            out["job"] = job.to_json()
            if job.status in ("queued", "running", "failed") and summary is None:
                out["status"] = job.status
        return out


def files_of(key: str, kind: str = "", where: Any = None) -> dict[str, str]:
    names: tuple[str, ...] = ("field.glb", "result.json", "result.vtu", "mesh.msh")
    if kind == "motion":
        names = ("motion.glb", "series.json", "result.json", "model.xml", "sweep.json")
    return {f: f"/api/results/{key}/{f}" for f in names if where is None or (where / f).exists()}


def motion_text(s: dict[str, Any], head: str = "") -> str:
    lines = [f"{head}simulated {s['duration_s']:g} s in {s['steps']:,} steps with MuJoCo."]
    for m in s["mates"]:
        on = ", ".join(f"{p}: [{', '.join(f'{v:.1f}' for v in f)}] N" for p, f in m["peak_force_on"].items())
        rng = f"; moved {m['range'][0]:.1f} to {m['range'][1]:.1f} {m['range_unit']}" if m.get("range") else ""
        lines.append(f"Joint {m['id']} ({m['type']}, {' to '.join(m['parts'])}): peak load {m['peak_force_n']:.1f} N at t = {m['peak_at_s']:.3f} s"
                     + (f" (force on each part, in its own axes: {on})" if on else "") + rng + ".")
    for d in s["drivers"]:
        lines.append(f"Driver on {d['mate']} ({d['kind']} {d['value']:g} {d['unit']}): peak effort {d['peak_effort']:.3g} {d['effort_unit']}, "
                     f"RMS {d['rms_effort']:.3g} {d['effort_unit']}.")
    if s.get("peak_bearing"):
        pb = s["peak_bearing"]
        lines.append(f"Highest bearing load: {pb['force_n']:.1f} N at {pb['mate']} on {pb['part']}. "
                     f"sim_bearing_load turns it into a static stress study of {pb['part']}.")
    if s.get("sweep"):
        sw = s["sweep"]
        lines.append(f"Sweep over {sw['parameter']}, {sw['variants']} variants on {sw['backend']} ({sw['device']}):")
        for r in sw["rows"][:40]:
            if r["ok"]:
                worst = max(r["peak_force_n"].items(), key=lambda kv: kv[1]) if r["peak_force_n"] else ("-", 0.0)
                eff = ", ".join(f"{k} {v:.3g}" for k, v in r["peak_effort"].items())
                lines.append(f"  {r['value']:g}: max joint load {worst[1]:.1f} N at {worst[0]}" + (f"; effort {eff}" if eff else ""))
            else:
                lines.append(f"  {r['value']:g}: failed ({r['error']})")
    if s.get("loop_error_mm"):
        lines.append(f"Loop joints stay within {s['loop_error_mm']:.3f} mm.")
    for w in s.get("warnings", []):
        lines.append(f"Note: {w}")
    return " ".join(lines[:1]) + "\n" + "\n".join(lines[1:])


def _assembly(p: Project, ref: str | None) -> dict[str, Any]:
    return p.assembly(ref)


def summary_text(s: dict[str, Any], study_name: str = "") -> str:
    """Plain-language result summary for agents."""
    head = f"{study_name}: " if study_name else ""
    if s.get("type") == "motion":
        return motion_text(s, head)
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


class MateService:
    """Mates (joints) in assembly.yaml, edited by the Check tab and the motion_* MCP tools.

    Edits are staged on the branch like other model edits, so they belong to
    the next version of the model.
    """

    def __init__(self, engine: Any):
        self.engine = engine

    def list(self, p: Project, ref: str | None = None) -> list[MM.Mate]:
        return MM.mates_from(_assembly(p, ref))

    async def resolved(self, p: Project, ref: str | None = None) -> list[dict[str, Any]]:
        """Mates with their current centre and axis (from the picked faces), or the problem that stops them."""
        from .motion.resolve import find_face, joint_frame
        geo = self.engine.geometry
        man = await geo.build(p, ref)
        by = {x["id"]: x for x in man["parts"]}
        metas = {x["id"]: geo.meta(x["key"]) for x in man["parts"] if x["ok"]}
        coms = {pid: m.get("com") or m["center"] for pid, m in metas.items()}
        scale = 100.0
        if man.get("bbox"):
            scale = max(1.0, max(man["bbox"]["max"][k] - man["bbox"]["min"][k] for k in range(3)))
        out = []
        for m in self.list(p, ref):
            d = m.model_dump(mode="json")
            try:
                for q in m.parts:
                    if q != MM.GROUND and (q not in by or not by[q]["ok"]):
                        raise MotionProblem(f"Part {q} is missing or doesn't build")
                warns: list[str] = []
                faces = [{**find_face(f, metas, scale, m.label or m.id, warns), "part": f.part} for f in m.faces]
                d["origin_mm"], d["axis_dir"] = joint_frame(m, faces, coms)
                d["warnings"] = warns
            except MotionProblem as e:
                d["problem"] = str(e)
            out.append(d)
        return out

    def _write(self, p: Project, asm: dict[str, Any], branch: str | None) -> None:
        p.stage(branch, {"assembly.yaml": dump(asm)})

    def add(self, p: Project, data: dict[str, Any], branch: str | None = None) -> MM.Mate:
        asm = _assembly(p, branch)
        parts = {x["id"] for x in asm["parts"]}
        faces = data.get("faces") or []
        names = list(data.get("parts") or [])
        if not names:
            names = list(dict.fromkeys(f["part"] for f in faces))
            if len(names) == 1:
                names = [MM.GROUND, names[0]]
            if len(names) != 2:
                raise StoreError("Pick faces on two parts (or on one part to fix it to ground)")
        for q in names:
            if q != MM.GROUND and q not in parts:
                raise StoreError(f"No part {q!r}")
        kind = data.get("type") or "revolute"
        d = {**{k: v for k, v in data.items() if v is not None}, "parts": names, "type": kind,
             "id": data.get("id") or MM.next_mate_id(asm, kind)}
        if any(x.get("id") == d["id"] for x in asm.get("mates") or []):
            raise StoreError(f"A joint {d['id']} exists already")
        try:
            mate = MM.Mate.model_validate(d)
        except Exception as e:
            raise StoreError(f"Invalid joint: {e}") from None
        asm.setdefault("mates", []).append(mate.model_dump(mode="json", exclude_none=True))
        self._write(p, asm, branch)
        return mate

    def update(self, p: Project, mid: str, data: dict[str, Any], branch: str | None = None) -> MM.Mate:
        asm = _assembly(p, branch)
        ms = asm.get("mates") or []
        i = next((i for i, x in enumerate(ms) if x.get("id") == mid), None)
        if i is None:
            raise StoreError(f"No joint {mid!r}")
        try:
            mate = MM.Mate.model_validate({**ms[i], **{k: v for k, v in data.items() if k != "id"}, "id": mid})
        except Exception as e:
            raise StoreError(f"Invalid joint: {e}") from None
        ms[i] = mate.model_dump(mode="json", exclude_none=True)
        self._write(p, asm, branch)
        return mate

    def remove(self, p: Project, mid: str, branch: str | None = None) -> None:
        asm = _assembly(p, branch)
        ms = asm.get("mates") or []
        if not any(x.get("id") == mid for x in ms):
            raise StoreError(f"No joint {mid!r}")
        asm["mates"] = [x for x in ms if x.get("id") != mid]
        self._write(p, asm, branch)


async def bearing_load(engine: Any, p: Project, sid: str, mate: str, part: str, ref: str | None = None,
                       into: str | None = None, author: tuple[str, str] = YOU) -> St.Study:
    """Turn a motion study's peak bearing load into a static stress study of one part (Phase 4 → Phase 3 hand-off).

    The study loads the part's faces of that joint with the peak force the
    other part exerts on it, in the part's own (modelled) axes, and holds the
    part at the faces of its other joints. `into` updates an existing static
    study instead of making a new one.
    """
    sim: SimService = engine.sim
    st = await sim.state(p, sid, ref)
    if st["status"] != "done":
        raise StoreError("Run the motion study on this version first")
    s = st["summary"]
    row = next((m for m in s["mates"] if m["id"] == mate), None)
    if row is None:
        raise StoreError(f"No joint {mate!r} in the result")
    if part not in row["peak_force_on"]:
        raise StoreError(f"Joint {mate} doesn't connect {part}")
    force = row["peak_force_on"][part]
    prep = await sim.prepare(p, sid, ref)
    joints = {j["id"]: j for j in prep["inputs"]["mechanism"]["joints"]}
    geo = engine.geometry
    key = next(x["key"] for x in prep["manifest"]["parts"] if x["id"] == part)
    meta = geo.meta(key) or {"faces": []}
    sig = {f["tag"]: {k: v for k, v in f.items() if k != "tag"} for f in meta["faces"]}
    load_tags = joints[mate]["faces"].get(part) or []
    if not load_tags:
        raise StoreError(f"Joint {mate} has no faces picked on {part}. Pick its bore or pin faces so the load has somewhere to go.")
    hold = [t for j in joints.values() if j["id"] != mate for t in (j["faces"].get(part) or [])]
    motion_name = prep["study"].name
    bcs = [{"id": "force-1", "type": "force", "label": f"Peak load at {joints[mate]['label']} ({motion_name}, t = {row['peak_at_s']:.3f} s)",
            "faces": [{"part": part, "tag": t, "sig": sig.get(t)} for t in load_tags], "vector": [round(float(x), 4) for x in force]}]
    if hold:
        bcs.insert(0, {"id": "fixed-1", "type": "fixed", "label": "Other joints of the part",
                       "faces": [{"part": part, "tag": t, "sig": sig.get(t)} for t in dict.fromkeys(hold)]})
    if into:
        cur = sim.read(p, into, ref)
        if cur.type != "static":
            raise StoreError("A bearing load goes into a static stress study")
        d = cur.to_yaml_dict()
        d["boundaries"] = [b for b in d.get("boundaries", []) if not str(b.get("label", "")).startswith(f"Peak load at {joints[mate]['label']} (")]
        used = {b["id"] for b in d["boundaries"]}
        for b in bcs:
            if b["type"] == "fixed" and any(x["type"] == "fixed" for x in d["boundaries"]):
                continue
            i = 1
            while f"{b['type']}-{i}" in used:
                i += 1
            b["id"] = f"{b['type']}-{i}"
            used.add(b["id"])
            d["boundaries"].append(b)
        return sim.replace(p, into, d, None, author)
    study = sim.create(p, f"{part} under peak load at {joints[mate]['label']}", "static", None, author,
                       template={"parts": [part], "boundaries": bcs})
    return study
