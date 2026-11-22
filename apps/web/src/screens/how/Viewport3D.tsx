// 3D view for How? and Check, built with react-three-fiber.
// Geometry is the stub assembly from model/parts.ts; the engine will stream GLB instead.
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Edges, OrbitControls, OrthographicCamera } from '@react-three/drei';
import { useEffect, useMemo, useRef, type ComponentRef, type ReactNode } from 'react';
import * as THREE from 'three';
import { bodyBounds, buildModel, heat, massProps, modelBounds, MODEL_Y_OFFSET, rotorAxis, stressAt, type Model, type Part, type Primitive, type Vec3 } from '../../model/parts';
import { useApp, type CameraView } from '../../state/store';

const BLUE = new THREE.Color('#1D4ED8');
const ORANGE = new THREE.Color('#D9480F');
const D2R = Math.PI / 180;

const VIEWS: Record<CameraView, { az: number; el: number }> = {
  iso: { az: 35, el: 22 },
  front: { az: 0, el: 0 },
  top: { az: 0, el: 89.9 },
  side: { az: 90, el: 0 },
};

/** Results that colour the model: which field, and is it animated. */
function resultMode(study: string, done: boolean) {
  if (!done) return null;
  if (study === 'static' || study === 'thermal' || study === 'cfd' || study === 'soft' || study === 'vibration') return 'field' as const;
  if (study === 'modal') return 'modal' as const;
  if (study === 'motion') return 'motion' as const;
  return null;
}

// ---------- screen-space labels ----------
// DOM labels (pins, CG, hover tag) live outside the canvas; a projector inside the canvas
// moves them every frame. This keeps them crisp and avoids mounting DOM inside the R3F tree.
const anchors = new Map<string, { p: THREE.Vector3; el: HTMLElement | null }>();

function ScreenTag({ id, at, children }: { id: string; at: Vec3; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    anchors.set(id, { p: new THREE.Vector3(at[0], at[1] + MODEL_Y_OFFSET, at[2]), el: ref.current });
    return () => { anchors.delete(id); };
  }, [id, at[0], at[1], at[2]]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={ref} className="screentag" style={{ position: 'absolute', left: 0, top: 0, visibility: 'hidden', zIndex: 8, pointerEvents: 'none' }}>{children}</div>;
}

function Projector() {
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, size }) => {
    anchors.forEach((a) => {
      if (!a.el) return;
      v.copy(a.p).project(camera);
      a.el.style.transform = `translate(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px)`;
      a.el.style.visibility = 'visible';
    });
  });
  return null;
}

function Labels() {
  const version = useApp((s) => s.version);
  const layer = useApp((s) => s.layer);
  const pins = useApp((s) => s.pins);
  const openPin = useApp((s) => s.openPin);
  const showResolved = useApp((s) => s.showResolved);
  const explode = useApp((s) => s.explode);
  const analysis = useApp((s) => s.analysis);
  const hovered = useApp((s) => s.hovered);
  const selected = useApp((s) => s.selected);
  const model = buildModel(version);
  const exOf = (id: string) => (model.parts.find((x) => x.id === id)?.ex ?? [0, 0, 0]).map((k) => k * explode * 70);
  const mp = analysis === 'cg' && layer === 'how' ? massProps(model) : null;
  const hov = hovered ? model.parts.find((p) => p.id === hovered) : undefined;
  const hovAt: Vec3 | null = hov ? (() => { const b = bodyBoundsOfPart(hov); return [(b.mn[0] + b.mx[0]) / 2, b.mx[1], (b.mn[2] + b.mx[2]) / 2]; })() : null;

  return (
    <>
      {layer === 'how' && pins.filter((p) => showResolved || !p.resolved).map((p) => {
        const ex = exOf(p.part);
        const n = pins.indexOf(p) + 1;
        return (
          <ScreenTag key={p.id} id={`pin-${p.id}`} at={[p.p[0] + ex[0], p.p[1] + ex[1], p.p[2] + ex[2]]}>
            <button className={`mpin${openPin === p.id ? ' on' : ''}${p.resolved ? ' resolved' : ''}`} style={{ position: 'static', margin: '-30px 0 0 -4px', pointerEvents: 'auto' }}
              aria-label={`Comment ${n}`} onClick={() => useApp.setState({ openPin: openPin === p.id ? null : p.id })}>{n}</button>
          </ScreenTag>
        );
      })}
      {mp && <ScreenTag id="cg" at={[mp.cg[0], mp.cg[1] + 24, mp.cg[2]]}><span className="mlabel" style={{ position: 'static', display: 'inline-block', transform: 'translate(-50%, -50%)' }}>CG</span></ScreenTag>}
      {hov && hovAt && hov.id !== selected && (
        <ScreenTag id={`hov-${hov.id}-${explode}`} at={[hovAt[0] + exOf(hov.id)[0], hovAt[1] + exOf(hov.id)[1], hovAt[2] + exOf(hov.id)[2]]}>
          <span className="hovtag" style={{ position: 'static', display: 'inline-block', transform: 'translate(-50%, -140%)' }}>{hov.name}</span>
        </ScreenTag>
      )}
      {selected && (() => {
        const p = model.parts.find((x) => x.id === selected);
        if (!p) return null;
        const b = bodyBoundsOfPart(p), ex = exOf(p.id);
        return (
          <ScreenTag id={`sel-${p.id}-${explode}`} at={[(b.mn[0] + b.mx[0]) / 2 + ex[0], b.mx[1] + ex[1], (b.mn[2] + b.mx[2]) / 2 + ex[2]]}>
            <span className="hovtag seltag" style={{ position: 'static', transform: 'translate(-50%, -140%)' }}>{p.name}</span>
          </ScreenTag>
        );
      })()}
    </>
  );
}

