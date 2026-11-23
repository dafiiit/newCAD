"""Volume meshing with Gmsh.

build123d BREP → Gmsh (OpenCASCADE kernel) → tetrahedral mesh. Every B-rep
face is mapped back to its stable face tag, and the mesh keeps one triangle
set per tagged face (also written as Gmsh physical groups named
`<part>/<tag>`), so boundary conditions picked on faces survive remeshing.

Several parts are fragmented into one conformal mesh: where parts touch they
share nodes, which models them as bonded.

Gmsh is GPL. This module runs only inside the simulation pipeline process
(`python -m newcad_engine.sim.pipeline`), never inside the engine's API
process.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

# Gmsh second-order tetra (10 nodes) → CalculiX C3D10 / VTK order: edges 1-3 and 2-3 are swapped
GMSH_TET10_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]
TET_TYPES = {4: 4, 11: 10}   # gmsh element type → nodes
TRI_TYPES = {2: 3, 9: 6}


class MeshError(Exception):
    pass


@dataclass
class Mesh:
    nodes: np.ndarray                    # (n, 3) float64, model coordinates (mm, Z up)
    tets: np.ndarray                     # (e, 4|10) int64, 0-based node indices in CalculiX order
    tet_part: np.ndarray                 # (e,) part index of each element
    parts: list[str]                     # part ids
    faces: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)  # (part, tag) → (t, 3|6) node indices
    exterior: dict[tuple[str, str], bool] = field(default_factory=dict)     # False for faces where two parts are bonded
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def order(self) -> int:
        return 2 if self.tets.shape[1] == 10 else 1


def _match_exact(surfs: list[tuple[int, float, list[float]]], faces: list[dict[str, Any]], scale: float) -> dict[int, str]:
    """Match gmsh surfaces to tagged faces by area and centre of mass (both kernels compute the same values)."""
    out: dict[int, str] = {}
    used: set[str] = set()
    for s, area, com in surfs:
        best, best_d = None, math.inf
        for f in faces:
            if f["tag"] in used:
                continue
            d = math.dist(com, f["center"]) / scale + abs(area - f["area"]) / max(area, f["area"], 1e-9)
            if d < best_d:
                best, best_d = f["tag"], d
        if best is not None and best_d < 1e-3:
            out[s] = best
            used.add(best)
    return out


def mesh_parts(parts: list[dict[str, Any]], size: float, order: int, out_dir: Path,
               progress: Callable[[float, str], None] | None = None, threads: int | None = None) -> Mesh:
    """parts: [{"id", "brep": path, "faces": [{"tag", "area", "center"}]}]."""
    import gmsh

    say = progress or (lambda f, s: None)
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", threads or os.cpu_count() or 1)
        gmsh.model.add("study")
        occ = gmsh.model.occ
        vol_part: dict[int, int] = {}
        surf_tag: dict[int, tuple[str, str]] = {}
        all_pts = []
        for pi, p in enumerate(parts):
            dts = occ.importShapes(str(p["brep"]), highestDimOnly=True)
            occ.synchronize()
            vols = [t for d, t in dts if d == 3]
            if not vols:
                raise MeshError(f"Part {p['id']} has no solid to mesh (is it a closed solid?)")
            for v in vols:
                vol_part[v] = pi
                xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(3, v)
                all_pts += [(xmin, ymin, zmin), (xmax, ymax, zmax)]
            surfs = []
            for v in vols:
                for d, s in gmsh.model.getBoundary([(3, v)], oriented=False, combined=False):
                    surfs.append((abs(s), occ.getMass(2, abs(s)), list(occ.getCenterOfMass(2, abs(s)))))
            scale = max(1.0, max(math.dist(all_pts[-2], all_pts[-1]), 1.0))
            m = _match_exact(surfs, p["faces"], scale)
            for s, _, _ in surfs:
                if s not in m:
                    raise MeshError(f"Could not map a face of {p['id']} to its tag; rebuild the part and try again")
                surf_tag[s] = (p["id"], m[s])

        if len(vol_part) > 1:
            say(0.05, "Bonding parts")
            surf_tag, vol_part = _fragment(gmsh, vol_part, surf_tag, parts)

        # physical groups: one per part, one per tagged face
        by_face: dict[tuple[str, str], list[int]] = {}
        for s, key in surf_tag.items():
            by_face.setdefault(key, []).append(s)
        for key, ss in by_face.items():
            gmsh.model.addPhysicalGroup(2, ss, name=f"{key[0]}/{key[1]}")
        for pi, p in enumerate(parts):
            vs = [v for v, q in vol_part.items() if q == pi]
            if vs:
                gmsh.model.addPhysicalGroup(3, vs, name=p["id"])

        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 20)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10 if (threads or os.cpu_count() or 1) > 1 else 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
        gmsh.option.setNumber("Mesh.SaveAll", 0)
        say(0.1, "Meshing surfaces")
        gmsh.model.mesh.generate(2)
        say(0.2, "Meshing volume")
        gmsh.model.mesh.generate(3)
        if order == 2:
            gmsh.model.mesh.setOrder(2)
        say(0.3, "Checking mesh quality")
        mesh = _extract(gmsh, parts, vol_part, by_face)
        out_dir.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(out_dir / "mesh.msh"))
        return mesh
    finally:
        gmsh.finalize()


def _fragment(gmsh: Any, vol_part: dict[int, int], surf_tag: dict[int, tuple[str, str]], parts: list[dict[str, Any]]):
    """Fragment all volumes into one conformal model and map the new surfaces back to face tags."""
    occ = gmsh.model.occ
    copies: dict[int, tuple[str, str]] = {}
    for s, key in surf_tag.items():
        (d, c), = occ.copy([(2, s)])
        copies[c] = key
    vols = [(3, v) for v in vol_part]
    _, out_map = occ.fragment(vols, [], removeObject=True, removeTool=True)
    occ.synchronize()
    new_vol_part: dict[int, int] = {}
    for (d, v), children in zip(vols, out_map):
        for cd, cv in children:
            if cd == 3:
                new_vol_part.setdefault(cv, vol_part[v])
    part_index = {p["id"]: i for i, p in enumerate(parts)}
    new_tags: dict[int, tuple[str, str]] = {}
    pts_to_remove = []
    for v, pi in new_vol_part.items():
        for d, s in gmsh.model.getBoundary([(3, v)], oriented=False, combined=False):
            s = abs(s)
            if s in new_tags and part_index[new_tags[s][0]] == pi:
                continue
            com = occ.getCenterOfMass(2, s)
            q = gmsh.model.getClosestPoint(2, s, list(com))[0]
            pt = occ.addPoint(q[0], q[1], q[2])
            pts_to_remove.append(pt)
            best, best_d = None, math.inf
            for c, key in copies.items():
                if part_index[key[0]] != pi:
                    continue
                dist = occ.getDistance(0, pt, 2, c)[0]
                if 0 <= dist < best_d:
                    best, best_d = key, dist
            if best is None:
                raise MeshError("Could not map faces after bonding the parts")
            # an interface between two parts belongs to both; keep the first part's tag for the surface
            new_tags.setdefault(s, best)
    occ.remove([(0, p) for p in pts_to_remove])
    occ.remove([(2, c) for c in copies], recursive=True)
    occ.synchronize()
    return new_tags, new_vol_part


def _extract(gmsh: Any, parts: list[dict[str, Any]], vol_part: dict[int, int], by_face: dict[tuple[str, str], list[int]]) -> Mesh:
    tags, coords, _ = gmsh.model.mesh.getNodes()
    order = np.argsort(tags)
    tags = tags[order]
    nodes = coords.reshape(-1, 3)[order]
    lookup = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
    lookup[tags.astype(np.int64)] = np.arange(len(tags))

    tets, tet_part, tet_tags = [], [], []
    for v, pi in vol_part.items():
        types, etags, enodes = gmsh.model.mesh.getElements(3, v)
        for t, et, en in zip(types, etags, enodes):
            if t not in TET_TYPES:
                raise MeshError(f"Unexpected volume element type {t}")
            conn = lookup[en.astype(np.int64)].reshape(-1, TET_TYPES[t])
            if TET_TYPES[t] == 10:
                conn = conn[:, GMSH_TET10_TO_CCX]
            tets.append(conn)
            tet_part.append(np.full(len(conn), pi, dtype=np.int32))
            tet_tags.append(et)
    if not tets:
        raise MeshError("Meshing produced no volume elements")
    T = np.concatenate(tets)
    faces: dict[tuple[str, str], np.ndarray] = {}
    exterior: dict[tuple[str, str], bool] = {}
    for key, ss in by_face.items():
        tris = []
        ext = True
        for s in ss:
            up, _ = gmsh.model.getAdjacencies(2, s)
            if len([u for u in up if u in vol_part]) > 1:
                ext = False
            types, _, enodes = gmsh.model.mesh.getElements(2, s)
            for t, en in zip(types, enodes):
                if t in TRI_TYPES:
                    tris.append(lookup[en.astype(np.int64)].reshape(-1, TRI_TYPES[t]))
        if tris:
            faces[key] = np.concatenate(tris)
            exterior[key] = ext
    q = gmsh.model.mesh.getElementQualities(np.concatenate(tet_tags), "minSICN")
    quality = {
        "nodes": int(len(nodes)), "elements": int(len(T)), "order": 2 if T.shape[1] == 10 else 1,
        "min_quality": float(q.min()), "mean_quality": float(q.mean()),
        "poor_elements": int((q < 0.1).sum()), "inverted_elements": int((q <= 0).sum()),
    }
    if quality["inverted_elements"]:
        raise MeshError(f"The mesh has {quality['inverted_elements']} inverted elements; try a smaller mesh size")
    return Mesh(nodes=nodes, tets=T, tet_part=np.concatenate(tet_part), parts=[p["id"] for p in parts], faces=faces,
                exterior=exterior, quality=quality)
