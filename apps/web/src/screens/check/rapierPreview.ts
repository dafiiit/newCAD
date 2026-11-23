// Rapier "grab and drag" preview of a motion study, run in the browser.
//
// The same bodies (mass, centre of mass, inertia from the engine) and joints as the MuJoCo
// model, without contacts. Drivers become joint motors, springs become spring motors, and a
// grabbed part is pulled toward the pointer by a soft spring. This is preview physics: it is
// for feeling how the mechanism moves. The numbers in the Check tab always come from MuJoCo.
//
// World: Y-up, metres (the viewport's axes scaled from mm). Poses come out in viewport mm, as
// the transform from where a part was modelled, like the MuJoCo animation track.
import type RAPIER_NS from '@dimforge/rapier3d-compat';
import * as THREE from 'three';
import { loadMechanism } from '../../engine/sim';
import type { Mechanism } from '../../engine/types';

type R = typeof RAPIER_NS;
type V3 = [number, number, number];
/** translation (mm), quaternion xyzw */
export type Pose = [number, number, number, number, number, number, number];

let rapier: Promise<R> | null = null;
function loadRapier(): Promise<R> {
  rapier ??= import('@dimforge/rapier3d-compat').then(async (m) => {
    const R = (m.default ?? m) as R;
    await R.init();
    return R;
  });
  rapier.catch(() => { rapier = null; });
  return rapier;
}

/** Engine (Z-up) → view (Y-up). */
const view = (p: V3): V3 => [p[0], p[2], -p[1]];
const C = new THREE.Matrix3().set(1, 0, 0, 0, 0, 1, 0, -1, 0);

/** Eigen decomposition of a symmetric 3×3 (Jacobi): principal values and the frame whose columns are the axes. */
export function principal(I: number[][]): { values: V3; frame: THREE.Quaternion } {
  const a = I.map((r) => [...r]);
  const v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let sweep = 0; sweep < 30; sweep++) {
    const off = Math.abs(a[0][1]) + Math.abs(a[0][2]) + Math.abs(a[1][2]);
    if (off < 1e-14 * (Math.abs(a[0][0]) + Math.abs(a[1][1]) + Math.abs(a[2][2]) + 1e-30)) break;
    for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) {
      if (Math.abs(a[p][q]) < 1e-300) continue;
      const th = (a[q][q] - a[p][p]) / (2 * a[p][q]);
      const t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < 3; k++) {
        const akp = a[k][p], akq = a[k][q];
        a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < 3; k++) {
        const apk = a[p][k], aqk = a[q][k];
        a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < 3; k++) {
        const vkp = v[k][p], vkq = v[k][q];
        v[k][p] = c * vkp - s * vkq; v[k][q] = s * vkp + c * vkq;
      }
    }
  }
  const m = new THREE.Matrix4().set(v[0][0], v[0][1], v[0][2], 0, v[1][0], v[1][1], v[1][2], 0, v[2][0], v[2][1], v[2][2], 0, 0, 0, 0, 1);
  if (m.determinant() < 0) { for (let k = 0; k < 3; k++) v[k][2] *= -1; m.set(v[0][0], v[0][1], v[0][2], 0, v[1][0], v[1][1], v[1][2], 0, v[2][0], v[2][1], v[2][2], 0, 0, 0, 0, 1); }
  return { values: [Math.max(a[0][0], 1e-12), Math.max(a[1][1], 1e-12), Math.max(a[2][2], 1e-12)], frame: new THREE.Quaternion().setFromRotationMatrix(m) };
}

interface Body { id: string; rb: RAPIER_NS.RigidBody; com0: THREE.Vector3; mass: number }
interface Driven {
  joint: RAPIER_NS.ImpulseJoint; kind: 'speed' | 'torque' | 'position'; value: number; ramp: number;
  b1: RAPIER_NS.RigidBody; b2: RAPIER_NS.RigidBody; axis: THREE.Vector3; linear: boolean;
}

export class RapierPreview {
  private world: RAPIER_NS.World | null = null;
  private bodies = new Map<string, Body>();
  private driven: Driven[] = [];
  private t = 0;
  private grabbed: { body: Body; local: THREE.Vector3; target: THREE.Vector3 } | null = null;
  private disposed = false;

  constructor(private study: string) {}

  /** Builds the world from the engine's mechanism; false if Rapier or the mechanism could not load. */
  async start(): Promise<boolean> {
    let R: R, mech: Mechanism | null;
    try {
      [R, mech] = await Promise.all([loadRapier(), loadMechanism(this.study)]);
    } catch {
      return false;
    }
    if (!mech || this.disposed) return false;
    this.build(R, mech);
    return true;
  }

