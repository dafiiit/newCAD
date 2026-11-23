// Check tab with a running engine: real studies, solved by Gmsh + CalculiX on a compute target.
import { useEffect, useMemo, useState } from 'react';
import { cx, Segmented } from '../../components/ui';
import { CloseIcon } from '../../components/icons';
import { assetUrl } from '../../engine/client';
import { boxOverlaps, engineParts } from '../../engine/model';
import {
  addBoundary, addTarget, BOUNDARY_LABEL, BOUNDARY_TYPES, boundaryValue, cancelJob, COLORMAP, createStudy, deleteStudy, exactClash,
  loadTargets, patchStudy, removeBoundary, removeTarget, retryJob, runStudy, STUDY_META, studyJob, targetName,
} from '../../engine/sim';
import type { BoundaryType, EngineJob, EngineStudy, FieldInfo, StudySummary, StudyType, Where } from '../../engine/types';
import { useApp, type AppState, type SimPick } from '../../state/store';
import { MotionDetail, MotionNumbers } from './MotionCheck';

export const fmt = (x: number, unit = '') => {
  const a = Math.abs(x);
  const s = a === 0 ? '0' : a >= 1000 ? x.toFixed(0) : a >= 10 ? x.toFixed(1) : a >= 0.01 ? x.toFixed(3) : x.toExponential(2);
  return unit ? `${s} ${unit}` : s;
};

const NO_STUDIES: EngineStudy[] = [];

export function selectedStudy(s: Pick<AppState, 'eng' | 'simSel'>): EngineStudy | undefined {
  const list = s.eng?.sim?.studies ?? [];
  return list.find((x) => x.id === s.simSel) ?? list[0];
}

/** What the 3D view and the overlay show for the selected study. */
export function studyView(st: EngineStudy | undefined) {
  if (!st) return null;
  const job = studyJob(st);
  const state = st.state;
  const running = job && (job.status === 'queued' || job.status === 'running') ? job : undefined;
  const done = state?.status === 'done' && state.summary ? state : undefined;
  const failed = !running && !done && job?.status === 'failed' ? job : undefined;
  return { st, job, running, done, failed, problem: state?.status === 'problem' ? state.problem : undefined };
}

export function defaultField(sum: StudySummary | undefined): string | null {
  if (!sum) return null;
  if (sum.type === 'static') return 'von_mises';
  if (sum.type === 'thermal') return 'temp';
  if (sum.type === 'motion') return null;
  return 'mode_mag';
}

function whereText(w: Where | undefined, parts: Record<string, string>) {
  if (!w) return '';
  return `${w.part ? parts[w.part] ?? w.part : ''}${w.face ? `, face ${w.face}` : ''}`;
}

function badge(v: ReturnType<typeof studyView>) {
  if (!v) return { text: 'Not run', cls: '' };
  if (v.running) return { text: v.running.status === 'queued' ? 'Queued' : `${Math.round(v.running.progress * 100)} %`, cls: 'run' };
  if (v.done) return { text: 'Done', cls: 'done' };
  if (v.failed) return { text: 'Failed', cls: 'fail' };
  if (v.problem) return { text: 'Set up', cls: '' };
  return { text: 'Not run', cls: '' };
}