function bodyBoundsOfPart(part: Part) {
  const mn: Vec3 = [Infinity, Infinity, Infinity], mx: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const b of part.bodies) { const bb = bodyBounds(b); for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], bb.mn[k]); mx[k] = Math.max(mx[k], bb.mx[k]); } }
  return { mn, mx };
}

export function Viewport3D() {
  const settings = useApp((s) => s.settings);
  return (
    <div className="viewport">
      <div className="stage3d truecol" role="img" aria-label="3D view of the selected concept. Drag to orbit, scroll to zoom.">
        <Canvas gl={{ antialias: true, localClippingEnabled: true }} dpr={[1, 2]} onPointerMissed={() => useApp.setState({ selected: null })}>
          <color attach="background" args={['#ffffff']} />
          <CameraRig orbit={Number(settings.orbit)} />
          <ambientLight intensity={1.6} />
          <directionalLight position={[-300, 700, 500]} intensity={1.6} />
          <directionalLight position={[400, 200, -300]} intensity={0.35} />
          {settings.grid ? <gridHelper args={[600, 24, '#d6d6d1', '#ecece8']} position={[0, MODEL_Y_OFFSET - 0.5, 0]} /> : null}
          <Assembly />
          <Projector />
        </Canvas>
        <Labels />
      </div>
    </div>
  );
}

function CameraRig({ orbit }: { orbit: number }) {
  const camera = useApp((s) => s.camera);
  const size = useThree((s) => s.size);
  const cam = useRef<THREE.OrthographicCamera>(null);
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  const fit = Math.min(size.width / 640, size.height / 460);

  useEffect(() => {
    const c = cam.current;
    if (!c) return;
    const { az, el } = VIEWS[camera.view];
    const D = 1200;
    c.position.set(D * Math.cos(el * D2R) * Math.sin(az * D2R), D * Math.sin(el * D2R), D * Math.cos(el * D2R) * Math.cos(az * D2R));
    c.zoom = fit;
    c.lookAt(0, 0, 0);
    c.updateProjectionMatrix();
    controls.current?.target.set(0, 0, 0);
    controls.current?.update();
    // only on an explicit view change, not on every resize
  }, [camera.nonce]);

  return (
    <>
      <OrthographicCamera makeDefault ref={cam} position={[688, 450, 983]} zoom={fit} near={-5000} far={5000} />
      <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.15} rotateSpeed={orbit * 2.5} minZoom={0.3} maxZoom={12} />
    </>
  );
}

