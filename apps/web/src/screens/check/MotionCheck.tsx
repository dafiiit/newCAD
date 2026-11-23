// Check tab, motion studies (MuJoCo): joints from picked faces, drivers, springs, settings and a
// parameter sweep; results with peak bearing loads, a time plot, playback, the sweep table, and
// the hand-off of a bearing load into a static stress study. The Rapier grab-and-drag preview is
// switched on here; it is labelled as preview physics because the numbers come from MuJoCo.
import { useEffect, useMemo, useState } from 'react';
import { CloseIcon } from '../../components/icons';
import { cx } from '../../components/ui';
import { assetUrl } from '../../engine/client';
import { engineParts } from '../../engine/model';
import {
  addMate, deleteStudy, DRIVER_LABEL, driverUnit, loadSeries, MATE_LABEL, patchMotion, removeMate, retryJob, runStudy, springUnit,
  sweepPeak, targetName, useBearingLoad,
} from '../../engine/sim';
import type { DriverKind, MotionMate, EngineStudy, MateType, MotionSeries, MotionSetup, StudySummary } from '../../engine/types';
import { useApp, type MatePick } from '../../state/store';
import { fmt, JobProgress, NumIn, studyView } from './EngineCheck';
import { clock } from './MotionAssembly';

const MATE_TYPES: MateType[] = ['revolute', 'prismatic', 'ball', 'fixed'];
const MATE_HINT: Record<MateType, string> = {
  revolute: 'Click the bore or pin of each part (one round face is enough on a part held by ground).',
  prismatic: 'Click a flat or round face along the slide on each part.',
  ball: 'Click the ball and its socket.',
  fixed: 'Click a face on each part; one part alone is fixed to the ground.',
};

const DEFAULT_SETUP: MotionSetup = { duration: 2, timestep: 0.001, gravity: [0, 0, -9.81], contacts: false, damping: 0, drivers: [], springs: [], sweep: null, samples: 400 };

export function MotionDetail({ st }: { st: EngineStudy }) {
  const s = useApp();
  const v = studyView(st)!;
  const parts = engineParts(s) ?? [];
  const names: Record<string, string> = { ground: 'Ground', ...Object.fromEntries(parts.map((p) => [p.id, p.name])) };
  const mates = s.eng?.sim?.mates ?? [];
  const m = st.motion ?? DEFAULT_SETUP;
  const pick = s.matePick;
  const busy = !!pick;

  return (
    <div className="detail checkdetail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <h3 style={{ flex: 1 }}>{st.name}</h3>
        <button className="iconbtn sm" aria-label={`Delete ${st.name}`} title="Delete study" onClick={() => { if (window.confirm?.(`Delete the study “${st.name}”?`) ?? true) void deleteStudy(st.id); }}><CloseIcon size={14} /></button>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>Rigid-body motion · MuJoCo · {m.duration} s at {Number((m.timestep * 1000).toPrecision(3))} ms steps{m.contacts ? ' · contacts on' : ''}</span>

      <div className="sect">Joints</div>
      {mates.map((j) => <MateRow key={j.id} mate={j} names={names} />)}
      {!mates.length && !pick && <p className="muted" style={{ fontSize: 12, margin: 0 }}>No joints yet. Add one and click the faces it connects.</p>}
      {!pick && (
        <div className="simadd">
          {MATE_TYPES.map((t) => (
            <button key={t} className="pillbtn" onClick={() => useApp.setState({ matePick: { type: t, faces: [], label: '' }, simPick: null, selected: null, motionPreview: false })}>+ {MATE_LABEL[t]}</button>
          ))}
        </div>
      )}
      {pick && <MatePickCard pick={pick} names={names} />}

      <Drivers st={st} m={m} mates={mates} names={names} />
      <Springs st={st} m={m} mates={mates} />
      <Settings st={st} m={m} />
      <Sweep st={st} m={m} mates={mates} parts={parts.map((p) => ({ id: p.id, name: p.name }))} />

      {v.problem && !pick && <p className="simnote">{v.problem}</p>}
      {v.running ? <JobProgress job={v.running} /> : (
        <button className="pillbtn dark" disabled={!!v.problem || busy} onClick={() => runStudy(st.id, !!v.done)}>{v.done ? 'Re-run' : 'Run MuJoCo'}</button>
      )}
      {v.failed && (
        <div className="simnote fail">
          {v.failed.error}
          <button className="linkbtn" onClick={() => retryJob(v.failed!.id)}>Retry</button>
        </div>
      )}
      <PreviewToggle disabled={busy || !mates.length} />
      {v.done && <MotionResults st={st} sum={v.done.summary!} files={v.done.files ?? {}} rkey={v.done.key ?? ''} names={names} />}
    </div>
  );
}