export function EngineCheckPanel() {
  const studies = useApp((s) => s.eng?.sim?.studies) ?? NO_STUDIES;
  const loaded = useApp((s) => !!s.eng?.sim?.loaded);
  const simSel = useApp((s) => s.simSel);
  useApp((s) => s.eng?.sim?.jobs); // re-render on job progress
  const [adding, setAdding] = useState(false);
  const sel = studies.find((x) => x.id === simSel) ?? studies[0];
  const groups = useMemo(() => {
    const g: { title: string; items: EngineStudy[] }[] = [];
    for (const st of studies) {
      const t = STUDY_META[st.type].group;
      let x = g.find((y) => y.title === t);
      if (!x) { x = { title: t, items: [] }; g.push(x); }
      x.items.push(st);
    }
    return g;
  }, [studies]);

  return (
    <>
      <QuickChecks />
      {groups.map((g) => (
        <div key={g.title} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div className="sect">{g.title}</div>
          {g.items.map((st) => {
            const v = studyView(st);
            const b = badge(v);
            const nb = st.boundaries.length;
            const nd = st.motion?.drivers.length ?? 0;
            return (
              <button key={st.id} className={cx('stitem', sel?.id === st.id && 'on')}
                onClick={() => useApp.setState({ simSel: st.id, simPick: null, matePick: null, motionPreview: false, simProbe: null, simRange: null, simField: null })}>
                <span className="sticon">{STUDY_META[st.type].icon}</span>
                <span className="stbody"><b>{st.name}</b><span className="muted">{st.type === 'motion' ? (nd ? `${nd} driver${nd > 1 ? 's' : ''}${st.motion?.sweep ? ', sweep' : ''}` : 'No driver yet') : nb ? `${nb} condition${nb > 1 ? 's' : ''}` : 'No supports or loads yet'}</span></span>
                <span className={cx('stbadge', b.cls)}>{b.text}</span>
              </button>
            );
          })}
        </div>
      ))}
      {loaded && !studies.length && <p className="muted" style={{ fontSize: 13, margin: '12px 2px 4px' }}>No studies yet. Add one, pick the faces that are held and loaded, and run it.</p>}
      {adding ? (
        <div className="simadd">
          {(['static', 'modal', 'thermal', 'motion'] as StudyType[]).map((t) => (
            <button key={t} className="pillbtn" onClick={() => { setAdding(false); void createStudy(t); }}>
              {{ static: 'Static stress', modal: 'Natural frequencies', thermal: 'Heat transfer', motion: 'Motion (MuJoCo)' }[t]}
            </button>
          ))}
          <button className="linkbtn" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ) : (
        <button className="linkbtn" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => setAdding(true)}>+ New study</button>
      )}
      {sel && (sel.type === 'motion' ? <MotionDetail st={sel} /> : <StudyDetail st={sel} />)}
      <ComputeTargets />
    </>
  );
}

function QuickChecks() {
  const s = useApp();
  const man = s.eng?.manifest;
  const [clash, setClash] = useState<{ pairs: { name: string; clash: boolean; overlap: number }[]; done: boolean } | null>(null);
  if (!man || !man.parts.length) return null;
  const ok = engineParts(s)?.filter((p) => p.ok) ?? [];
  const run = async () => {
    setClash({ pairs: [], done: false });
    const cand = boxOverlaps(ok);
    const out: { name: string; clash: boolean; overlap: number }[] = [];
    for (const c of cand) {
      const r = await exactClash(c.a, c.b);
      if (r) out.push({ name: c.name, clash: r.clash, overlap: r.overlap_mm3 });
    }
    setClash({ pairs: out, done: true });
  };
  const clashes = clash?.pairs.filter((p) => p.clash) ?? [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div className="sect">Quick checks</div>
      <div className="kv"><span>Mass</span><b>{fmt(man.mass_kg, 'kg')}</b></div>
      {man.cg && <div className="kv"><span>Centre of gravity</span><span>({man.cg.map((x) => x.toFixed(1)).join(', ')}) mm</span></div>}
      <div className="kv">
        <span>Interference</span>
        {clash?.done ? <b>{clashes.length ? `${clashes.length} clash${clashes.length > 1 ? 'es' : ''}` : 'none'}</b>
          : <button className="linkbtn" style={{ padding: 0 }} disabled={!!clash} onClick={run}>{clash ? 'Checking…' : 'Check exactly'}</button>}
      </div>
      {clashes.map((c) => <div key={c.name} className="kv" style={{ paddingLeft: 10 }}><span>{c.name}</span><span>{fmt(c.overlap, 'mm³')}</span></div>)}
    </div>
  );
}

