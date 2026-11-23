// Helpers that let the screens read parts from the engine's build manifest
// and fall back to the stub assembly when there is no engine.
import { buildModel, modelBounds, type Vec3 } from '../model/parts';
import type { AppState } from '../state/store';
import type { ManifestPart } from './types';

export interface ViewPart {
  id: string;
  name: string;
  color: string;
  material: string;
  ok: boolean;
  mass_kg?: number;
  error?: string;
  line?: number | null;
  file: string;
  glb?: string;
  key?: string;
  /** bounds in viewer coordinates (Y up, mm) */
  mn: Vec3;
  mx: Vec3;
}

type S = Pick<AppState, 'eng' | 'version'>;

function viewBox(b: ManifestPart['bbox']): { mn: Vec3; mx: Vec3 } {
  if (!b) return { mn: [0, 0, 0], mx: [0, 0, 0] };
  const [x0, y0, z0] = b.min, [x1, y1, z1] = b.max;
  return { mn: [x0, z0, -y1], mx: [x1, z1, -y0] };
}

/** Parts of the checked-out version from the engine, or null in mock mode / before the first build. */
export function engineParts(s: S): ViewPart[] | null {
  const man = s.eng?.manifest;
  if (!man) return null;
  return man.parts.map((p) => ({
    id: p.id, name: p.name || p.id, color: p.color || '#B4C2D6', material: p.material || '', ok: p.ok, mass_kg: p.mass_kg,
    error: p.error, line: p.line, file: p.file, glb: p.glb, key: p.key, ...viewBox(p.bbox),
  }));
}

export function partNameOf(s: S, id: string | null): string | undefined {
  if (!id) return undefined;
  const ep = engineParts(s);
  if (ep) return ep.find((p) => p.id === id)?.name;
  return buildModel(s.version).parts.find((p) => p.id === id)?.name;
}

export function viewBounds(s: S): { mn: Vec3; mx: Vec3 } {
  const ep = engineParts(s)?.filter((p) => p.ok);
  if (!ep) return modelBounds(buildModel(s.version));
  if (!ep.length) return { mn: [-50, 0, -50], mx: [50, 50, 50] };
  const mn: Vec3 = [Infinity, Infinity, Infinity], mx: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of ep) for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], p.mn[k]); mx[k] = Math.max(mx[k], p.mx[k]); }
  return { mn, mx };
}

/** Pairs of parts whose bounding boxes overlap: a quick first pass until the engine's exact clash check is wired here. */
export function boxOverlaps(parts: ViewPart[]): { a: string; b: string; name: string; depth: number }[] {
  const out: { a: string; b: string; name: string; depth: number }[] = [];
  for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
    const A = parts[i], B = parts[j];
    let depth = Infinity;
    for (let k = 0; k < 3; k++) depth = Math.min(depth, Math.min(A.mx[k], B.mx[k]) - Math.max(A.mn[k], B.mn[k]));
    if (depth > 0.01) out.push({ a: A.id, b: B.id, name: `${A.name} ↔ ${B.name}`, depth });
  }
  return out;
}
