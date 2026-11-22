// Stub assembly for the "Generator mount" project.
// Mirrors the build123d source shown in the Code tab. Once the engine exists,
// geometry arrives as GLB with per-triangle face IDs and this file goes away.
import type { Version } from '../data/types';

export type Vec3 = [number, number, number];
export type Axis = 'x' | 'y' | 'z';

export type Primitive =
  | { kind: 'box'; c: Vec3; s: Vec3 }
  | { kind: 'cyl'; c: Vec3; r: number; len: number; axis: Axis; n: number }
  /** Right-triangle prism: legs L along +x and +y from (x0, y0), extruded along z around zc. */
  | { kind: 'tri'; x0: number; y0: number; L: number; zc: number; th: number };

export interface Part {
  id: string;
  name: string;
  color: string;
  bodies: Primitive[];
  /** Explode direction, scaled by the explode slider. */
  ex: Vec3;
}

export interface Model {
  ver: Version;
  cf: { t: number; t2: number; g: null | 'gusset' | 'rib' };
  parts: Part[];
}

const D2R = Math.PI / 180;

export const CFG: Record<Version, Model['cf']> = {
  1: { t: 10, t2: 10, g: null },
  2: { t: 10, t2: 10, g: 'gusset' },
  3: { t: 6, t2: 7, g: 'rib' },
};

/** The model is drawn with its base lowered by this much so the camera target sits near the middle. */
export const MODEL_Y_OFFSET = -70;

const cache = new Map<Version, Model>();

export function buildModel(ver: Version): Model {
  const hit = cache.get(ver);
  if (hit) return hit;
  const cf = CFG[ver];
  const { t, t2 } = cf;
  const parts: Part[] = [];
  const add = (id: string, name: string, color: string, bodies: Primitive[], ex: Vec3) => parts.push({ id, name, color, bodies, ex });
  const box = (c: Vec3, s: Vec3): Primitive => ({ kind: 'box', c, s });
  const cyl = (c: Vec3, r: number, len: number, axis: Axis, n: number): Primitive => ({ kind: 'cyl', c, r, len, axis, n });
  const tri = (x0: number, y0: number, L: number, zc: number, th: number): Primitive => ({ kind: 'tri', x0, y0, L, zc, th });

  add('plate', 'Base plate', '#C7CCD4', [box([0, t / 2, 0], [220, t, 140])], [0, -1, 0]);
  const xi = -110 + t2;
  add('upright', 'Upright', '#B4C2D6', [box([-110 + t2 / 2, t + 75, 0], [t2, 150, 140])], [-1, 0.2, 0]);
  if (cf.g === 'gusset') add('gusset', 'Gussets (2×)', '#A9B9D0', [tri(xi, t, 90, -62, 8), tri(xi, t, 90, 62, 8)], [-0.4, 0.6, 0]);
  if (cf.g === 'rib') add('gusset', 'Ribs (2×)', '#A9B9D0', [tri(xi, t, 62, -64, 5), tri(xi, t, 62, 64, 5)], [-0.4, 0.6, 0]);
  const gy = t + 85;
  const flange: Primitive[] = [cyl([xi + 4, gy, 0], 58, 8, 'x', 22)];
  for (const a of [45, 135, 225, 315]) flange.push(cyl([xi + 11, gy + Math.sin(a * D2R) * 52, Math.cos(a * D2R) * 52], 5, 6, 'x', 6));
  add('flange', 'Generator flange', '#8C95A1', flange, [0.6, 0, 0]);
  add('gen', 'Generator', '#41464F', [cyl([xi + 68, gy, 0], 46, 120, 'x', 22)], [1.1, 0, 0]);
  add('shaft', 'Shaft', '#D2A93B', [cyl([xi + 158, gy, 0], 9, 60, 'x', 12)], [1.8, 0, 0]);
  const hub: Primitive[] = [cyl([xi + 198, gy, 0], 20, 20, 'x', 16)];
  for (const a of [90, 210, 330]) hub.push(cyl([xi + 210, gy + Math.sin(a * D2R) * 12, Math.cos(a * D2R) * 12], 3.2, 4, 'x', 6));
  add('hub', 'Coupling hub', '#9AA3AE', hub, [2.4, 0, 0]);
  const bolts: Primitive[] = [];
  for (const sx of [-85, 85]) for (const sz of [-55, 55]) bolts.push(cyl([sx, t + 3, sz], 7, 6, 'y', 6));
  add('bolts', 'Base bolts (4×)', '#6E7580', bolts, [0, 0.8, 0]);

  const model: Model = { ver, cf, parts };
  cache.set(ver, model);
  return model;
}