function StudyDetail({ st }: { st: EngineStudy }) {
  const s = useApp();
  const v = studyView(st)!;
  const parts = engineParts(s) ?? [];
  const names = Object.fromEntries(parts.map((p) => [p.id, p.name]));
  const pick = s.simPick;
  const kinds = BOUNDARY_TYPES[st.type];
  const runLabel = v.done ? 'Re-run' : `Run ${STUDY_META[st.type].engine}`;
  const [meshDraft, setMeshDraft] = useState<string>(st.mesh.size ? String(st.mesh.size) : '');
  useEffect(() => setMeshDraft(st.mesh.size ? String(st.mesh.size) : ''), [st.id, st.mesh.size]);

  const startPick = (type: BoundaryType) => {
    const p: SimPick = { type, faces: [], vector: [0, 0, -100], value: null, ambient: null, label: '' };
    if (type === 'gravity') p.vector = [0, 0, -9.81];
    if (type === 'pressure') p.value = 0.1;
    if (type === 'temperature') p.value = 20;
    if (type === 'heat_flux') p.value = 10;
    if (type === 'convection') { p.value = 10; p.ambient = 20; }
    useApp.setState({ simPick: p, selected: null });
  };

  return (
    <div className="detail checkdetail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <h3 style={{ flex: 1 }}>{st.name}</h3>
        <button className="iconbtn sm" aria-label={`Delete ${st.name}`} title="Delete study" onClick={() => { if (window.confirm?.(`Delete the study “${st.name}”?`) ?? true) void deleteStudy(st.id); }}><CloseIcon size={14} /></button>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>FEM · {STUDY_META[st.type].engine} · Gmsh + CalculiX · {st.mesh.size ? `${st.mesh.size} mm` : 'auto'} quadratic tetra</span>

      <div className="sect">Supports and loads</div>
      {st.boundaries.map((b) => (
        <div key={b.id} className="bcrow">
          <span className={cx('bcdot', b.type === 'fixed' || b.type === 'temperature' || b.type === 'convection' ? 'sup' : 'load')} />
          <span className="bcbody">
            <b>{b.label || BOUNDARY_LABEL[b.type]}</b>
            <span className="muted">{boundaryValue(b)}{b.faces.length ? ` · ${b.faces.length} face${b.faces.length > 1 ? 's' : ''} on ${[...new Set(b.faces.map((f) => names[f.part] ?? f.part))].join(', ')}` : ''}</span>
          </span>
          <button className="iconbtn sm" aria-label={`Remove ${b.label || BOUNDARY_LABEL[b.type]}`} onClick={() => removeBoundary(st.id, b.id)}><CloseIcon size={12} /></button>
        </div>
      ))}
      {!pick && (
        <div className="simadd">
          {[...kinds.supports, ...kinds.loads].map((t) => (
            <button key={t} className="pillbtn" onClick={() => startPick(t)}>+ {BOUNDARY_LABEL[t]}</button>
          ))}
        </div>
      )}
      {pick && <PickCard st={st} pick={pick} />}

      <div className="sect">Materials</div>
      {parts.filter((p) => !st.parts || st.parts.includes(p.id)).map((p) => (
        <div key={p.id} className="kv" style={{ alignItems: 'center' }}>
          <span>{p.name}</span>
          <select aria-label={`Material of ${p.name}`} value={st.materials[p.id] ?? p.material ?? 'Steel'} style={{ height: 30 }}
            onChange={(e) => patchStudy(st.id, { materials: { ...st.materials, [p.id]: e.target.value } })}>
            {(s.eng?.sim?.materials ?? []).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
        </div>
      ))}
      <div className="kv" style={{ alignItems: 'center' }}>
        <span>Mesh size</span>
        <span className="siminwrap">
          <input className="simin" inputMode="decimal" placeholder="auto" value={meshDraft} aria-label="Mesh size in mm"
            onChange={(e) => setMeshDraft(e.target.value)}
            onBlur={() => { const n = Number(meshDraft); patchStudy(st.id, { mesh: { size: meshDraft.trim() && n > 0 ? n : null } }); }}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} /> mm
        </span>
      </div>
      {st.type === 'modal' && (
        <div className="kv" style={{ alignItems: 'center' }}>
          <span>Modes</span>
          <NumIn value={st.modes} label="Number of modes" onCommit={(n) => n && patchStudy(st.id, { modes: Math.max(1, Math.min(30, Math.round(n))) })} />
        </div>
      )}
      {st.type === 'static' && (
        <div className="kv" style={{ alignItems: 'center' }}>
          <span>Safety target</span>
          <NumIn value={st.safety_target ?? Number(s.settings.sfTarget) ?? 2} label="Required safety factor" onCommit={(n) => n && patchStudy(st.id, { safety_target: n })} />
        </div>
      )}

      {v.problem && !pick && <p className="simnote">{v.problem}</p>}
      {v.running ? <JobProgress job={v.running} /> : (
        <button className="pillbtn dark" disabled={!!v.problem || !!pick} onClick={() => runStudy(st.id, !!v.done)}>{runLabel}</button>
      )}
      {v.failed && (
        <div className="simnote fail">
          {v.failed.error}
          <button className="linkbtn" onClick={() => retryJob(v.failed!.id)}>Retry</button>
        </div>
      )}
      {v.done && <Results st={st} sum={v.done.summary!} files={v.done.files ?? {}} names={names} />}
    </div>
  );
}