function MateRow({ mate, names }: { mate: MotionMate; names: Record<string, string> }) {
  const where = mate.origin_mm ? ` · at ${mate.origin_mm.map((x) => Number(x.toFixed(1))).join(', ')} mm` : '';
  return (
    <div className="bcrow">
      <span className={cx('bcdot', mate.problem ? 'off' : 'sup')} />
      <span className="bcbody">
        <b>{mate.label || mate.id}</b>
        <span className="muted">{MATE_LABEL[mate.type]} · {names[mate.parts[0]] ?? mate.parts[0]} ↔ {names[mate.parts[1]] ?? mate.parts[1]}{where}</span>
        {mate.problem && <span className="muted simbad">{mate.problem}</span>}
      </span>
      <button className="iconbtn sm" aria-label={`Remove ${mate.label || mate.id}`} onClick={() => removeMate(mate.id)}><CloseIcon size={12} /></button>
    </div>
  );
}

function MatePickCard({ pick, names }: { pick: MatePick; names: Record<string, string> }) {
  const [busy, setBusy] = useState(false);
  const partsPicked = [...new Set(pick.faces.map((f) => f.part))];
  const ready = partsPicked.length >= 1 && partsPicked.length <= 2;
  const add = async () => {
    setBusy(true);
    const ok = await addMate({ type: pick.type, label: pick.label, faces: pick.faces });
    setBusy(false);
    if (ok) useApp.setState({ matePick: null });
  };
  return (
    <div className="bcpick">
      <b>{MATE_LABEL[pick.type]} joint</b>
      <span className="muted" style={{ fontSize: 12 }}>
        {pick.faces.length
          ? `${pick.faces.length} face${pick.faces.length > 1 ? 's' : ''} on ${partsPicked.map((p) => names[p] ?? p).join(' and ')}${partsPicked.length === 1 ? ' (joined to ground)' : ''}.${partsPicked.length > 2 ? ' A joint connects two parts; drop faces from the others.' : ''}`
          : MATE_HINT[pick.type]}
      </span>
      <input className="simin wide" placeholder="Name (optional), e.g. Crank pivot" value={pick.label} aria-label="Name"
        onChange={(e) => useApp.setState({ matePick: { ...pick, label: e.target.value } })} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="pillbtn dark" disabled={!ready || busy} onClick={add}>Add</button>
        <button className="pillbtn" onClick={() => useApp.setState({ matePick: null })}>Cancel</button>
      </div>
    </div>
  );
}

const drivable = (j: MotionMate) => j.type === 'revolute' || j.type === 'prismatic';

