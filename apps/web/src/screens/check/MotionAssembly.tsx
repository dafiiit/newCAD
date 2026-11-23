// The 3D view of a motion study: the part meshes from the model GLBs, moved by one of
//  - the MuJoCo result's animation track (motion.glb), at the playback time,
//  - live body poses while the job runs (job.frame events),
//  - the Rapier preview (grab and drag), which simulates the same bodies and joints in the browser.
// Each pose moves a part from where it was modelled (the body frames coincide with the assembly frame).
import { Edges } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { apiBuffer } from '../../engine/client';
import { engineParts, type ViewPart } from '../../engine/model';
import { toView } from '../../engine/sync';
import type { MotionMate, EngineStudy } from '../../engine/types';
import { MODEL_Y_OFFSET } from '../../model/parts';
import { useApp } from '../../state/store';
import { loadPart, type Loaded } from '../how/EngineAssembly';
import { studyView } from './EngineCheck';
import { RapierPreview, type Pose } from './rapierPreview';

/** Playback clock shared by the viewport and the panel (the store copy updates a few times a second). */
export const clock = { t: 0 };

type Track = { pos?: THREE.Interpolant; rot?: THREE.Interpolant };
interface Anim { tracks: Record<string, Track>; duration: number }
const anims = new Map<string, Promise<Anim>>();
const loader = new GLTFLoader();

function loadAnim(url: string, key: string): Promise<Anim> {
  let p = anims.get(key);
  if (!p) {
    p = apiBuffer(url).then((buf) => new Promise<Anim>((resolve, reject) => {
      loader.parse(buf, '', (gltf) => {
        const clip = gltf.animations[0];
        const tracks: Record<string, Track> = {};
        // createInterpolant is public at runtime (linear for positions, slerp for quaternions) but not in the typings
        const interp = (tr: THREE.KeyframeTrack) => (tr as unknown as { createInterpolant(): THREE.Interpolant }).createInterpolant();
        for (const tr of clip?.tracks ?? []) {
          const dot = tr.name.lastIndexOf('.');
          const node = tr.name.slice(0, dot), prop = tr.name.slice(dot + 1);
          const t = (tracks[node] ??= {});
          if (prop === 'position') t.pos = interp(tr);
          if (prop === 'quaternion') t.rot = interp(tr);
        }
        resolve({ tracks, duration: clip?.duration ?? 0 });
      }, reject);
    }));
    p.catch(() => anims.delete(key));
    anims.set(key, p);
  }
  return p;
}

const IDENTITY: Pose = [0, 0, 0, 0, 0, 0, 1];

