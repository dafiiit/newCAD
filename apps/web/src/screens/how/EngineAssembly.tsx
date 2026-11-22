// The 3D model as the engine builds it: one GLB per part, with a B-rep face id per triangle.
import { Edges } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { useEffect, useMemo, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { apiBuffer } from '../../engine/client';
import { engineParts, viewBounds, type ViewPart } from '../../engine/model';
import { toView } from '../../engine/sync';
import { MODEL_Y_OFFSET, type Vec3 } from '../../model/parts';
import { useApp } from '../../state/store';

const BLUE = new THREE.Color('#1D4ED8');
const ORANGE = new THREE.Color('#D9480F');

interface Loaded { geo: THREE.BufferGeometry; faceTags: string[] }

const cache = new Map<string, Promise<Loaded>>();
const loader = new GLTFLoader();

/** Loads one part's GLB (cached by its content key; the engine never changes a key's file). */
function loadPart(url: string, key: string): Promise<Loaded> {
  let p = cache.get(key);
  if (!p) {
    p = apiBuffer(url).then((buf) => new Promise<Loaded>((resolve, reject) => {
      loader.parse(buf, '', (gltf) => {
        let geo: THREE.BufferGeometry | null = null;
        let tags: string[] = [];
        gltf.scene.updateMatrixWorld(true);
        gltf.scene.traverse((o) => {
          const m = o as THREE.Mesh;
          if (!geo && m.isMesh) {
            geo = m.geometry.clone();
            geo.applyMatrix4(m.matrixWorld);
            tags = (m.userData?.faceTags ?? m.parent?.userData?.faceTags ?? []) as string[];
          }
        });
        if (!geo) reject(new Error('GLB has no mesh'));
        else resolve({ geo, faceTags: tags });
      }, reject);
    }));
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

function faceAttr(geo: THREE.BufferGeometry) {
  return geo.getAttribute('_face_id') ?? geo.getAttribute('_FACE_ID');
}

let zebraTex: THREE.Texture | null = null;
function zebraMatcap() {
  if (zebraTex) return zebraTex;
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d')!;
  for (let i = 0; i < 16; i++) { g.fillStyle = i % 2 ? '#f6f6f3' : '#1c1c1c'; g.fillRect(0, i * 16, 256, 16); }
  zebraTex = new THREE.CanvasTexture(c);
  return zebraTex;
}

export function EngineAssembly() {
  const s = useApp();
  const parts = engineParts(s) ?? [];
  const bb = viewBounds(s);
  const center: Vec3 = [(bb.mn[0] + bb.mx[0]) / 2, (bb.mn[1] + bb.mx[1]) / 2, (bb.mn[2] + bb.mx[2]) / 2];
  const cg = s.analysis === 'cg' && s.layer === 'how' && s.eng?.manifest?.cg ? toView(s.eng.manifest.cg) : null;
  const rx = Math.max(40, (bb.mx[0] - bb.mn[0]) * 0.62), rz = Math.max(40, (bb.mx[2] - bb.mn[2]) * 0.75);
  return (
    <group position={[0, MODEL_Y_OFFSET, 0]}>
      {parts.filter((p) => p.ok && p.glb && p.key).map((p) => <GlbPart key={p.key} part={p} center={center} bb={bb} />)}
      {cg && (
        <group position={cg}>
          <mesh renderOrder={10}><sphereGeometry args={[Math.max(4, (bb.mx[0] - bb.mn[0]) / 40), 20, 12]} /><meshBasicMaterial color="#111" depthTest={false} /></mesh>
        </group>
      )}
      <mesh position={[center[0], bb.mn[1] - 0.6, center[2]]} rotation={[-Math.PI / 2, 0, 0]} scale={[rx, rz, 1]}>
        <circleGeometry args={[1, 48]} />
        <meshBasicMaterial color="#000" transparent opacity={0.06} depthWrite={false} />
      </mesh>
    </group>
  );
}

/** Explode offset of a part: away from the assembly centre. */
export function explodeOffset(p: ViewPart, center: Vec3, explode: number): Vec3 {
  const c: Vec3 = [(p.mn[0] + p.mx[0]) / 2, (p.mn[1] + p.mx[1]) / 2, (p.mn[2] + p.mx[2]) / 2];
  return [(c[0] - center[0]) * explode * 0.8, (c[1] - center[1]) * explode * 0.8, (c[2] - center[2]) * explode * 0.8];
}

function GlbPart({ part, center, bb }: { part: ViewPart; center: Vec3; bb: { mn: Vec3; mx: Vec3 } }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const selected = useApp((s) => s.selected === part.id);
  const hovered = useApp((s) => s.hovered === part.id);
  const hi = useApp((s) => !!s.anHi?.includes(part.id));
  const display = useApp((s) => s.display);
  const xray = useApp((s) => s.xray);
  const zebra = useApp((s) => s.zebra);
  const cut = useApp((s) => s.cut);
  const tool = useApp((s) => s.tool);
  const layer = useApp((s) => s.layer);
  const explode = useApp((s) => s.explode);

  useEffect(() => {
    let live = true;
    loadPart(part.glb!, part.key!).then((l) => { if (live) setLoaded(l); }).catch((e) => useApp.getState().showToast(`Could not load ${part.name}: ${e.message ?? e}`));
    return () => { live = false; };
  }, [part.glb, part.key, part.name]);

  const clip = useMemo(() => {
    if (!cut) return [];
    const ai = { x: 0, y: 2, z: 1 }[cut.ax];
    const pos = bb.mn[ai] + ((bb.mx[ai] - bb.mn[ai]) * cut.pct) / 100;
    const n = new THREE.Vector3(ai === 0 ? -1 : 0, ai === 1 ? -1 : 0, ai === 2 ? -1 : 0);
    return [new THREE.Plane(n, ai === 1 ? pos + MODEL_Y_OFFSET : pos)];
  }, [cut, bb.mn[0], bb.mx[0], bb.mn[1], bb.mx[1], bb.mn[2], bb.mx[2]]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!loaded) return null;
  const ex = explodeOffset(part, center, explode);
  const base = new THREE.Color(part.color);
  const color = selected ? base.clone().lerp(BLUE, 0.45) : hi ? base.clone().lerp(ORANGE, 0.55) : hovered ? base.clone().lerp(BLUE, 0.2) : base;
  const wire = display === 'wire';
  const edgeColor = selected ? '#1D4ED8' : wire ? '#111111' : xray ? '#59595a' : '#3a3a3a';
  const opacity = wire ? 0 : xray ? 0.28 : 1;

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (layer === 'how' && tool === 'comment') {
      const p = e.point.clone();
      p.y -= MODEL_Y_OFFSET;
      let face: string | null = null;
      const fa = faceAttr(loaded.geo);
      if (fa && e.face) face = loaded.faceTags[Math.round(fa.getX(e.face.a))] ?? null;
      useApp.getState().addPin(part.id, [p.x - ex[0], p.y - ex[1], p.z - ex[2]], { face, key: part.key ?? null });
      return;
    }
    useApp.getState().select(part.id);
  };

  return (
    <group position={ex}>
      <mesh geometry={loaded.geo} onClick={onClick}
        onPointerOver={(e) => { e.stopPropagation(); useApp.setState({ hovered: part.id }); document.body.style.cursor = tool === 'comment' ? 'cell' : 'pointer'; }}
        onPointerOut={() => { if (useApp.getState().hovered === part.id) useApp.setState({ hovered: null }); document.body.style.cursor = ''; }}>
        {zebra ? (
          <meshMatcapMaterial matcap={zebraMatcap()} clippingPlanes={clip} side={cut ? THREE.DoubleSide : THREE.FrontSide} />
        ) : (
          <meshLambertMaterial color={color} transparent={opacity < 1} opacity={opacity} depthWrite={opacity === 1} clippingPlanes={clip} side={cut ? THREE.DoubleSide : THREE.FrontSide} />
        )}
        {display !== 'shaded' && <Edges threshold={25} color={edgeColor} lineWidth={selected ? 1.6 : 1} />}
      </mesh>
    </group>
  );
}