  private build(R: R, mech: Mechanism) {
    const g = view(mech.settings.gravity);
    const world = new R.World({ x: g[0], y: g[1], z: g[2] });
    world.timestep = 1 / 240;
    const ground = world.createRigidBody(R.RigidBodyDesc.fixed());
    const rb: Record<string, RAPIER_NS.RigidBody> = { ground };
    const pos: Record<string, THREE.Vector3> = { ground: new THREE.Vector3() };
    const Cm = new THREE.Matrix4().setFromMatrix3(C);
    for (const b of mech.bodies) {
      const c = new THREE.Vector3(...view(b.com)).multiplyScalar(1e-3);
      // inertia about the centre of mass, engine axes kg·mm² → view axes kg·m²
      const I = new THREE.Matrix4().set(
        b.inertia_kgmm2[0][0], b.inertia_kgmm2[0][1], b.inertia_kgmm2[0][2], 0,
        b.inertia_kgmm2[1][0], b.inertia_kgmm2[1][1], b.inertia_kgmm2[1][2], 0,
        b.inertia_kgmm2[2][0], b.inertia_kgmm2[2][1], b.inertia_kgmm2[2][2], 0, 0, 0, 0, 1);
      const Iv = Cm.clone().multiply(I).multiply(Cm.clone().transpose()).elements; // column-major
      const { values, frame } = principal([[Iv[0], Iv[4], Iv[8]], [Iv[1], Iv[5], Iv[9]], [Iv[2], Iv[6], Iv[10]]].map((r) => r.map((x) => x * 1e-6)));
      const mass = Math.max(b.mass_kg, 1e-6);
      const desc = R.RigidBodyDesc.dynamic()
        .setTranslation(c.x, c.y, c.z)
        .setAdditionalMassProperties(mass, { x: 0, y: 0, z: 0 }, { x: values[0], y: values[1], z: values[2] }, { x: frame.x, y: frame.y, z: frame.z, w: frame.w })
        .setAngularDamping(0.05).setLinearDamping(0.02).setCanSleep(false);
      const body = world.createRigidBody(desc);
      rb[b.id] = body;
      pos[b.id] = c;
      this.bodies.set(b.id, { id: b.id, rb: body, com0: c.clone(), mass });
    }
    const springs = Object.fromEntries(mech.springs.map((s) => [s.mate, s]));
    const drivers = Object.fromEntries(mech.drivers.map((d) => [d.mate, d]));
    for (const j of mech.joints) {
      const [p1, p2] = j.parts;
      if (!rb[p1] || !rb[p2]) continue;
      const o = new THREE.Vector3(...view(j.origin)).multiplyScalar(1e-3);
      const a1 = o.clone().sub(pos[p1]), a2 = o.clone().sub(pos[p2]);
      const ax = new THREE.Vector3(...view(j.axis)).normalize();
      const v = (x: THREE.Vector3) => ({ x: x.x, y: x.y, z: x.z });
      let data: RAPIER_NS.JointData;
      if (j.type === 'revolute') data = R.JointData.revolute(v(a1), v(a2), v(ax));
      else if (j.type === 'prismatic') data = R.JointData.prismatic(v(a1), v(a2), v(ax));
      else if (j.type === 'ball') data = R.JointData.spherical(v(a1), v(a2));
      else data = R.JointData.fixed(v(a1), { x: 0, y: 0, z: 0, w: 1 }, v(a2), { x: 0, y: 0, z: 0, w: 1 });
      const joint = world.createImpulseJoint(data, rb[p1], rb[p2], true);
      joint.setContactsEnabled(false);
      if (j.type !== 'revolute' && j.type !== 'prismatic') continue;
      const unit = joint as RAPIER_NS.UnitImpulseJoint;
      if (j.limits_si) unit.setLimits(j.limits_si[0], j.limits_si[1]);
      const d = drivers[j.id];
      const sp = springs[j.id];
      if (d) {
        this.driven.push({ joint, kind: d.kind, value: d.value_si, ramp: Math.max(d.ramp, 1e-3), b1: rb[p1], b2: rb[p2], axis: ax, linear: j.type === 'prismatic' });
      } else if (sp && (sp.stiffness_si > 0 || sp.damping_si > 0)) {
        unit.configureMotorModel(R.MotorModel.ForceBased);
        unit.configureMotorPosition(sp.rest_si, sp.stiffness_si, sp.damping_si);
      }
    }
    this.world = world;
  }

