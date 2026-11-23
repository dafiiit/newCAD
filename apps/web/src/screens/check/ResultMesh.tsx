// A study result drawn from the engine's field GLB. The GLB carries raw nodal values per vertex
// (_von_mises, _safety, _disp, _temp, _mode1…); the colour map, its range and the deformed shape
// are applied here in the shader, so changing them needs no engine round trip.
import type { ThreeEvent } from '@react-three/fiber';
import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { apiBuffer } from '../../engine/client';
import { COLORMAP } from '../../engine/sim';
import { toEngine } from '../../engine/sync';
import type { StudySummary } from '../../engine/types';
import { useApp } from '../../state/store';
import { useResultField } from './EngineCheck';

interface Loaded { geo: THREE.BufferGeometry; faceTags: string[] }
const cache = new Map<string, Promise<Loaded>>();
const loader = new GLTFLoader();

function loadField(url: string, key: string): Promise<Loaded> {
  let p = cache.get(key);
  if (!p) {
    p = apiBuffer(url).then((buf) => new Promise<Loaded>((resolve, reject) => {
      loader.parse(buf, '', (gltf) => {
        let out: Loaded | null = null;
        gltf.scene.traverse((o) => {
          const m = o as THREE.Mesh;
          if (!out && m.isMesh) out = { geo: m.geometry, faceTags: (m.userData?.faceTags ?? m.parent?.userData?.faceTags ?? []) as string[] };
        });
        if (out) resolve(out); else reject(new Error('Result GLB has no mesh'));
      }, reject);
    }));
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

const VERT = /* glsl */ `
attribute float scalar;
attribute vec3 disp;
uniform float scale;
varying float vS;
varying vec3 vN;
#include <clipping_planes_pars_vertex>
void main() {
  vS = scalar;
  vN = normalize(normalMatrix * normal);
  vec4 mvPosition = modelViewMatrix * vec4(position + disp * scale, 1.0);
  #include <clipping_planes_vertex>
  gl_Position = projectionMatrix * mvPosition;
}`;

const FRAG = /* glsl */ `
uniform float lo;
uniform float hi;
uniform float flip;
uniform vec3 c0; uniform vec3 c1; uniform vec3 c2; uniform vec3 c3; uniform vec3 c4;
varying float vS;
varying vec3 vN;
#include <clipping_planes_pars_fragment>
vec3 cmap(float t) {
  t = clamp(t, 0.0, 1.0) * 4.0;
  if (t < 1.0) return mix(c0, c1, t);
  if (t < 2.0) return mix(c1, c2, t - 1.0);
  if (t < 3.0) return mix(c2, c3, t - 2.0);
  return mix(c3, c4, t - 3.0);
}
void main() {
  #include <clipping_planes_fragment>
  float t = (vS - lo) / max(hi - lo, 1e-12);
  if (flip > 0.5) t = 1.0 - t;
  vec3 n = normalize(vN);
  float l = 0.62 + 0.38 * max(dot(n, normalize(vec3(-0.35, 0.75, 0.55))), 0.0) + 0.08 * max(dot(n, vec3(0.0, 0.0, 1.0)), 0.0);
  gl_FragColor = vec4(cmap(t) * min(l, 1.0), 1.0);
}`;

const colors = COLORMAP.map((c) => new THREE.Color(c));

export function ResultMesh({ url, rkey, sum }: { url: string; rkey: string; sum: StudySummary }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const { key: field, info, range } = useResultField(sum);
  const deform = useApp((s) => s.simDeform);
  const mode = useApp((s) => s.mode);
  const t0 = useRef(0);

  useEffect(() => {
    let live = true;
    loadField(url, rkey).then((l) => { if (live) setLoaded(l); }).catch((e) => useApp.getState().showToast(`Could not load the result: ${e.message ?? e}`));
    return () => { live = false; };
  }, [url, rkey]);

  const vecName = sum.type === 'modal' ? `_mode${Math.min(mode, sum.modes?.length ?? 1)}` : '_disp';
  const geo = useMemo(() => {
    if (!loaded) return null;
    const g = loaded.geo.clone();
    const n = g.getAttribute('position').count;
    const sc = field ? g.getAttribute(`_${field}`) : null;
    g.setAttribute('scalar', sc ?? new THREE.BufferAttribute(new Float32Array(n), 1));
    g.setAttribute('disp', g.getAttribute(vecName) ?? new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    return g;
  }, [loaded, field, vecName]);

  const mat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, clipping: true,
    uniforms: {
      lo: { value: 0 }, hi: { value: 1 }, scale: { value: 0 }, flip: { value: 0 },
      c0: { value: colors[0] }, c1: { value: colors[1] }, c2: { value: colors[2] }, c3: { value: colors[3] }, c4: { value: colors[4] },
    },
  }), []);
  useEffect(() => () => mat.dispose(), [mat]);

  const base = (sum.deform_scale ?? 1) * deform;
  mat.uniforms.lo.value = range?.[0] ?? 0;
  mat.uniforms.hi.value = range?.[1] ?? 1;
  mat.uniforms.flip.value = field === 'safety' ? 1 : 0; // low safety factor is the bad end: draw it red
  if (sum.type !== 'modal') mat.uniforms.scale.value = sum.type === 'thermal' ? 0 : base;

  useFrame((_, dt) => {
    if (sum.type !== 'modal') return;
    const s = useApp.getState();
    if (s.playing) t0.current += dt;
    mat.uniforms.scale.value = base * Math.sin(t0.current * 2 * Math.PI * 0.7);
  });

  if (!geo || !loaded) return null;

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (!e.face || !field || !info) return;
    const sc = geo.getAttribute('scalar');
    const pos = geo.getAttribute('position');
    const ids = [e.face.a, e.face.b, e.face.c];
    const P = ids.map((i) => new THREE.Vector3().fromBufferAttribute(pos, i));
    const bary = new THREE.Triangle(P[0], P[1], P[2]).getBarycoord(e.object.worldToLocal(e.point.clone()), new THREE.Vector3());
    const val = bary ? bary.x * sc.getX(ids[0]) + bary.y * sc.getX(ids[1]) + bary.z * sc.getX(ids[2]) : sc.getX(ids[0]);
    const fa = geo.getAttribute('_face_id');
    const tag = fa ? loaded.faceTags[Math.round(fa.getX(ids[0]))] : undefined;
    const lp = e.object.worldToLocal(e.point.clone());
    const [part, face] = tag ? tag.split('/') : [null, null];
    useApp.setState({ simProbe: { value: val, unit: info.unit, label: info.label, point: toEngine([lp.x, lp.y, lp.z]), part, face } });
  };

  return <mesh geometry={geo} material={mat} onClick={onClick} />;
}
