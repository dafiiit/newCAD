"""Analytic FEM validation cases, run through the real engine (build123d → Gmsh → CalculiX).

Each case builds a part, sets up a study the same way the Check tab and the
sim_* tools do (face tags picked by geometry), solves it, and compares one
number with a closed-form reference.

    cd engine && uv run --extra dev python ../validation/report.py      # table
    cd engine && uv run --extra dev pytest ../validation                 # gate
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any, Callable

from newcad_engine.project.store import YOU

E_STEEL, NU_STEEL, RHO_STEEL, K_STEEL = 210_000.0, 0.30, 7850e-12, 50.0  # MPa, -, t/mm³, W/(m·K)


@dataclass
class Result:
    case: str
    quantity: str
    fem: float
    reference: float
    tolerance: float
    detail: str = ""

    @property
    def error(self) -> float:
        return (self.fem - self.reference) / self.reference

    @property
    def ok(self) -> bool:
        return abs(self.error) <= self.tolerance


def _face(faces: list[dict[str, Any]], pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    hits = [f for f in faces if pred(f)]
    if len(hits) != 1:
        raise AssertionError(f"expected one face, found {len(hits)}")
    return hits[0]


def _ref(part: str, f: dict[str, Any]) -> dict[str, Any]:
    return {"part": part, "tag": f["tag"], "sig": {k: v for k, v in f.items() if k != "tag"}}


def _normal(axis: int, sign: int) -> Callable[[dict[str, Any]], bool]:
    return lambda f: bool(f.get("normal")) and f["normal"][axis] * sign > 0.999


async def _project(engine, name: str, code: str, material: str = "Steel"):
    p = engine.store.create(name)
    p.commit("main", name, YOU, changes={"parts/body.py": code,
                                         "assembly.yaml": f"parts:\n- id: body\n  file: parts/body.py\n  material: {material}\n"})
    man = await engine.geometry.build(p)
    assert man["ok"], man
    return p, engine.geometry.meta(man["parts"][0]["key"])["faces"]


async def _solve(engine, p, name: str, kind: str, boundaries: list[dict[str, Any]], size: float, **extra: Any) -> dict[str, Any]:
    st = engine.sim.create(p, name, kind, None)
    engine.sim.replace(p, st.id, {**st.to_yaml_dict(), "mesh": {"size": size, "order": 2}, "boundaries": boundaries, **extra}, None)
    job = await engine.sim.run(p, st.id)
    while job.status in ("queued", "running"):
        await asyncio.sleep(0.1)
    if job.status != "done":
        raise AssertionError(f"{name}: {job.status} {job.error}")
    return job.summary


BEAM_L, BEAM_B, BEAM_H, BEAM_F = 200.0, 20.0, 20.0, 1000.0
BEAM = f"""from build123d import *
result = Box({BEAM_L}, {BEAM_B}, {BEAM_H}, align=(Align.MIN, Align.CENTER, Align.CENTER))
"""


async def cantilever(engine, sizes: tuple[float, ...] = (10.0, 5.0, 3.0)) -> list[Result]:
    """Tip load on a clamped square beam. Reference: Timoshenko beam (bending + shear), L/h = 10."""
    p, faces = await _project(engine, "Cantilever", BEAM)
    root, tip = _face(faces, _normal(0, -1)), _face(faces, _normal(0, 1))
    I = BEAM_B * BEAM_H**3 / 12
    G = E_STEEL / (2 * (1 + NU_STEEL))
    kappa = 10 * (1 + NU_STEEL) / (12 + 11 * NU_STEEL)  # Cowper's shear coefficient for a rectangle
    bending = BEAM_F * BEAM_L**3 / (3 * E_STEEL * I)
    shear = BEAM_F * BEAM_L / (kappa * G * BEAM_B * BEAM_H)
    out = []
    for size in sizes:
        s = await _solve(engine, p, f"Tip load {size}", "static", [
            {"id": "fixed-1", "type": "fixed", "faces": [_ref("body", root)]},
            {"id": "force-1", "type": "force", "faces": [_ref("body", tip)], "vector": [0, 0, -BEAM_F]},
        ], size)
        out.append(Result("Cantilever tip deflection", f"mesh {size:g} mm", s["max_displacement_mm"], bending + shear, 0.02,
                          f"{s['mesh']['elements']:,} C3D10 elements; Euler–Bernoulli alone {bending:.4f} mm"))
    return out


async def cantilever_frequency(engine, size: float = 5.0) -> list[Result]:
    """First bending frequency of the clamped beam. Reference: Euler–Bernoulli, β₁L = 1.8751."""
    p, faces = await _project(engine, "Cantilever modes", BEAM)
    root = _face(faces, _normal(0, -1))
    s = await _solve(engine, p, "Modes", "modal", [{"id": "fixed-1", "type": "fixed", "faces": [_ref("body", root)]}], size, modes=2)
    I, A = BEAM_B * BEAM_H**3 / 12, BEAM_B * BEAM_H
    f1 = 1.875104**2 / (2 * math.pi) * math.sqrt(E_STEEL * I / (RHO_STEEL * A * BEAM_L**4))
    return [Result("Cantilever first bending mode", "frequency (Hz)", s["frequencies_hz"][0], f1, 0.02,
                   f"{s['mesh']['elements']:,} elements; shear and rotary inertia lower it slightly")]


PLATE_W, PLATE_L, PLATE_T, HOLE_D, SIGMA = 100.0, 300.0, 5.0, 20.0, 10.0
PLATE = f"""from build123d import *
with BuildPart() as p:
    Box({PLATE_L}, {PLATE_W}, {PLATE_T}, align=(Align.CENTER, Align.CENTER, Align.MIN))
    Cylinder({HOLE_D / 2}, {PLATE_T}, align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
result = p.part
"""


async def plate_with_hole(engine, size: float = 4.0) -> list[Result]:
    """Plate in tension with a central hole. Reference: Peterson/Pilkey Kt for a finite-width plate (d/W = 0.2)."""
    p, faces = await _project(engine, "Plate with hole", PLATE)
    left, right = _face(faces, _normal(0, -1)), _face(faces, _normal(0, 1))
    s = await _solve(engine, p, "Tension", "static", [
        {"id": "fixed-1", "type": "fixed", "faces": [_ref("body", left)]},
        {"id": "pressure-1", "type": "pressure", "faces": [_ref("body", right)], "value": -SIGMA},  # negative pressure pulls
    ], size)
    r = HOLE_D / PLATE_W
    kt_net = 3.0 - 3.14 * r + 3.667 * r**2 - 1.527 * r**3
    peak = kt_net * SIGMA * PLATE_W / (PLATE_W - HOLE_D)
    return [Result("Plate with hole, peak stress", "von Mises at the hole (MPa)", s["max_von_mises_mpa"], peak, 0.05,
                   f"Kt(net) = {kt_net:.3f}; {s['mesh']['elements']:,} elements; peak at face {s['max_von_mises_at']['face']}")]


async def conduction_bar(engine, size: float = 5.0) -> list[Result]:
    """Heat into one end of a bar, the other end held at 20 °C. Reference: 1D conduction, ΔT = P·L/(k·A)."""
    p, faces = await _project(engine, "Conduction bar", BEAM)
    root, tip = _face(faces, _normal(0, -1)), _face(faces, _normal(0, 1))
    P = 10.0
    s = await _solve(engine, p, "Heat", "thermal", [
        {"id": "temperature-1", "type": "temperature", "faces": [_ref("body", root)], "value": 20.0},
        {"id": "heat_flux-1", "type": "heat_flux", "faces": [_ref("body", tip)], "value": P},
    ], size)
    dT = P * (BEAM_L / 1000) / (K_STEEL * (BEAM_B * BEAM_H) * 1e-6)
    return [Result("Conduction bar", "hot-end temperature (°C)", s["max_temperature_c"], 20.0 + dT, 0.01)]


CASES = {"cantilever": cantilever, "cantilever_frequency": cantilever_frequency, "plate_with_hole": plate_with_hole,
         "conduction_bar": conduction_bar}