  /** Advance by a frame's time, in fixed sub-steps. */
  step(dt: number) {
    const w = this.world;
    if (!w) return;
    const n = Math.max(1, Math.min(16, Math.round(dt / w.timestep)));
    for (let i = 0; i < n; i++) {
      this.t += w.timestep;
      for (const d of this.driven) this.drive(d, w.timestep);
      this.pull(w.timestep);
      w.step();
    }
  }

  private drive(d: Driven, h: number) {
    const s = Math.min(this.t / d.ramp, 1);
    const unit = d.joint as RAPIER_NS.UnitImpulseJoint;
    if (d.kind === 'speed') unit.configureMotorVelocity(d.value * s, 60);
    else if (d.kind === 'position') {
      const e = s * s * s * (10 - 15 * s + 6 * s * s); // minimum jerk, as in the MuJoCo run
      unit.configureMotorPosition(d.value * e, 1600, 80);
    } else {
      const f = d.axis.clone().multiplyScalar(d.value * h);
      if (d.linear) {
        d.b2.applyImpulse({ x: f.x, y: f.y, z: f.z }, true);
        d.b1.applyImpulse({ x: -f.x, y: -f.y, z: -f.z }, true);
      } else {
        d.b2.applyTorqueImpulse({ x: f.x, y: f.y, z: f.z }, true);
        d.b1.applyTorqueImpulse({ x: -f.x, y: -f.y, z: -f.z }, true);
      }
    }
  }

  /** The drag spring: critically damped, scaled by the grabbed part's mass. */
  private pull(h: number) {
    const g = this.grabbed;
    if (!g) return;
    const k = 400, c = 2 * Math.sqrt(k);
    const p = this.worldPoint(g.body, g.local);
    const lv = g.body.rb.linvel(), av = g.body.rb.angvel(), t = g.body.rb.translation();
    const r = p.clone().sub(new THREE.Vector3(t.x, t.y, t.z));
    const vel = new THREE.Vector3(lv.x, lv.y, lv.z).add(new THREE.Vector3(av.x, av.y, av.z).cross(r));
    const f = g.target.clone().sub(p).multiplyScalar(k).sub(vel.multiplyScalar(c)).multiplyScalar(g.body.mass * h);
    g.body.rb.applyImpulseAtPoint({ x: f.x, y: f.y, z: f.z }, { x: p.x, y: p.y, z: p.z }, true);
  }

  private worldPoint(b: Body, local: THREE.Vector3) {
    const t = b.rb.translation(), q = b.rb.rotation();
    return local.clone().applyQuaternion(new THREE.Quaternion(q.x, q.y, q.z, q.w)).add(new THREE.Vector3(t.x, t.y, t.z));
  }

  /** The part's pose: from where it was modelled to where it is now (viewport mm, xyzw). */
  pose(pid: string): Pose | null {
    const b = this.bodies.get(pid);
    if (!b) return null;
    const t = b.rb.translation(), q = b.rb.rotation();
    const rq = new THREE.Quaternion(q.x, q.y, q.z, q.w);
    const tr = new THREE.Vector3(t.x, t.y, t.z).sub(b.com0.clone().applyQuaternion(rq)).multiplyScalar(1000);
    return [tr.x, tr.y, tr.z, q.x, q.y, q.z, q.w];
  }

  /** Grab a part at a point (viewport mm, without the model's display offset). */
  grab(pid: string, pointMm: THREE.Vector3, _camera?: THREE.Camera) {
    const b = this.bodies.get(pid);
    if (!b) return;
    const p = pointMm.clone().multiplyScalar(1e-3);
    const t = b.rb.translation(), q = b.rb.rotation();
    const local = p.clone().sub(new THREE.Vector3(t.x, t.y, t.z)).applyQuaternion(new THREE.Quaternion(q.x, q.y, q.z, q.w).invert());
    this.grabbed = { body: b, local, target: p };
  }

  setTarget(pointMm: THREE.Vector3) {
    if (this.grabbed) this.grabbed.target.copy(pointMm).multiplyScalar(1e-3);
  }

  release() { this.grabbed = null; }

  /** The grabbed point now (viewport mm), or null. */
  grabbedPoint(): THREE.Vector3 | null {
    const g = this.grabbed;
    return g ? this.worldPoint(g.body, g.local).multiplyScalar(1000) : null;
  }

  dragging(): { anchorWorld: THREE.Vector3 } | null {
    const p = this.grabbedPoint();
    return p ? { anchorWorld: p } : null;
  }

  dispose() {
    this.disposed = true;
    this.grabbed = null;
    this.world?.free();
    this.world = null;
    this.bodies.clear();
    this.driven = [];
  }
}