function Drivers({ st, m, mates, names }: { st: EngineStudy; m: MotionSetup; mates: MotionMate[]; names: Record<string, string> }) {
  const byId = Object.fromEntries(mates.map((j) => [j.id, j]));
  const free = mates.filter((j) => drivable(j) && !m.drivers.some((d) => d.mate === j.id));
  const set = (drivers: MotionSetup['drivers']) => patchMotion(st.id, { drivers });
  return (
    <>
      <div className="sect">Drivers</div>
      {m.drivers.map((d, i) => {
        const j = byId[d.mate];
        return (
          <div key={d.mate} className="bcrow" style={{ flexWrap: 'wrap' }}>
            <span className="bcdot load" />
            <span className="bcbody">
              <b>{j?.label || d.mate}</b>
              <span className="muted">{j ? `${names[j.parts[1]] ?? j.parts[1]} relative to ${names[j.parts[0]] ?? j.parts[0]}` : 'joint missing'}</span>
            </span>
            <select aria-label="Driver kind" value={d.kind} style={{ height: 28 }}
              onChange={(e) => set(m.drivers.map((x, k) => (k === i ? { ...x, kind: e.target.value as DriverKind } : x)))}>
              {(Object.keys(DRIVER_LABEL) as DriverKind[]).map((k) => <option key={k} value={k}>{DRIVER_LABEL[k]}</option>)}
            </select>
            <span className="siminwrap">
              <NumIn value={d.value} label={`${DRIVER_LABEL[d.kind]} of ${j?.label || d.mate}`} onCommit={(n) => n !== null && set(m.drivers.map((x, k) => (k === i ? { ...x, value: n } : x)))} />
              {driverUnit(d.kind, j?.type)}
            </span>
            <button className="iconbtn sm" aria-label={`Remove driver on ${j?.label || d.mate}`} onClick={() => set(m.drivers.filter((_, k) => k !== i))}><CloseIcon size={12} /></button>
          </div>
        );
      })}
      {free.length > 0 && (
        <select aria-label="Add a driver" value="" style={{ height: 30, alignSelf: 'flex-start' }}
          onChange={(e) => e.target.value && set([...m.drivers, { mate: e.target.value, kind: 'speed', value: 60, ramp: 0.2 }])}>
          <option value="">+ Driver on a joint…</option>
          {free.map((j) => <option key={j.id} value={j.id}>{j.label || j.id}</option>)}
        </select>
      )}
      {!m.drivers.length && <span className="muted" style={{ fontSize: 12 }}>Without a driver the mechanism moves under gravity and springs only.</span>}
    </>
  );
}

function Springs({ st, m, mates }: { st: EngineStudy; m: MotionSetup; mates: MotionMate[] }) {
  const byId = Object.fromEntries(mates.map((j) => [j.id, j]));
  const free = mates.filter((j) => drivable(j) && !m.springs.some((x) => x.mate === j.id));
  const set = (springs: MotionSetup['springs']) => patchMotion(st.id, { springs });
  if (!m.springs.length && !free.length) return null;
  return (
    <>
      <div className="sect">Springs and dampers</div>
      {m.springs.map((sp, i) => {
        const j = byId[sp.mate];
        const u = springUnit(j?.type);
        return (
          <div key={sp.mate} className="bcrow" style={{ flexWrap: 'wrap' }}>
            <span className="bcdot load" />
            <span className="bcbody"><b>{j?.label || sp.mate}</b><span className="muted">k in {u}, c in {u}·s</span></span>
            <span className="siminwrap">k <NumIn value={sp.stiffness} label="Stiffness" onCommit={(n) => n !== null && set(m.springs.map((x, k) => (k === i ? { ...x, stiffness: Math.max(0, n) } : x)))} /></span>
            <span className="siminwrap">c <NumIn value={sp.damping} label="Damping" onCommit={(n) => n !== null && set(m.springs.map((x, k) => (k === i ? { ...x, damping: Math.max(0, n) } : x)))} /></span>
            <button className="iconbtn sm" aria-label={`Remove spring on ${j?.label || sp.mate}`} onClick={() => set(m.springs.filter((_, k) => k !== i))}><CloseIcon size={12} /></button>
          </div>
        );
      })}
      {free.length > 0 && (
        <select aria-label="Add a spring" value="" style={{ height: 30, alignSelf: 'flex-start' }}
          onChange={(e) => e.target.value && set([...m.springs, { mate: e.target.value, stiffness: 1, damping: 0, rest: 0 }])}>
          <option value="">+ Spring on a joint…</option>
          {free.map((j) => <option key={j.id} value={j.id}>{j.label || j.id}</option>)}
        </select>
      )}
    </>
  );
}