/** Axis of the generator, shaft and hub (they spin about +x through this point). */
export function rotorAxis(model: Model): { y: number; z: number } {
  return { y: model.cf.t + 85, z: 0 };
}

// ---------- mass properties (exact for prisms) ----------

export const DENSITY: Record<string, number> = {
  plate: 7.85e-6, upright: 7.85e-6, gusset: 7.85e-6, bolts: 7.85e-6, flange: 2.7e-6, shaft: 8.0e-6, hub: 8.0e-6,
};
export const MATERIAL: Record<string, string> = {
  plate: 'Steel', upright: 'Steel', gusset: 'Steel', bolts: 'Steel', flange: 'Aluminium', shaft: 'Stainless', hub: 'Stainless', gen: 'Bought-in (4 kg)',
};

function volumeAndCentroid(b: Primitive): { V: number; c: Vec3 } {
  if (b.kind === 'box') return { V: b.s[0] * b.s[1] * b.s[2], c: b.c };
  if (b.kind === 'cyl') {
    const area = 0.5 * b.n * b.r * b.r * Math.sin((2 * Math.PI) / b.n);
    return { V: area * b.len, c: b.c };
  }
  return { V: ((b.L * b.L) / 2) * b.th, c: [b.x0 + b.L / 3, b.y0 + b.L / 3, b.zc] };
}

export interface MassProps {
  parts: { id: string; name: string; mass: number; c: Vec3 }[];
  total: number;
  cg: Vec3;
  bracket: number;
}

export function massProps(model: Model): MassProps {
  const out: MassProps['parts'] = [];
  let M = 0, bracket = 0;
  const C: Vec3 = [0, 0, 0];
  for (const part of model.parts) {
    let V = 0;
    const cv: Vec3 = [0, 0, 0];
    for (const b of part.bodies) {
      const r = volumeAndCentroid(b);
      V += r.V;
      for (let k = 0; k < 3; k++) cv[k] += r.V * r.c[k];
    }
    const c = cv.map((x) => x / V) as Vec3;
    const mass = part.id === 'gen' ? 4.0 : V * (DENSITY[part.id] ?? 7.85e-6);
    out.push({ id: part.id, name: part.name, mass, c });
    M += mass;
    for (let k = 0; k < 3; k++) C[k] += mass * c[k];
    if (part.id === 'plate' || part.id === 'upright' || part.id === 'gusset') bracket += mass;
  }
  return { parts: out, total: M, cg: C.map((x) => x / M) as Vec3, bracket };
}

// ---------- bounds and interference ----------

export interface Box3 { mn: Vec3; mx: Vec3 }

export function bodyBounds(b: Primitive): Box3 {
  if (b.kind === 'box') {
    return { mn: [0, 1, 2].map((k) => b.c[k] - b.s[k] / 2) as Vec3, mx: [0, 1, 2].map((k) => b.c[k] + b.s[k] / 2) as Vec3 };
  }
  if (b.kind === 'cyl') {
    const ax = { x: 0, y: 1, z: 2 }[b.axis];
    const half = [0, 1, 2].map((k) => (k === ax ? b.len / 2 : b.r));
    return { mn: [0, 1, 2].map((k) => b.c[k] - half[k]) as Vec3, mx: [0, 1, 2].map((k) => b.c[k] + half[k]) as Vec3 };
  }
  return { mn: [b.x0, b.y0, b.zc - b.th / 2], mx: [b.x0 + b.L, b.y0 + b.L, b.zc + b.th / 2] };
}