function Assembly() {
  const version = useApp((s) => s.version);
  const layer = useApp((s) => s.layer);
  const study = useApp((s) => s.study);
  const done = useApp((s) => !!s.studyDone[`${s.study}:${s.version}`]);
  const analysis = useApp((s) => s.analysis);
  const explode = useApp((s) => s.explode);
  const model = buildModel(version);
  const mode = layer === 'check' ? resultMode(study, done) : null;
  const group = useRef<THREE.Group>(null);
  const t0 = useRef(0);

  // modal: wobble the bracket in the selected mode shape (exaggerated)
  useFrame((_, dt) => {
    const s = useApp.getState();
    if (!group.current) return;
    if (mode === 'modal' && s.playing) {
      t0.current += dt;
      const a = Math.sin(t0.current * 2 * Math.PI * 0.8) * 0.035;
      group.current.rotation.set(s.mode === 2 ? a : 0, s.mode === 3 ? a : 0, s.mode === 1 ? -a : 0);
    } else group.current.rotation.set(0, 0, 0);
  });

  const mp = analysis === 'cg' && layer !== 'check' ? massProps(model) : null;

  return (
    <group position={[0, MODEL_Y_OFFSET, 0]}>
      <group ref={group}>
        {model.parts.map((p) => <PartMesh key={`${version}:${p.id}`} model={model} part={p} result={mode} explode={explode} />)}
      </group>
      {mp && (
        <group position={mp.cg}>
          <mesh renderOrder={10}><sphereGeometry args={[7, 20, 12]} /><meshBasicMaterial color="#111" depthTest={false} /></mesh>
        </group>
      )}
      <ModelShadow model={model} />
    </group>
  );
}

function ModelShadow({ model }: { model: Model }) {
  const bb = modelBounds(model);
  const cx = (bb.mn[0] + bb.mx[0]) / 2, cz = (bb.mn[2] + bb.mx[2]) / 2;
  const rx = (bb.mx[0] - bb.mn[0]) * 0.62, rz = (bb.mx[2] - bb.mn[2]) * 0.75;
  return (
    <mesh position={[cx, -0.6, cz]} rotation={[-Math.PI / 2, 0, 0]} scale={[rx, rz, 1]}>
      <circleGeometry args={[1, 48]} />
      <meshBasicMaterial color="#000" transparent opacity={0.06} depthWrite={false} />
    </mesh>
  );
}