/** Static: scale factor on the real displacement. Modal: the largest motion drawn, in mm (mode shapes have no absolute size). */
function deformText(v: number, modal: boolean) {
  if (v === 0) return 'off';
  const n = v >= 10 ? Math.round(v).toString() : v.toFixed(1);
  return modal ? `${n} mm` : `${n}×`;
}

export function NumIn({ value, label, onCommit }: { value: number; label: string; onCommit: (n: number | null) => void }) {
  const [d, setD] = useState(String(value));
  useEffect(() => setD(String(value)), [value]);
  return (
    <input className="simin" inputMode="decimal" aria-label={label} value={d} onChange={(e) => setD(e.target.value)}
      onBlur={() => { const n = Number(d); onCommit(d.trim() && Number.isFinite(n) ? n : null); }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
  );
}

function PickCard({ st, pick }: { st: EngineStudy; pick: SimPick }) {
  const set = (p: Partial<SimPick>) => useApp.setState({ simPick: { ...pick, ...p } });
  const needsFaces = pick.type !== 'gravity';
  const [busy, setBusy] = useState(false);
  const vec = (i: number, v: string) => { const x = [...pick.vector] as [number, number, number]; x[i] = Number(v) || 0; set({ vector: x }); };
  const ready = !needsFaces || pick.faces.length > 0;
  const add = async () => {
    setBusy(true);
    const ok = await addBoundary(st.id, {
      type: pick.type, label: pick.label, faces: pick.faces,
      vector: pick.type === 'force' || pick.type === 'gravity' ? pick.vector : undefined,
      value: pick.value, ambient: pick.ambient,
    });
    setBusy(false);
    if (ok) useApp.setState({ simPick: null });
  };
  return (
    <div className="bcpick">
      <b>{BOUNDARY_LABEL[pick.type]}</b>
      {needsFaces && <span className="muted" style={{ fontSize: 12 }}>{pick.faces.length ? `${pick.faces.length} face${pick.faces.length > 1 ? 's' : ''} picked. Click more faces, or click a picked face to drop it.` : 'Click the faces on the model.'}</span>}
      {(pick.type === 'force' || pick.type === 'gravity') && (
        <div className="vecin" aria-label={pick.type === 'force' ? 'Total force in N' : 'Acceleration in m/s²'}>
          {['X', 'Y', 'Z'].map((ax, i) => (
            <label key={ax}>{ax}<input className="simin" inputMode="decimal" defaultValue={pick.vector[i]} onChange={(e) => vec(i, e.target.value)} /></label>
          ))}
          <span className="muted">{pick.type === 'force' ? 'N total' : 'm/s²'}</span>
        </div>
      )}
      {pick.value !== null && (
        <div className="kv" style={{ alignItems: 'center' }}>
          <span>{{ pressure: 'Pressure (MPa, + pushes in)', temperature: 'Temperature (°C)', heat_flux: 'Heat input (W)', convection: 'h (W/m²K)' }[pick.type as 'pressure'] ?? 'Value'}</span>
          <input className="simin" inputMode="decimal" defaultValue={pick.value} onChange={(e) => set({ value: Number(e.target.value) })} aria-label="Value" />
        </div>
      )}
      {pick.ambient !== null && (
        <div className="kv" style={{ alignItems: 'center' }}>
          <span>Ambient (°C)</span>
          <input className="simin" inputMode="decimal" defaultValue={pick.ambient} onChange={(e) => set({ ambient: Number(e.target.value) })} aria-label="Ambient temperature" />
        </div>
      )}
      <input className="simin wide" placeholder="Name (optional), e.g. Wall bolts" value={pick.label} onChange={(e) => set({ label: e.target.value })} aria-label="Name" />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="pillbtn dark" disabled={!ready || busy} onClick={add}>Add</button>
        <button className="pillbtn" onClick={() => useApp.setState({ simPick: null })}>Cancel</button>
      </div>
    </div>
  );
}

export function JobProgress({ job }: { job: EngineJob }) {
  return (
    <div className="simjob" aria-live="polite">
      <div className="simbar"><span style={{ width: `${Math.max(3, Math.round(job.progress * 100))}%` }} /></div>
      <div className="kv"><span>{job.stage}{job.target ? ` · ${targetName(job.target)}` : ''}</span>
        <button className="linkbtn" style={{ padding: 0 }} onClick={() => cancelJob(job.id)}>Cancel</button></div>
    </div>
  );
}

const FIELD_OPTIONS: Record<string, { key: string; label: string }[]> = {
  static: [{ key: 'von_mises', label: 'Stress' }, { key: 'safety', label: 'Safety' }, { key: 'disp_mag', label: 'Displacement' }],
  modal: [{ key: 'mode_mag', label: 'Mode shape' }],
  thermal: [{ key: 'temp', label: 'Temperature' }],
  motion: [],
};

export function useResultField(sum: StudySummary | undefined) {
  const simField = useApp((s) => s.simField);
  const simRange = useApp((s) => s.simRange);
  const key = sum && simField && sum.fields[simField] ? simField : defaultField(sum);
  const info: FieldInfo | undefined = key && sum ? sum.fields[key] : undefined;
  const range: [number, number] | null = info ? simRange ?? [info.min, info.max] : null;
  return { key, info, range };
}

function Results({ st, sum, files, names }: { st: EngineStudy; sum: StudySummary; files: Record<string, string>; names: Record<string, string> }) {
  const s = useApp();
  const { key, info, range } = useResultField(sum);
  const opts = FIELD_OPTIONS[sum.type];
  const sel = opts.find((o) => o.key === key)?.label ?? opts[0].label;
  const target = sum.safety_target ?? st.safety_target ?? Number(s.settings.sfTarget);
  return (
    <>
      <div className="sect">Results</div>
      <ResultNumbers sum={sum} names={names} target={target} />
      {sum.type === 'modal' && sum.modes && (
        <div className="modes">
          {sum.modes.map((m) => (
            <button key={m.index} className={cx('mode', s.mode === m.index && 'on')} onClick={() => useApp.setState({ mode: m.index, playing: true })}>
              <b>Mode {m.index}</b><span>{m.frequency_hz.toFixed(1)} Hz</span><span className="muted">moves most: {m.max_at.part ? names[m.max_at.part] ?? m.max_at.part : '–'}</span>
            </button>
          ))}
        </div>
      )}
      {opts.length > 1 && <Segmented label="Result shown" options={opts.map((o) => o.label)} value={sel} style={{ marginTop: 6 }}
        onChange={(l) => useApp.setState({ simField: opts.find((o) => o.label === l)!.key, simRange: null })} />}
      {info && range && <EditableLegend info={info} range={range} />}
      <label className="rpmlbl" htmlFor="deform">{sum.type === 'modal' ? 'Mode shape amplitude' : 'Deformed shape'} <b>{deformText(s.simDeform * (sum.deform_scale ?? 1), sum.type === 'modal')}</b></label>
      {sum.type !== 'thermal' && <input id="deform" type="range" min={0} max={3} step={0.05} value={s.simDeform} onChange={(e) => useApp.setState({ simDeform: Number(e.target.value) })} style={{ accentColor: '#111' }} />}
      {sum.type === 'modal' && <div className="playrow"><button className="pillbtn" onClick={() => useApp.setState({ playing: !s.playing })}>{s.playing ? 'Pause' : 'Play'}</button><span className="muted" style={{ fontSize: 12 }}>Mode {s.mode} · shape exaggerated</span></div>}
      {s.simProbe && <div className="kv"><span>Probe</span><b>{fmt(s.simProbe.value, s.simProbe.unit)}</b></div>}
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
        {sum.mesh.elements.toLocaleString()} elements, min quality {sum.mesh.min_quality.toFixed(2)} · solved in {sum.timing_s.total.toFixed(1)} s on {targetName(sum.target)} with {sum.solver.name} {sum.solver.version ?? ''}
        {files['result.vtu'] && <> · <a href={assetUrl(files['result.vtu'])} download>VTU for ParaView</a></>}
      </p>
      {sum.warnings.map((w) => <p key={w} className="simnote">{w}</p>)}
    </>
  );
}

export function ResultNumbers({ sum, names, target }: { sum: StudySummary; names: Record<string, string>; target: number }) {
  if (sum.type === 'motion') return <MotionNumbers sum={sum} names={{ ground: 'Ground', ...names }} />;
  if (sum.type === 'static') {
    const sf = sum.min_safety_factor ?? 0;
    return (
      <>
        <div className="kv"><span>Peak von Mises</span><b>{fmt(sum.max_von_mises_mpa ?? 0, 'MPa')}</b></div>
        <div className="kv"><span>at</span><span>{whereText(sum.max_von_mises_at, names)}</span></div>
        <div className="kv"><span>Safety factor</span><b className={cx(sf < target && 'simbad')}>{sf >= 100 ? '> 100' : sf.toFixed(2)} (target {Number(target).toFixed(1)})</b></div>
        <div className="kv"><span>Max deflection</span><b>{fmt(sum.max_displacement_mm ?? 0, 'mm')}</b></div>
      </>
    );
  }
  if (sum.type === 'modal') {
    const f = sum.frequencies_hz ?? [];
    return <div className="kv"><span>First mode</span><b>{f.length ? `${f[0].toFixed(1)} Hz` : '–'}</b></div>;
  }
  return (
    <>
      <div className="kv"><span>Max temperature</span><b>{fmt(sum.max_temperature_c ?? 0, '°C')}</b></div>
      <div className="kv"><span>at</span><span>{whereText(sum.max_temperature_at, names)}</span></div>
      <div className="kv"><span>Min temperature</span><b>{fmt(sum.min_temperature_c ?? 0, '°C')}</b></div>
    </>
  );
}

const nice = (x: number) => (Math.abs(x) < 1e-6 ? 0 : Number(x.toPrecision(4)));

export function EditableLegend({ info, range }: { info: FieldInfo; range: [number, number] }) {
  const commit = (i: 0 | 1, v: string) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return;
    const r: [number, number] = [...range];
    r[i] = n;
    useApp.setState({ simRange: r });
  };
  const custom = useApp((s) => !!s.simRange);
  return (
    <>
      <div className="legend truecol" style={{ background: `linear-gradient(90deg,${COLORMAP.join(',')})` }} />
      <div className="legendlbl simlegend">
        <input aria-label={`${info.label} at the low end`} key={`lo${range[0]}`} defaultValue={nice(range[0])} onBlur={(e) => commit(0, e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
        <span>{info.label}{info.unit ? ` (${info.unit})` : ''}{custom && <button className="linkbtn" style={{ fontSize: 11 }} onClick={() => useApp.setState({ simRange: null })}>reset</button>}</span>
        <input aria-label={`${info.label} at the high end`} key={`hi${range[1]}`} defaultValue={nice(range[1])} onBlur={(e) => commit(1, e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} style={{ textAlign: 'right' }} />
      </div>
    </>
  );
}

function ComputeTargets() {
  const targets = useApp((s) => s.eng?.sim?.targets);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{ name: string; url: string; token: string } | null>(null);
  useEffect(() => { if (open && !targets) void loadTargets(); }, [open, targets]);
  return (
    <div style={{ marginTop: 14 }}>
      <button className="linkbtn" style={{ padding: 0 }} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void loadTargets(); }}>
        {open ? 'Hide compute targets' : 'Compute targets'}
      </button>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {(targets ?? []).map((t) => {
            const d = t.devices;
            const missing = d ? Object.entries(d.solvers).filter(([, v]) => !v).map(([k]) => k) : [];
            return (
              <div key={t.id} className="targetrow">
                <span className={cx('bcdot', t.online ? 'on' : 'off')} />
                <span className="bcbody">
                  <b>{t.name}</b>
                  <span className="muted">
                    {t.online && d ? `${d.cpu.performance_cores} cores${d.memory_gb ? ` · ${Math.round(d.memory_gb)} GB` : ''}${d.gpus.length ? ` · ${d.gpus.map((g) => g.name).join(', ')}` : ' · no CUDA GPU'}${t.running ? ` · ${t.running} running` : ''}` : t.problem ?? 'offline'}
                  </span>
                  {missing.length > 0 && <span className="muted simbad">Missing: {missing.join(', ')}</span>}
                </span>
                {t.kind === 'remote' && <button className="iconbtn sm" aria-label={`Remove ${t.name}`} onClick={() => removeTarget(t.id)}><CloseIcon size={12} /></button>}
              </div>
            );
          })}
          {form ? (
            <div className="bcpick">
              <b>Add compute node</b>
              <span className="muted" style={{ fontSize: 12 }}>A machine running <code>newcad-engine --worker</code> (see compute-node/ in the repo).</span>
              <input className="simin wide" placeholder="Name, e.g. Lab GPU" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Name" />
              <input className="simin wide" placeholder="https://host:8765" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} aria-label="URL" />
              <input className="simin wide" placeholder="Token" type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} aria-label="Token" />
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="pillbtn dark" disabled={!form.name || !/^https?:\/\//.test(form.url) || form.token.length < 8}
                  onClick={async () => { if (await addTarget(form.name, form.url, form.token)) setForm(null); }}>Connect</button>
                <button className="pillbtn" onClick={() => setForm(null)}>Cancel</button>
              </div>
            </div>
          ) : (
            <button className="linkbtn" style={{ alignSelf: 'flex-start', padding: 0 }} onClick={() => setForm({ name: '', url: '', token: '' })}>+ Add compute node</button>
          )}
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>Each job goes to a target that has its solvers. CPU solvers stay on this computer unless it is busy.</p>
        </div>
      )}
    </div>
  );
}

