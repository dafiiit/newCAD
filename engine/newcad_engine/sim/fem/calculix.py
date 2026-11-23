"""CalculiX adapter: writes the input deck, runs `ccx`, reads the results.

CalculiX is GPL and is only ever started as a separate program. Units are the
consistent mm–N–s–tonne system: stress in MPa, density in t/mm³, power in
mW (N·mm/s).

Supported analyses: linear static (fixed, force, pressure, gravity), modal
(natural frequencies and mode shapes) and steady-state heat transfer (fixed
temperature, heat input, convection).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..mesh.gmsh_mesh import Mesh

# C3D10/C3D4 face numbering by corner nodes (0-based), from the CalculiX manual
TET_FACES = [(0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)]


class SolverError(Exception):
    pass


def ccx_binary() -> str | None:
    for name in (os.environ.get("NEWCAD_CCX"), "ccx", "ccx_2.22", "ccx_2.21", "ccx_2.20"):
        if name and shutil.which(name):
            return shutil.which(name)
    return None


def ccx_version(binary: str | None = None) -> str | None:
    b = binary or ccx_binary()
    if not b:
        return None
    try:
        out = subprocess.run([b, "-v"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Version\s+([\d.]+)", out)
    return m.group(1) if m else "unknown"


def _lines(values: list[int], per: int = 16) -> str:
    return "\n".join(", ".join(str(v) for v in values[i:i + per]) for i in range(0, len(values), per))


def _tri_area(nodes: np.ndarray, tris: np.ndarray) -> np.ndarray:
    a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def _face_map(mesh: Mesh) -> dict[tuple[int, int, int], tuple[int, int]]:
    """Sorted corner triple → (element number, face number) for every element face."""
    out: dict[tuple[int, int, int], tuple[int, int]] = {}
    T = mesh.tets[:, :4]
    for k, f in enumerate(TET_FACES):
        tri = np.sort(T[:, list(f)], axis=1)
        for e, row in enumerate(tri):
            out.setdefault((int(row[0]), int(row[1]), int(row[2])), (e + 1, k + 1))
    return out


def write_input(job: dict[str, Any], mesh: Mesh, path: Path) -> dict[str, Any]:
    """Write the .inp deck. Returns bookkeeping (node sets) for result post-processing."""
    kind = job["type"]
    etype = "C3D10" if mesh.order == 2 else "C3D4"
    out: list[str] = ["*HEADING", f"NewCAD study {job.get('study', '')}"]
    out.append("*NODE, NSET=NALL")
    out.append("\n".join(f"{i + 1}, {x:.9g}, {y:.9g}, {z:.9g}" for i, (x, y, z) in enumerate(mesh.nodes)))
    parts = job["parts"]
    for pi, p in enumerate(parts):
        idx = np.nonzero(mesh.tet_part == pi)[0]
        if not len(idx):
            continue
        out.append(f"*ELEMENT, TYPE={etype}, ELSET=P{pi}")
        out.append("\n".join(f"{e + 1}, " + ", ".join(str(n + 1) for n in mesh.tets[e]) for e in idx))
    out.append("*ELSET, ELSET=EALL")
    out.append("\n".join(f"P{pi}" for pi in range(len(parts)) if (mesh.tet_part == pi).any()))
    for pi, p in enumerate(parts):
        m = p["material"]
        out += [f"*MATERIAL, NAME=M{pi}", "*ELASTIC", f"{m['E']:.9g}, {m['nu']:.9g}", "*DENSITY", f"{m['density'] * 1e-12:.9g}",
                "*CONDUCTIVITY", f"{m['conductivity']:.9g}", "*EXPANSION", f"{m['expansion']:.9g}",
                "*SPECIFIC HEAT", f"{m['specific_heat'] * 1e6:.9g}"]
        if (mesh.tet_part == pi).any():
            out.append(f"*SOLID SECTION, ELSET=P{pi}, MATERIAL=M{pi}")

    fmap = None
    sets: dict[str, list[int]] = {}
    tri_sets: dict[str, np.ndarray] = {}
    for b in job["boundaries"]:
        tris = [mesh.faces[(p, t)] for p, t in b["faces"] if (p, t) in mesh.faces]
        if b["faces"] and not tris:
            raise SolverError(f"{b['label']}: its faces are not in the mesh")
        if tris:
            T = np.concatenate(tris)
            tri_sets[b["id"]] = T
            nodes = sorted(set(int(n) + 1 for n in T.reshape(-1)))
            name = f"B_{re.sub(r'[^A-Za-z0-9]', '_', b['id'])}"
            sets[b["id"]] = nodes
            out.append(f"*NSET, NSET={name}")
            out.append(_lines(nodes))

    def nset(bid: str) -> str:
        return f"B_{re.sub(r'[^A-Za-z0-9]', '_', bid)}"

    bcs = job["boundaries"]
    reaction_sets = [b["id"] for b in bcs if b["type"] == "fixed"]
    if kind == "thermal":
        amb = next((b["ambient"] for b in bcs if b["type"] == "convection"), None)
        if amb is None:
            amb = next((b["value"] for b in bcs if b["type"] == "temperature"), 20.0)
        out += ["*INITIAL CONDITIONS, TYPE=TEMPERATURE", f"NALL, {amb:.9g}"]
    out.append("*STEP")
    if kind == "static":
        out.append("*STATIC")
    elif kind == "modal":
        out += ["*FREQUENCY", f"{int(job.get('modes', 6))}"]
    else:
        out.append("*HEAT TRANSFER, STEADY STATE")

    for b in bcs:
        if b["type"] == "fixed":
            out += ["*BOUNDARY", f"{nset(b['id'])}, 1, 3, 0."]
        elif b["type"] == "temperature":
            out += ["*BOUNDARY", f"{nset(b['id'])}, 11, 11, {b['value']:.9g}"]

    # nodal loads: total force spread over the faces by area (consistent loads of 6-node triangles go to the mid-side nodes)
    cload: dict[tuple[int, int], float] = {}
    dload: list[str] = []
    dflux: list[str] = []
    film: list[str] = []
    for b in bcs:
        T = tri_sets.get(b["id"])
        if b["type"] == "force":
            areas = _tri_area(mesh.nodes, T)
            total = float(areas.sum())
            if total <= 0:
                raise SolverError(f"{b['label']}: faces have no area")
            F = np.asarray(b["vector"], dtype=float)
            share = areas / total
            cols = [3, 4, 5] if T.shape[1] == 6 else [0, 1, 2]
            for t, s in zip(T, share):
                for c in cols:
                    n = int(t[c]) + 1
                    for d in range(3):
                        if F[d]:
                            cload[(n, d + 1)] = cload.get((n, d + 1), 0.0) + F[d] * s / 3
        elif b["type"] in ("pressure", "heat_flux", "convection"):
            if fmap is None:
                fmap = _face_map(mesh)
            if b["type"] == "heat_flux":
                q = float(b["value"]) * 1000.0 / max(float(_tri_area(mesh.nodes, T).sum()), 1e-12)  # W total → mW/mm²
            for t in T:
                key = tuple(sorted(int(x) for x in t[:3]))
                hit = fmap.get(key)  # type: ignore[arg-type]
                if hit is None:
                    continue
                e, f = hit
                if b["type"] == "pressure":
                    dload.append(f"{e}, P{f}, {b['value']:.9g}")
                elif b["type"] == "heat_flux":
                    dflux.append(f"{e}, S{f}, {q:.9g}")
                else:
                    film.append(f"{e}, F{f}, {b['ambient']:.9g}, {float(b['value']) * 1e-3:.9g}")
        elif b["type"] == "gravity":
            g = np.asarray(b["vector"], dtype=float) * 1000.0  # m/s² → mm/s²
            mag = float(np.linalg.norm(g))
            if mag > 0:
                d = g / mag
                dload.append(f"EALL, GRAV, {mag:.9g}, {d[0]:.9g}, {d[1]:.9g}, {d[2]:.9g}")
    if cload:
        out.append("*CLOAD")
        out.append("\n".join(f"{n}, {d}, {v:.9g}" for (n, d), v in sorted(cload.items())))
    if dload:
        out += ["*DLOAD", "\n".join(dload)]
    if dflux:
        out += ["*DFLUX", "\n".join(dflux)]
    if film:
        out += ["*FILM", "\n".join(film)]

    if kind == "thermal":
        out += ["*NODE FILE", "NT"]
    else:
        out += ["*NODE FILE", "U"]
    if kind == "static":
        out += ["*EL FILE", "S"]
        for bid in reaction_sets:
            out += [f"*NODE PRINT, NSET={nset(bid)}, TOTALS=ONLY", "RF"]
    out.append("*END STEP")
    path.write_text("\n".join(out) + "\n")
    return {"sets": sets, "reaction_sets": reaction_sets}


def run(work: Path, name: str, threads: int, timeout_s: float, log: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None) -> float:
    """Run ccx on work/name.inp. Returns wall time in seconds."""
    b = ccx_binary()
    if not b:
        raise SolverError("CalculiX (ccx) is not installed on this compute target")
    env = {**os.environ, "OMP_NUM_THREADS": str(threads), "CCX_NPROC_EQUATION_SOLVER": str(threads),
           "CCX_NPROC_STIFFNESS": str(threads), "CCX_NPROC_RESULTS": str(threads)}
    t0 = time.perf_counter()
    with open(work / "ccx.log", "w") as lf:
        # same process group as the pipeline, so cancelling the pipeline stops the solver too
        proc = subprocess.Popen([b, "-i", name], cwd=work, stdout=lf, stderr=subprocess.STDOUT, env=env)
        try:
            while proc.poll() is None:
                if cancelled and cancelled():
                    proc.kill()
                    raise SolverError("cancelled")
                if time.perf_counter() - t0 > timeout_s:
                    proc.kill()
                    raise SolverError(f"CalculiX took longer than {timeout_s:.0f} s and was stopped")
                time.sleep(0.1)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    text = (work / "ccx.log").read_text(errors="replace")
    if log:
        log(text[-4000:])
    errs = [ln.strip() for ln in text.splitlines() if "*ERROR" in ln]
    if errs or proc.returncode != 0 or not (work / f"{name}.frd").exists():
        why = errs[0] if errs else f"exit code {proc.returncode}"
        if "singular" in text.lower() or "zero pivot" in text.lower():
            why = "the model can move freely (add or check fixed faces) or parts are not connected"
        raise SolverError(f"CalculiX failed: {why}")
    return time.perf_counter() - t0


def read_frd(path: Path, n_nodes: int) -> list[dict[str, Any]]:
    """Nodal result blocks of a .frd file: [{"name", "step", "value", "data": (n_nodes, ncomp)}]."""
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    value = 0.0
    step = 0
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("  100C"):
                try:
                    value = float(line[12:24])
                except ValueError:
                    value = 0.0
                try:
                    step = int(line[58:63])
                except ValueError:
                    step += 1
                cur = None
            elif line.startswith(" -4") and cur is None:
                parts = line.split()
                name, ncomp = parts[1], int(parts[2])
                cur = {"name": name, "step": step, "value": value, "ncomp": ncomp,
                       "data": np.zeros((n_nodes, min(ncomp, 6)))}
                blocks.append(cur)
            elif line.startswith(" -1") and cur is not None:
                node = int(line[3:13])
                body = line[13:].rstrip("\n")
                vals = [float(body[i:i + 12]) for i in range(0, len(body), 12) if body[i:i + 12].strip()]
                if 0 < node <= n_nodes:
                    k = min(len(vals), cur["data"].shape[1])
                    cur["data"][node - 1, :k] = vals[:k]
            elif line.startswith(" -3"):
                cur = None
    return blocks


def read_frequencies(dat: Path) -> list[float]:
    text = dat.read_text(errors="replace")
    i = text.find("E I G E N V A L U E   O U T P U T")
    if i < 0:
        return []
    freqs = []
    for line in text[i:].splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit():
            try:
                freqs.append(float(parts[3]))
            except ValueError:
                pass
        elif freqs and not line.strip():
            break
        elif freqs and parts and not parts[0].isdigit():
            break
    return freqs


def read_reactions(dat: Path) -> list[list[float]]:
    """Total reaction force per fixed set (TOTALS=ONLY prints one line each)."""
    out = []
    lines = dat.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if "total force" in line.lower():
            for nxt in lines[i + 1:i + 4]:
                vals = nxt.split()
                if len(vals) >= 3:
                    try:
                        out.append([float(v) for v in vals[:3]])
                        break
                    except ValueError:
                        continue
    return out


def von_mises(s: np.ndarray) -> np.ndarray:
    """s: (n, 6) as SXX SYY SZZ SXY SYZ SZX."""
    xx, yy, zz, xy, yz, zx = (s[:, i] for i in range(6))
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (xy ** 2 + yz ** 2 + zx ** 2))