function geometryOf(b: Primitive): { geo: THREE.BufferGeometry; pos: Vec3; rot: Vec3 } {
  if (b.kind === 'box') return { geo: new THREE.BoxGeometry(b.s[0], b.s[1], b.s[2]), pos: b.c, rot: [0, 0, 0] };
  if (b.kind === 'cyl') {
    const geo = new THREE.CylinderGeometry(b.r, b.r, b.len, b.n, 1);
    const rot: Vec3 = b.axis === 'x' ? [0, 0, -Math.PI / 2] : b.axis === 'z' ? [Math.PI / 2, 0, 0] : [0, 0, 0];
    return { geo, pos: b.c, rot };
  }
  const shape = new THREE.Shape();
  shape.moveTo(0, 0); shape.lineTo(b.L, 0); shape.lineTo(0, b.L); shape.closePath();
  return { geo: new THREE.ExtrudeGeometry(shape, { depth: b.th, bevelEnabled: false }), pos: [b.x0, b.y0, b.zc - b.th / 2], rot: [0, 0, 0] };
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

function PartMesh({ model, part, result, explode }: { model: Model; part: Part; result: 'field' | 'modal' | 'motion' | null; explode: number }) {
  const selected = useApp((s) => s.selected === part.id);
  const hovered = useApp((s) => s.hovered === part.id);
  const hi = useApp((s) => !!s.anHi?.includes(part.id));
  const display = useApp((s) => s.display);
  const xray = useApp((s) => s.xray);
  const zebra = useApp((s) => s.zebra);
  const cut = useApp((s) => s.cut);
  const tool = useApp((s) => s.tool);
  const layer = useApp((s) => s.layer);
  const spinRef = useRef<THREE.Group>(null);
  const axis = rotorAxis(model);
  const spins = result === 'motion' && (part.id === 'shaft' || part.id === 'hub' || part.id === 'gen');

  useFrame((_, dt) => {
    if (!spinRef.current) return;
    const s = useApp.getState();
    if (spins && s.playing && part.id !== 'gen') spinRef.current.rotation.x += dt * (s.rpm / 60) * 2 * Math.PI * 0.1;
    if (!spins) spinRef.current.rotation.x = 0;
  });

  const bodies = useMemo(() => part.bodies.map((b) => {
    const g = geometryOf(b);
    // per-vertex result colours, in world coordinates of the unexploded model
    const m = new THREE.Matrix4().compose(new THREE.Vector3(...g.pos), new THREE.Quaternion().setFromEuler(new THREE.Euler(...g.rot)), new THREE.Vector3(1, 1, 1));
    const P = g.geo.getAttribute('position');
    const colors = new Float32Array(P.count * 3);
    const v = new THREE.Vector3();
    const bb = modelBounds(model);
    for (let i = 0; i < P.count; i++) {
      v.fromBufferAttribute(P, i).applyMatrix4(m);
      const t = result === 'modal' ? Math.max(0, Math.min(1, (v.y - bb.mn[1]) / (bb.mx[1] - bb.mn[1]))) : stressAt(model, part.id, [v.x, v.y, v.z]);
      const c = heat(t);
      colors.set(c, i * 3);
    }
    g.geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return g;
  }), [part, model, result]);

  useEffect(() => () => bodies.forEach((b) => b.geo.dispose()), [bodies]);

  const clip = useMemo(() => {
    if (!cut) return [];
    const bb = modelBounds(model);
    const ai = { x: 0, y: 2, z: 1 }[cut.ax];
    const pos = bb.mn[ai] + ((bb.mx[ai] - bb.mn[ai]) * cut.pct) / 100;
    const n = new THREE.Vector3(ai === 0 ? -1 : 0, ai === 1 ? -1 : 0, ai === 2 ? -1 : 0);
    // planes live in world space; the model group is lowered by MODEL_Y_OFFSET
    return [new THREE.Plane(n, ai === 1 ? pos + MODEL_Y_OFFSET : pos)];
  }, [cut, model]);

  const base = new THREE.Color(part.color);
  const color = selected ? base.clone().lerp(BLUE, 0.45) : hi ? base.clone().lerp(ORANGE, 0.55) : hovered ? base.clone().lerp(BLUE, 0.2) : base;
  const useField = !!result && !zebra;
  const wire = display === 'wire';
  const edgeColor = selected ? '#1D4ED8' : wire ? '#111111' : xray ? '#59595a' : '#3a3a3a';
  const opacity = wire ? 0 : xray ? 0.28 : 1;
  const ex: Vec3 = part.ex.map((k) => k * explode * 70) as Vec3;

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (layer === 'how' && tool === 'comment') {
      const p = e.point.clone();
      p.y -= MODEL_Y_OFFSET;
      useApp.getState().addPin(part.id, [p.x - ex[0], p.y - ex[1], p.z - ex[2]]);
      return;
    }
    useApp.getState().select(part.id);
  };

  return (
    <group position={ex}>
      <group ref={spinRef} position={[0, axis.y, axis.z]}>
        <group position={[0, -axis.y, -axis.z]}>
          {bodies.map((b, i) => (
            <mesh key={i} geometry={b.geo} position={b.pos} rotation={b.rot}
              onClick={onClick}
              onPointerOver={(e) => { e.stopPropagation(); useApp.setState({ hovered: part.id }); document.body.style.cursor = tool === 'comment' ? 'cell' : 'pointer'; }}
              onPointerOut={() => { if (useApp.getState().hovered === part.id) useApp.setState({ hovered: null }); document.body.style.cursor = ''; }}>
              {zebra ? (
                <meshMatcapMaterial matcap={zebraMatcap()} clippingPlanes={clip} side={cut ? THREE.DoubleSide : THREE.FrontSide} />
              ) : (
                <meshLambertMaterial key={useField ? 'field' : 'plain'} color={useField ? '#ffffff' : color} vertexColors={useField} flatShading transparent={opacity < 1} opacity={opacity}
                  depthWrite={opacity === 1} clippingPlanes={clip} side={cut ? THREE.DoubleSide : THREE.FrontSide} />
              )}
              {display !== 'shaded' && <Edges threshold={20} color={edgeColor} lineWidth={selected ? 1.6 : 1} clippingPlanes={clip} />}
            </mesh>
          ))}
        </group>
      </group>
    </group>
  );
}