function Settings({ st, m }: { st: EngineStudy; m: MotionSetup }) {
  const gOn = Math.hypot(...m.gravity) > 0;
  return (
    <>
      <div className="sect">Settings</div>
      <div className="kv" style={{ alignItems: 'center' }}><span>Duration</span>
        <span className="siminwrap"><NumIn value={m.duration} label="Duration in s" onCommit={(n) => n && n > 0 && patchMotion(st.id, { duration: Math.min(n, 120) })} /> s</span></div>
      <div className="kv" style={{ alignItems: 'center' }}><span>Time step</span>
        <span className="siminwrap"><NumIn value={m.timestep * 1000} label="Time step in ms" onCommit={(n) => n && n > 0 && patchMotion(st.id, { timestep: Math.min(Math.max(n, 0.01), 20) / 1000 })} /> ms</span></div>
      <div className="kv" style={{ alignItems: 'center' }}><span>Joint damping</span>
        <span className="siminwrap"><NumIn value={m.damping} label="Joint damping" onCommit={(n) => n !== null && patchMotion(st.id, { damping: Math.max(0, n) })} /> N·m·s/rad</span></div>
      <label className="kv" style={{ alignItems: 'center' }}><span>Gravity (−Z)</span>
        <input type="checkbox" checked={gOn} onChange={(e) => patchMotion(st.id, { gravity: e.target.checked ? [0, 0, -9.81] : [0, 0, 0] })} /></label>
      <label className="kv" style={{ alignItems: 'center' }}><span>Contacts between parts</span>
        <input type="checkbox" checked={m.contacts} onChange={(e) => patchMotion(st.id, { contacts: e.target.checked })} /></label>
      {m.contacts && <span className="muted" style={{ fontSize: 12 }}>Collision shapes: boxes, cylinders and spheres are kept; other parts are split into convex pieces (CoACD).</span>}
    </>
  );
}

function sweepOptions(m: MotionSetup, mates: MotionMate[], parts: { id: string; name: string }[]) {
  const byId = Object.fromEntries(mates.map((j) => [j.id, j]));
  const o: { key: string; label: string; unit: string }[] = [];
  for (const d of m.drivers) o.push({ key: `drivers.${d.mate}.value`, label: `${DRIVER_LABEL[d.kind]}: ${byId[d.mate]?.label || d.mate}`, unit: driverUnit(d.kind, byId[d.mate]?.type) });
  for (const sp of m.springs) {
    o.push({ key: `springs.${sp.mate}.stiffness`, label: `Stiffness: ${byId[sp.mate]?.label || sp.mate}`, unit: springUnit(byId[sp.mate]?.type) });
    o.push({ key: `springs.${sp.mate}.damping`, label: `Damping: ${byId[sp.mate]?.label || sp.mate}`, unit: `${springUnit(byId[sp.mate]?.type)}·s` });
  }
  for (const p of parts) o.push({ key: `mass.${p.id}`, label: `Mass: ${p.name}`, unit: 'kg' });
  o.push({ key: 'damping', label: 'Joint damping', unit: 'N·m·s/rad' });
  return o;
}

