// Check tab against the engine: studies (studies/<id>.yaml), jobs on compute targets, results.
//
// Studies load with their run state for the checked-out version. Job progress arrives as
// `job.update` events; when a job ends the studies reload so the result shows up.
import { useApp } from '../state/store';
import { api, EngineError } from './client';
import type { BoundaryType, EngineJob, EngineStudy, EngineTarget, Material, SimState, StudyBoundary, StudyType } from './types';
import type { EngineEvent } from './client';

const get = () => useApp.getState();
const pid = () => get().eng?.pid ?? null;
const P = (path = '') => `/api/projects/${encodeURIComponent(pid() ?? '')}${path}`;

export const emptySim = (): SimState => ({ studies: [], jobs: {}, targets: null, materials: [], loaded: false });

function patchSim(patch: Partial<SimState> | ((s: SimState) => Partial<SimState>)) {
  const e = get().eng;
  if (!e) return;
  const sim = e.sim ?? emptySim();
  const p = typeof patch === 'function' ? patch(sim) : patch;
  useApp.setState({ eng: { ...e, sim: { ...sim, ...p } } });
}

function msg(e: unknown) {
  return e instanceof EngineError ? e.message : e instanceof Error ? e.message : String(e);
}
function toast(e: unknown, prefix = '') {
  const m = `${prefix}${msg(e)}`;
  get().showToast(m.length > 160 ? `${m.slice(0, 158)}…` : m);
}

// ---------- loading ----------

let seq = 0;
export async function loadStudies() {
  if (!pid()) return;
  const n = ++seq;
  const [studies, materials] = await Promise.all([
    api<EngineStudy[]>(P('/studies')),
    get().eng?.sim?.materials.length ? Promise.resolve(get().eng!.sim.materials) : api<Material[]>('/api/materials'),
  ]);
  if (n !== seq) return;
  const jobs = { ...(get().eng?.sim?.jobs ?? {}) };
  for (const st of studies) if (st.state?.job) jobs[st.state.job.id] = st.state.job;
  patchSim({ studies, materials, jobs, loaded: true });
  const s = get();
  if (!s.simSel || !studies.some((x) => x.id === s.simSel)) useApp.setState({ simSel: studies[0]?.id ?? null });
}

let timer: ReturnType<typeof setTimeout> | null = null;
export function scheduleStudies(delay = 300) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => { timer = null; loadStudies().catch(() => undefined); }, delay);
}

export async function loadTargets() {
  try { patchSim({ targets: await api<EngineTarget[]>('/api/targets') }); } catch (e) { toast(e, 'Compute targets: '); }
}

/** Handles sim events from the socket. Returns true when the event was one of ours. */
export function onSimEvent(ev: EngineEvent): boolean {
  if (ev.type === 'job.update') {
    const job = ev.job as EngineJob;
    if (job.project !== pid()) return true;
    const prev = get().eng?.sim?.jobs[job.id];
    patchSim((s) => ({ jobs: { ...s.jobs, [job.id]: job } }));
    if (job.status !== 'queued' && job.status !== 'running' && prev?.status !== job.status) {
      scheduleStudies(100);
      if (job.status === 'done' && !job.cached) get().showToast(`${job.name} finished on ${targetName(job.target)}`);
      if (job.status === 'failed') get().showToast(`${job.name} failed: ${job.error ?? 'unknown error'}`);
    }
    return true;
  }
  if (ev.type === 'targets.changed') { void loadTargets(); return true; }
  return false;
}

export function targetName(id: string | null | undefined) {
  if (!id) return 'this computer';
  return get().eng?.sim?.targets?.find((t) => t.id === id)?.name ?? (id === 'local' ? 'this computer' : id);
}

/** The latest job of a study for its current setup (from events, newer than the loaded state). */
export function studyJob(st: EngineStudy): EngineJob | undefined {
  const jobs = Object.values(get().eng?.sim?.jobs ?? {}).filter((j) => j.study === st.id && (!st.state?.key || j.key === st.state.key));
  return jobs.sort((a, b) => b.created - a.created)[0] ?? st.state?.job;
}

// ---------- editing ----------

function replaceStudy(st: EngineStudy) {
  patchSim((s) => ({ studies: s.studies.map((x) => (x.id === st.id ? st : x)) }));
}

export async function createStudy(type: StudyType) {
  const names: Record<StudyType, string> = { static: 'Static stress', modal: 'Natural frequencies', thermal: 'Heat transfer' };
  const taken = new Set(get().eng?.sim?.studies.map((s) => s.name));
  let name = names[type];
  for (let i = 2; taken.has(name); i++) name = `${names[type]} ${i}`;
  try {
    const st = await api<EngineStudy>(P('/studies'), { body: { name, type } });
    useApp.setState({ simSel: st.id });
    await loadStudies();
  } catch (e) { toast(e, 'Could not create the study: '); }
}

export async function deleteStudy(id: string) {
  try { await api(P(`/studies/${id}`), { method: 'DELETE' }); await loadStudies(); } catch (e) { toast(e); }
}