export function MotionAssembly({ st }: { st: EngineStudy }) {
  const s = useApp();
  const parts = (engineParts(s) ?? []).filter((p) => p.ok && p.glb && p.key);
  const v = studyView(st);
  const done = v?.done;
  const live = s.motionLive && s.motionLive.study === st.id && v?.running ? s.motionLive : null;
  const [anim, setAnim] = useState<Anim | null>(null);
  const preview = useRef<RapierPreview | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const mates = s.eng?.sim?.mates ?? [];

  useEffect(() => {
    let alive = true;
    setAnim(null);
    const url = done?.files?.['motion.glb'];
    if (url && done.key) loadAnim(url, done.key).then((a) => { if (alive) setAnim(a); }).catch((e) => s.showToast(`Could not load the motion: ${e.message ?? e}`));
    return () => { alive = false; };
  }, [done?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Rapier preview: built when switched on, rebuilt when the setup changes
  const previewOn = s.motionPreview;
  const setupKey = JSON.stringify([st.motion, mates.map((m) => [m.id, m.type, m.parts, m.origin_mm, m.axis_dir])]);
  useEffect(() => {
    if (!previewOn) return;
    let alive = true;
    const p = new RapierPreview(st.id);
    p.start().then((ok) => {
      if (!alive) { p.dispose(); return; }
      if (ok) { preview.current = p; setPreviewReady(true); } else useApp.setState({ motionPreview: false });
    });
    return () => { alive = false; preview.current?.dispose(); preview.current = null; setPreviewReady(false); };
  }, [previewOn, st.id, setupKey]);

  const source = useRef<(pid: string) => Pose>(() => IDENTITY);
  const lastStore = useRef(0);
  useFrame((_, delta) => {
    const p = preview.current;
    if (previewOn && p) {
      p.step(Math.min(delta, 1 / 20));
      source.current = (pid) => p.pose(pid) ?? IDENTITY;
      return;
    }
    if (live) {
      const f = live.frame;
      source.current = (pid) => (f[pid] as Pose | undefined) ?? IDENTITY;
      return;
    }
    if (anim) {
      const st0 = useApp.getState();
      if (st0.playing && anim.duration > 0) {
        clock.t = (clock.t + delta * st0.motionSpeed) % anim.duration;
        const now = performance.now();
        if (now - lastStore.current > 100) { lastStore.current = now; useApp.setState({ motionT: clock.t }); }
      }
      const t = Math.min(clock.t, anim.duration);
      source.current = (pid) => {
        const tr = anim.tracks[pid];
        if (!tr) return IDENTITY;
        const a = tr.pos?.evaluate(t) as ArrayLike<number> | undefined;
        const b = tr.rot?.evaluate(t) as ArrayLike<number> | undefined;
        return [a?.[0] ?? 0, a?.[1] ?? 0, a?.[2] ?? 0, b?.[0] ?? 0, b?.[1] ?? 0, b?.[2] ?? 0, b?.[3] ?? 1];
      };
      return;
    }
    source.current = () => IDENTITY;
  });

  return (
    <group>
      {parts.map((p) => (
        <PosedPart key={p.key} part={p} source={source} grab={previewOn && previewReady ? preview : null}
          markers={mates.filter((m) => m.origin_mm && m.axis_dir && (m.parts[1] === p.id || (m.parts[1] === 'ground' && m.parts[0] === p.id)))} />
      ))}
      {previewOn && previewReady && <DragSpring preview={preview} />}
    </group>
  );
}

function PosedPart({ part, source, grab, markers }: { part: ViewPart; source: React.RefObject<(pid: string) => Pose>; grab: React.RefObject<RapierPreview | null> | null; markers: MotionMate[] }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const g = useRef<THREE.Group>(null);
  const selected = useApp((s) => s.selected === part.id);
  const controls = useThree((s) => s.controls) as unknown as { enabled: boolean } | null;
  useEffect(() => {
    let live = true;
    loadPart(part.glb!, part.key!).then((l) => { if (live) setLoaded(l); }).catch(() => undefined);
    return () => { live = false; };
  }, [part.glb, part.key]);
  useFrame(() => {
    const pose = source.current?.(part.id) ?? IDENTITY;
    g.current?.position.set(pose[0], pose[1], pose[2]);
    g.current?.quaternion.set(pose[3], pose[4], pose[5], pose[6]);
  });
  const color = useMemo(() => new THREE.Color(part.color).lerp(new THREE.Color('#1D4ED8'), selected ? 0.4 : 0), [part.color, selected]);
  if (!loaded) return null;
  const down = (e: ThreeEvent<PointerEvent>) => {
    if (!grab?.current) return;
    e.stopPropagation();
    const p = e.point.clone();
    p.y -= MODEL_Y_OFFSET;
    grab.current.grab(part.id, p, e.camera);
    if (controls) controls.enabled = false; // the drag moves the part, not the camera
    document.body.style.cursor = 'grabbing';
  };
  return (
    <group ref={g}>
      <mesh geometry={loaded.geo} onPointerDown={down}
        onClick={(e) => { e.stopPropagation(); if (!grab) useApp.getState().select(part.id); }}
        onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = grab ? 'grab' : 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}>
        <meshLambertMaterial color={color} />
        <Edges threshold={25} color="#3a3a3a" />
      </mesh>
      {markers.map((m) => <JointMarker key={m.id} mate={m} />)}
    </group>
  );
}

/** Green axis through a joint centre (it moves with the joint's second part). */
function JointMarker({ mate }: { mate: MotionMate }) {
  const o = toView(mate.origin_mm!);
  const a = new THREE.Vector3(...toView(mate.axis_dir!)).normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), a);
  const len = mate.type === 'fixed' ? 0 : 36;
  return (
    <group position={o} quaternion={q}>
      {len > 0 && <mesh renderOrder={5}><cylinderGeometry args={[0.9, 0.9, len, 10]} /><meshBasicMaterial color="#15803D" depthTest={false} transparent opacity={0.85} /></mesh>}
      <mesh renderOrder={5}><sphereGeometry args={[mate.type === 'ball' ? 4 : 2.6, 16, 10]} /><meshBasicMaterial color="#15803D" depthTest={false} transparent opacity={0.85} /></mesh>
    </group>
  );
}

/** While a part is grabbed: a spring pulls the grabbed point toward the pointer on a plane facing the camera. */
function DragSpring({ preview }: { preview: React.RefObject<RapierPreview | null> }) {
  const { camera, pointer, raycaster, controls } = useThree();
  const line = useRef<THREE.Line>(null);
  useEffect(() => {
    const up = () => {
      preview.current?.release();
      if (controls) (controls as unknown as { enabled: boolean }).enabled = true;
      document.body.style.cursor = '';
    };
    window.addEventListener('pointerup', up);
    return () => window.removeEventListener('pointerup', up);
  }, [preview, controls]);
  const pos = useMemo(() => new Float32Array(6), []);
  useFrame(() => {
    const p = preview.current;
    const drag = p?.dragging();
    if (line.current) line.current.visible = !!drag;
    if (!p || !drag) return;
    if (controls) (controls as unknown as { enabled: boolean }).enabled = false;
    raycaster.setFromCamera(pointer, camera);
    const hit = new THREE.Vector3();
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()).negate(),
      drag.anchorWorld.clone().add(new THREE.Vector3(0, MODEL_Y_OFFSET, 0)));
    if (raycaster.ray.intersectPlane(plane, hit)) {
      hit.y -= MODEL_Y_OFFSET;
      p.setTarget(hit);
      const a = p.grabbedPoint();
      if (a && line.current) {
        pos.set([a.x, a.y, a.z, hit.x, hit.y, hit.z]);
        const geo = line.current.geometry as THREE.BufferGeometry;
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geo.attributes.position.needsUpdate = true;
      }
    }
  });
  return (
    // @ts-expect-error three's <line> clashes with the SVG element type in JSX
    <line ref={line} renderOrder={6}>
      <bufferGeometry />
      <lineBasicMaterial color="#D9480F" depthTest={false} />
    </line>
  );
}