/** Floating card on the 3D view for the selected engine study. */
export function EngineResultOverlay() {
  const s = useApp();
  useApp((x) => x.eng?.sim?.jobs);
  const st = selectedStudy(s);
  const parts = engineParts(s) ?? [];
  const names = Object.fromEntries(parts.map((p) => [p.id, p.name]));
  const v = studyView(st);
  const sum = v?.done?.summary;
  const { info, range } = useResultField(sum);
  if (!st || !v) {
    return (
      <div className="resov" aria-label="Study result">
        <div className="resovhead"><span className="sticon">FEM</span><span className="resovt"><b>No study yet</b><span className="muted">Add one in the Check panel</span></span></div>
      </div>
    );
  }
  const b = badge(v);
  return (
    <div className="resov" aria-label="Study result">
      <div className="resovhead">
        <span className="sticon">{STUDY_META[st.type].icon}</span>
        <span className="resovt"><b>{st.name}</b><span className="muted">{s.matePick ? `Picking faces for a ${s.matePick.type} joint` : s.simPick ? `Picking faces for ${BOUNDARY_LABEL[s.simPick.type].toLowerCase()}` : b.text === 'Done' ? `${STUDY_META[st.type].group} · done` : b.text}</span></span>
      </div>
      {v.running && <JobProgress job={v.running} />}
      {sum && !s.simPick && !s.matePick ? (
        <>
          {info && range && <EditableLegend info={info} range={range} />}
          <ResultNumbers sum={sum} names={names} target={sum.safety_target ?? st.safety_target ?? Number(s.settings.sfTarget)} />
          {s.simProbe && <div className="kv"><span>Probe{s.simProbe.face ? ` (${s.simProbe.face})` : ''}</span><b>{fmt(s.simProbe.value, s.simProbe.unit)}</b></div>}
          {!s.simProbe && st.type !== 'motion' && <span className="muted" style={{ fontSize: 12 }}>Click the model to read a value.</span>}
          {st.type === 'motion' && <span className="muted" style={{ fontSize: 12 }}>{s.motionPreview ? 'Preview physics (Rapier): drag a part. Numbers come from MuJoCo.' : 'Playing the MuJoCo result.'}</span>}
        </>
      ) : !v.running && (
        <p className="muted" style={{ margin: '2px 0 4px', fontSize: 13 }}>{s.simPick || s.matePick ? 'Click faces on the model, then press Add in the panel.' : v.problem ?? (v.failed ? v.failed.error : 'Not run on this version yet.')}</p>
      )}
    </div>
  );
}