export async function patchStudy(id: string, patch: Partial<Pick<EngineStudy, 'name' | 'materials' | 'modes' | 'safety_target' | 'target'>> & { mesh?: { size?: number | null } }) {
  try { replaceStudy(await api<EngineStudy>(P(`/studies/${id}`), { method: 'PATCH', body: patch })); } catch (e) { toast(e); }
}

export async function addBoundary(id: string, b: { type: BoundaryType; label: string; faces: { part: string; tag: string; key: string | null }[]; vector?: number[]; value?: number | null; ambient?: number | null }) {
  try {
    const body = { ...b, value: b.value ?? undefined, ambient: b.ambient ?? undefined };
    replaceStudy(await api<EngineStudy>(P(`/studies/${id}/boundaries`), { body }));
    return true;
  } catch (e) { toast(e, 'Could not add it: '); return false; }
}

export async function removeBoundary(id: string, bid: string) {
  try { replaceStudy(await api<EngineStudy>(P(`/studies/${id}/boundaries/${bid}`), { method: 'DELETE' })); } catch (e) { toast(e); }
}

// ---------- running ----------

export async function runStudy(id: string, force = false) {
  try {
    const job = await api<EngineJob>(P(`/studies/${id}/run`), { body: { force } });
    patchSim((s) => ({ jobs: { ...s.jobs, [job.id]: job } }));
    if (job.status === 'done') { get().showToast('Result is up to date (from cache)'); scheduleStudies(50); }
    useApp.setState({ simProbe: null, simRange: null });
  } catch (e) { toast(e, 'Can’t run: '); }
}

export async function cancelJob(jid: string) {
  try { await api(`/api/jobs/${jid}/cancel`, { body: {} }); } catch (e) { toast(e); }
}

export async function retryJob(jid: string) {
  try { await api(`/api/jobs/${jid}/retry`, { body: {} }); } catch (e) { toast(e); }
}

export async function addTarget(name: string, url: string, token: string) {
  try {
    const t = await api<EngineTarget>('/api/targets', { body: { name, url, token } });
    get().showToast(t.online ? `${t.name} connected` : `${t.name} added, but not reachable yet${t.problem ? `: ${t.problem}` : ''}`);
    await loadTargets();
    return true;
  } catch (e) { toast(e, 'Could not add the compute node: '); return false; }
}

export async function removeTarget(id: string) {
  try { await api(`/api/targets/${id}`, { method: 'DELETE' }); await loadTargets(); } catch (e) { toast(e); }
}

// ---------- quick checks (no solver) ----------

export async function exactClash(a: string, b: string): Promise<{ clash: boolean; overlap_mm3: number; distance_mm: number } | null> {
  try { return await api(P('/measure'), { body: { kind: 'clash', a, b } }); } catch (e) { toast(e); return null; }
}

// ---------- labels ----------

export const BOUNDARY_LABEL: Record<BoundaryType, string> = {
  fixed: 'Fixed support', force: 'Force', pressure: 'Pressure', gravity: 'Gravity',
  temperature: 'Temperature', heat_flux: 'Heat input', convection: 'Convection',
};

export const BOUNDARY_TYPES: Record<StudyType, { supports: BoundaryType[]; loads: BoundaryType[] }> = {
  static: { supports: ['fixed'], loads: ['force', 'pressure', 'gravity'] },
  modal: { supports: ['fixed'], loads: [] },
  thermal: { supports: ['temperature', 'convection'], loads: ['heat_flux'] },
};

export function boundaryValue(b: StudyBoundary): string {
  const v = (x: number) => (Math.abs(x) >= 100 ? x.toFixed(0) : Number(x.toPrecision(3)).toString());
  switch (b.type) {
    case 'fixed': return 'all directions';
    case 'force': {
      const f = b.vector ?? [0, 0, 0];
      const mag = Math.hypot(...f);
      return `${v(mag)} N [${f.map(v).join(', ')}]`;
    }
    case 'gravity': return `${v(Math.hypot(...(b.vector ?? [0, 0, 0])))} m/s²`;
    case 'pressure': return `${v(b.value ?? 0)} MPa`;
    case 'temperature': return `${v(b.value ?? 0)} °C`;
    case 'heat_flux': return `${v(b.value ?? 0)} W`;
    case 'convection': return `h ${v(b.value ?? 0)} W/m²K, ${v(b.ambient ?? 20)} °C`;
  }
}

export const STUDY_META: Record<StudyType, { group: string; icon: string; engine: string }> = {
  static: { group: 'Structural (FEM)', icon: 'FEM', engine: 'linear static' },
  modal: { group: 'Vibration', icon: 'VIB', engine: 'modal' },
  thermal: { group: 'Heat', icon: 'TH', engine: 'steady-state thermal' },
};

/** Colour stops of the result legend (same as the .legend CSS gradient). */
export const COLORMAP = ['#2B59C3', '#22A6B3', '#7BC043', '#F2C230', '#E2462F'];
