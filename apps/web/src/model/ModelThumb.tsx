// Lightweight SVG thumbnail of an assembly (painter's algorithm, flat shading).
// Used for project cards and version history, where a WebGL canvas per card would be too heavy.
import { useMemo } from 'react';
import type { Version } from '../data/types';
import { buildModel, type Primitive, type Vec3 } from './parts';

const D2R = Math.PI / 180;

function prismFaces(profile: [number, number][], map: (u: number, v: number, w: number) => Vec3, w0: number, w1: number): Vec3[][] {
  const faces: Vec3[][] = [profile.map(([u, v]) => map(u, v, w0)), profile.map(([u, v]) => map(u, v, w1))];
  for (let i = 0; i < profile.length; i++) {
    const a = profile[i], b = profile[(i + 1) % profile.length];
    faces.push([map(a[0], a[1], w0), map(b[0], b[1], w0), map(b[0], b[1], w1), map(a[0], a[1], w1)]);
  }
  return faces;
}

function facesOf(b: Primitive): Vec3[][] {
  if (b.kind === 'box') {
    const [w, h] = b.s;
    return prismFaces([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]], (u, v, z) => [b.c[0] + u, b.c[1] + v, b.c[2] + z], -b.s[2] / 2, b.s[2] / 2);
  }
  if (b.kind === 'cyl') {
    const prof: [number, number][] = [];
    for (let i = 0; i < b.n; i++) { const a = (i / b.n) * 2 * Math.PI; prof.push([Math.cos(a) * b.r, Math.sin(a) * b.r]); }
    const map = (u: number, v: number, w: number): Vec3 => {
      const p: Vec3 = b.axis === 'x' ? [w, v, u] : b.axis === 'y' ? [u, w, v] : [u, v, w];
      return [p[0] + b.c[0], p[1] + b.c[1], p[2] + b.c[2]];
    };
    return prismFaces(prof, map, -b.len / 2, b.len / 2);
  }
  return prismFaces([[0, 0], [b.L, 0], [0, b.L]], (u, v, z) => [b.x0 + u, b.y0 + v, z], b.zc - b.th / 2, b.zc + b.th / 2);
}

function hexRgb(h: string) { const x = h.replace('#', ''); return [0, 2, 4].map((i) => parseInt(x.substr(i, 2), 16)); }

export function ModelThumb({ version, yaw = -35, pitch = 22, scale = 0.8 }: { version: Version; yaw?: number; pitch?: number; scale?: number }) {
  const polys = useMemo(() => {
    const ca = Math.cos(yaw * D2R), sa = Math.sin(yaw * D2R), cb = Math.cos(pitch * D2R), sb = Math.sin(pitch * D2R);
    const rot = (p: Vec3): Vec3 => { const x1 = p[0] * ca + p[2] * sa, z1 = -p[0] * sa + p[2] * ca; return [x1, p[1] * cb - z1 * sb, p[1] * sb + z1 * cb]; };
    const out: { z: number; pts: string; fill: string }[] = [];
    for (const part of buildModel(version).parts) {
      const rgb = hexRgb(part.color);
      for (const body of part.bodies) {
        const fs = facesOf(body);
        const C = fs.flat().reduce((a, p) => [a[0] + p[0], a[1] + p[1], a[2] + p[2]], [0, 0, 0]).map((x) => x / fs.flat().length);
        for (const f of fs) {
          const u = [f[1][0] - f[0][0], f[1][1] - f[0][1], f[1][2] - f[0][2]], v = [f[2][0] - f[0][0], f[2][1] - f[0][1], f[2][2] - f[0][2]];
          let n: Vec3 = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
          const L = Math.hypot(...n) || 1; n = n.map((x) => x / L) as Vec3;
          const fc = [0, 1, 2].map((k) => f.reduce((a, p) => a + p[k], 0) / f.length);
          if ((fc[0] - C[0]) * n[0] + (fc[1] - C[1]) * n[1] + (fc[2] - C[2]) * n[2] < 0) n = n.map((x) => -x) as Vec3;
          const nr = rot(n);
          if (nr[2] <= 0.001) continue;
          const pts = f.map((p) => { const r = rot([p[0], p[1] - 70, p[2]]); return [200 + scale * r[0], 135 - scale * r[1], r[2]]; });
          const lit = Math.max(0, -0.35 * nr[0] + 0.75 * nr[1] + 0.56 * nr[2]);
          const I = 0.6 + 0.42 * lit;
          const col = rgb.map((c) => Math.round(Math.min(255, c * I)));
          out.push({ z: pts.reduce((a, p) => a + p[2], 0) / pts.length, pts: pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '), fill: `rgb(${col.join(',')})` });
        }
      }
    }
    return out.sort((a, b) => a.z - b.z);
  }, [version, yaw, pitch, scale]);

  return (
    <svg className="layer truecol" viewBox="0 0 400 250" aria-hidden="true">
      {polys.map((p, i) => <polygon key={i} points={p.pts} fill={p.fill} stroke="rgba(17,17,17,0.5)" strokeLinejoin="round" />)}
    </svg>
  );
}