export function modelBounds(model: Model): Box3 {
  const mn: Vec3 = [Infinity, Infinity, Infinity], mx: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of model.parts) for (const b of p.bodies) {
    const bb = bodyBounds(b);
    for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], bb.mn[k]); mx[k] = Math.max(mx[k], bb.mx[k]); }
  }
  return { mn, mx };
}

/** Overlap depth of two bodies, or -1 when they are apart. 0 means touching. */
function overlap(a: Primitive, b: Primitive): number {
  const A = bodyBounds(a), B = bodyBounds(b);
  const ov = [0, 1, 2].map((k) => Math.min(A.mx[k], B.mx[k]) - Math.max(A.mn[k], B.mn[k]));
  if (!ov.every((x) => x > -0.5)) return -1;
  // two parallel cylinders: compare the radial distance, not the boxes
  if (a.kind === 'cyl' && b.kind === 'cyl' && a.axis === b.axis) {
    const ax = { x: 0, y: 1, z: 2 }[a.axis];
    const d = Math.hypot(...[0, 1, 2].filter((k) => k !== ax).map((k) => a.c[k] - b.c[k]));
    const radial = a.r + b.r - d;
    if (radial < 0.5) return radial > -0.5 ? 0 : -1;
    return Math.min(ov[ax], radial);
  }
  const depth = Math.min(ov[0], ov[1], ov[2]);
  return depth > 0.5 ? depth : 0;
}

export interface Interference {
  hits: { a: string; b: string; name: string; depth: number }[];
  contacts: { a: string; b: string; name: string }[];
  bodies: number;
  pairs: number;
}

export function interference(model: Model): Interference {
  const P = model.parts;
  const hits: Interference['hits'] = [], contacts: Interference['contacts'] = [];
  for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
    let clash = 0, touch = false;
    for (const A of P[i].bodies) for (const B of P[j].bodies) {
      const d = overlap(A, B);
      if (d < 0) continue;
      touch = true;
      clash = Math.max(clash, d);
    }
    const name = `${P[i].name} ⇄ ${P[j].name}`;
    if (clash > 0) hits.push({ a: P[i].id, b: P[j].id, name, depth: clash });
    else if (touch) contacts.push({ a: P[i].id, b: P[j].id, name });
  }
  const bodies = P.reduce((n, p) => n + p.bodies.length, 0);
  return { hits, contacts, bodies, pairs: (P.length * (P.length - 1)) / 2 };
}

// ---------- mock result fields ----------

const STRESS_K: Record<string, number> = { upright: 1, plate: 0.85, gusset: 0.8, flange: 0.35, gen: 0.1, shaft: 0.22, hub: 0.08, bolts: 0.3 };
const STRESS_M: Record<Version, number> = { 1: 1, 2: 0.5, 3: 0.72 };

/** Normalised mock von Mises stress at a point, peaking at the upright root. */
export function stressAt(model: Model, partId: string, p: Vec3): number {
  const R = [-110 + model.cf.t2, model.cf.t];
  const d = Math.hypot(p[0] - R[0], p[1] - R[1]);
  return Math.max(0, Math.min(1, (STRESS_K[partId] ?? 0.2) * STRESS_M[model.ver] * Math.exp(-d / 110) * 1.2));
}

const HEAT: [number, [number, number, number]][] = [
  [0, [43, 89, 195]], [0.35, [34, 166, 179]], [0.55, [123, 192, 67]], [0.78, [242, 194, 48]], [1, [226, 70, 47]],
];

/** Same colormap as the legend gradient, returns 0..1 RGB. */
export function heat(t: number): [number, number, number] {
  for (let i = 1; i < HEAT.length; i++) {
    if (t <= HEAT[i][0]) {
      const [t0, a] = HEAT[i - 1], [t1, b] = HEAT[i];
      const u = (t - t0) / (t1 - t0);
      return [0, 1, 2].map((k) => (a[k] + (b[k] - a[k]) * u) / 255) as [number, number, number];
    }
  }
  return HEAT[HEAT.length - 1][1].map((x) => x / 255) as [number, number, number];
}