function Sweep({ st, m, mates, parts }: { st: EngineStudy; m: MotionSetup; mates: MotionMate[]; parts: { id: string; name: string }[] }) {
  const opts = sweepOptions(m, mates, parts);
  const sw = m.sweep;
  const [txt, setTxt] = useState(sw ? sw.values.join(', ') : '');
  useEffect(() => setTxt(sw ? sw.values.join(', ') : ''), [st.id, sw?.values.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps
  const unit = opts.find((o) => o.key === sw?.parameter)?.unit ?? '';
  const commit = () => {
    const values = txt.split(/[,;\s]+/).map(Number).filter((x) => Number.isFinite(x));
    if (sw && values.length) void patchMotion(st.id, { sweep: { parameter: sw.parameter, values: values.slice(0, 4096) } });
  };
  return (
    <>
      <div className="sect">Parameter sweep</div>
      <select aria-label="Sweep parameter" value={sw?.parameter ?? ''} style={{ height: 30 }}
        onChange={(e) => {
          const p = e.target.value;
          if (!p) { void patchMotion(st.id, { sweep: null }); return; }
          const cur = p.startsWith('drivers.') ? m.drivers.find((d) => `drivers.${d.mate}.value` === p)?.value ?? 1 : 1;
          void patchMotion(st.id, { sweep: { parameter: p, values: [0.5, 0.75, 1, 1.25, 1.5].map((f) => Number((cur * f).toPrecision(4))) } });
        }}>
        <option value="">No sweep (one run)</option>
        {opts.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      {sw && (
        <>
          <div className="kv" style={{ alignItems: 'center' }}><span>Values ({unit})</span>
            <input className="simin wide" style={{ maxWidth: 180 }} aria-label="Sweep values" value={txt} onChange={(e) => setTxt(e.target.value)}
              onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} /></div>
          <span className="muted" style={{ fontSize: 12 }}>{sw.values.length} variants. On an NVIDIA target they run as parallel worlds in MuJoCo Warp; elsewhere on a CPU process pool.</span>
        </>
      )}
    </>
  );
}

function PreviewToggle({ disabled }: { disabled: boolean }) {
  const on = useApp((s) => s.motionPreview);
  return (
    <div className="bcpick" style={{ gap: 4 }}>
      <label className="kv" style={{ alignItems: 'center' }}>
        <span><b>Grab and drag</b> <span className="stbadge">Preview physics</span></span>
        <input type="checkbox" checked={on} disabled={disabled} aria-label="Grab and drag preview"
          onChange={(e) => useApp.setState({ motionPreview: e.target.checked, matePick: null })} />
      </label>
      <span className="muted" style={{ fontSize: 12 }}>Rapier in the browser, to feel how it moves. Loads and the numbers in the results always come from MuJoCo.</span>
    </div>
  );
}

const SPEEDS = [0.1, 0.25, 0.5, 1];

function MotionResults({ st, sum, files, rkey, names }: { st: EngineStudy; sum: StudySummary; files: Record<string, string>; rkey: string; names: Record<string, string> }) {
  const s = useApp();
  const [series, setSeries] = useState<MotionSeries | null>(null);
  const rows = sum.mates ?? [];
  const peak = sum.peak_bearing;
  const [plotMate, setPlotMate] = useState<string | null>(peak?.mate ?? rows[0]?.id ?? null);
  useEffect(() => setPlotMate(peak?.mate ?? rows[0]?.id ?? null), [rkey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let alive = true;
    setSeries(null);
    if (files['series.json'] && rkey) loadSeries(rkey, files['series.json']).then((x) => { if (alive) setSeries(x); }).catch(() => undefined);
    return () => { alive = false; };
  }, [rkey]); // eslint-disable-line react-hooks/exhaustive-deps
  const dur = sum.duration_s ?? st.motion?.duration ?? 1;
  const nonGround = (pid: string) => pid !== 'ground';

  return (
    <>
      <div className="sect">Results</div>
      <MotionNumbers sum={sum} names={names} />
      {rows.map((r) => (
        <div key={r.id} className="kv" style={{ alignItems: 'baseline' }}>
          <span>{r.label || r.id}<span className="muted" style={{ fontSize: 11 }}>{r.range ? ` · ${r.range[0].toFixed(1)} to ${r.range[1].toFixed(1)} ${r.range_unit}` : ''}</span></span>
          <b>{fmt(r.peak_force_n, 'N')} <span className="muted" style={{ fontWeight: 400 }}>at {r.peak_at_s.toFixed(2)} s</span></b>
        </div>
      ))}
      {(sum.drivers ?? []).map((d) => (
        <div key={d.mate} className="kv"><span>Driver effort, {rows.find((r) => r.id === d.mate)?.label || d.mate}</span><b>{fmt(d.peak_effort, d.effort_unit)} peak · {fmt(d.rms_effort, d.effort_unit)} rms</b></div>
      ))}

      {series && plotMate && <ForcePlot series={series} mate={plotMate} rows={rows} onMate={setPlotMate} dur={dur} />}

      <div className="playrow">
        <button className="pillbtn" disabled={s.motionPreview} onClick={() => useApp.setState({ playing: !s.playing })}>{s.playing ? 'Pause' : 'Play'}</button>
        <input type="range" min={0} max={dur} step={dur / 500} value={Math.min(s.motionT, dur)} aria-label="Time" style={{ flex: 1, accentColor: '#111' }}
          onChange={(e) => { clock.t = Number(e.target.value); useApp.setState({ motionT: clock.t, playing: false }); }} />
        <select aria-label="Playback speed" value={s.motionSpeed} style={{ height: 28 }} onChange={(e) => useApp.setState({ motionSpeed: Number(e.target.value) })}>
          {SPEEDS.map((x) => <option key={x} value={x}>{x}×</option>)}
        </select>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>t = {Math.min(s.motionT, dur).toFixed(2)} s of {dur} s</span>

      <div className="sect">Use a bearing load</div>
      <span className="muted" style={{ fontSize: 12 }}>Makes a static stress study of the part, loaded with the joint's peak force and held at its other joints.</span>
      <div className="simadd">
        {rows.filter((r) => r.type !== 'fixed').flatMap((r) => Object.keys(r.peak_force_on).filter(nonGround).map((pid) => (
          <button key={`${r.id}:${pid}`} className={cx('pillbtn', peak?.mate === r.id && peak.part === pid && 'dark')} onClick={() => useBearingLoad(st.id, r.id, pid)}>
            {r.label || r.id} on {names[pid] ?? pid} ({fmt(r.peak_force_n, 'N')})
          </button>
        )))}
      </div>

      {sum.sweep && <SweepResults sum={sum} />}

      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
        {(sum.steps ?? 0).toLocaleString()} steps · solved in {sum.timing_s.total.toFixed(1)} s on {targetName(sum.target)} with {sum.solver.name} {sum.solver.version ?? ''}
        {files['model.xml'] && <> · <a href={assetUrl(files['model.xml'])} download="model.xml">MJCF model</a></>}
      </p>
      {sum.warnings.map((w) => <p key={w} className="simnote">{w}</p>)}
    </>
  );
}

/** Headline numbers (also used on the floating result card). */
export function MotionNumbers({ sum, names }: { sum: StudySummary; names: Record<string, string> }) {
  const p = sum.peak_bearing;
  return (
    <>
      <div className="kv"><span>Peak bearing load</span><b>{p ? fmt(p.force_n, 'N') : '–'}</b></div>
      {p && <div className="kv"><span>at</span><span>{p.label || p.mate}{p.part ? `, on ${names[p.part] ?? p.part}` : ''}, t = {p.at_s.toFixed(2)} s</span></div>}
      {(sum.loop_error_mm ?? 0) > 0 && <div className="kv"><span>Loop closure</span><span>within {fmt(sum.loop_error_mm ?? 0, 'mm')}</span></div>}
    </>
  );
}

function ForcePlot({ series, mate, rows, onMate, dur }: { series: MotionSeries; mate: string; rows: NonNullable<StudySummary['mates']>; onMate: (m: string) => void; dur: number }) {
  const t = useApp((s) => s.motionT);
  const W = 280, H = 110, pad = 4;
  const ys = series.mates[mate]?.force_mag ?? [];
  const max = Math.max(1e-9, ...ys);
  const path = useMemo(() => ys.map((y, i) => `${i ? 'L' : 'M'}${(pad + (series.t[i] / dur) * (W - 2 * pad)).toFixed(1)},${(H - pad - (y / max) * (H - 2 * pad)).toFixed(1)}`).join(''), [ys, max, series.t, dur]);
  const x = pad + (Math.min(t, dur) / dur) * (W - 2 * pad);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
      <select aria-label="Joint shown in the plot" value={mate} style={{ height: 28, alignSelf: 'flex-start' }} onChange={(e) => onMate(e.target.value)}>
        {rows.map((r) => <option key={r.id} value={r.id}>Bearing load: {r.label || r.id}</option>)}
      </select>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Bearing load over time, peak ${fmt(max, 'N')}`} style={{ background: 'var(--panel2, #f6f6f4)', borderRadius: 8 }}>
        <path d={path} fill="none" stroke="#1D4ED8" strokeWidth={1.5} />
        <line x1={x} x2={x} y1={0} y2={H} stroke="#D9480F" strokeWidth={1} />
        <text x={W - pad} y={12} textAnchor="end" fontSize={10} fill="currentColor">{fmt(max, 'N')}</text>
        <text x={W - pad} y={H - 6} textAnchor="end" fontSize={10} fill="currentColor">{dur.toFixed(1)} s</text>
      </svg>
    </div>
  );
}

function SweepResults({ sum }: { sum: StudySummary }) {
  const sw = sum.sweep!;
  const mate = sum.peak_bearing?.mate ?? null;
  const vals = sw.rows.map((r) => sweepPeak(r, mate));
  const ok = vals.filter((x): x is number => x !== null);
  const max = Math.max(1e-9, ...ok);
  const W = 280, H = 80, pad = 6;
  const xs = sw.rows.map((r) => r.value);
  const lo = Math.min(...xs), hi = Math.max(...xs), span = hi - lo || 1;
  const pts = sw.rows.map((r, i) => (vals[i] === null ? null : [pad + ((r.value - lo) / span) * (W - 2 * pad), H - pad - ((vals[i] as number) / max) * (H - 2 * pad)])).filter(Boolean) as number[][];
  return (
    <>
      <div className="sect">Sweep: {sw.parameter}</div>
      <span className="muted" style={{ fontSize: 12 }}>
        {sw.variants} variants in {sw.wall_s.toFixed(1)} s on {sw.backend === 'mujoco_warp' ? `MuJoCo Warp (${sw.device})` : 'a CPU process pool'}{sw.failed ? ` · ${sw.failed} unstable` : ''}
      </span>
      {pts.length > 1 && (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Peak bearing load over the sweep" style={{ background: 'var(--panel2, #f6f6f4)', borderRadius: 8 }}>
          <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="#1D4ED8" strokeWidth={1.5} />
          {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={2.5} fill="#1D4ED8" />)}
        </svg>
      )}
      <table className="simtable" style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
        <thead><tr><th style={{ textAlign: 'left' }}>Value</th><th style={{ textAlign: 'right' }}>Peak load{mate ? ` (${mate})` : ''}</th><th style={{ textAlign: 'right' }}>Peak effort</th></tr></thead>
        <tbody>
          {sw.rows.map((r, i) => (
            <tr key={i}>
              <td>{r.value}</td>
              <td style={{ textAlign: 'right' }}>{r.ok ? fmt(vals[i] ?? 0, 'N') : <span className="simbad" title={r.error}>failed</span>}</td>
              <td style={{ textAlign: 'right' }}>{r.ok && r.peak_effort ? Object.values(r.peak_effort).map((e) => fmt(e)).join(', ') || '–' : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
