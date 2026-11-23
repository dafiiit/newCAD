import { MODE_NAMES, MODES, PROPS, STUDIES } from '../../data/seed';
import { useApp, type AppState } from '../../state/store';
import { cx } from '../../components/ui';
import { EngineCheckPanel, EngineResultOverlay } from './EngineCheck';

type KV = { k: string; v: string };

/** Mock setup, results and legend for the selected study on the current version. All values are placeholders. */
export function studyView(s: AppState) {
  const S0 = STUDIES.find((x) => x.id === s.study) ?? STUDIES[0];
  const done = !!s.studyDone[`${S0.id}:${s.version}`];
  const P = PROPS[s.version];
  const freqs = MODES[s.version];
  const fx = s.rpm / 60;
  const peakN = Math.round(180 + s.rpm * 0.9);
  const by = (m: Record<number, string>) => m[s.version];
  const setup: Record<string, KV[]> = {
    static: [{ k: 'Fixed', v: '4 base bolts' }, { k: 'Load', v: '4 kg × 3 g at flange' }, { k: 'Materials', v: 'from parts' }],
    modal: [{ k: 'Fixed', v: '4 base bolts' }, { k: 'Excitation', v: `${s.rpm} rpm = ${fx.toFixed(1)} Hz` }, { k: 'Modes', v: '3' }],
    motion: [{ k: 'Joint', v: 'Revolute: shaft ↔ generator' }, { k: 'Drive', v: 'Torque ramp to target speed' }, { k: 'Bracket', v: 'Fixed body (welded)' }],
    thermal: [{ k: 'Heat source', v: 'Generator, 60 W' }, { k: 'Ambient', v: 'Water, 12 °C' }, { k: 'Contact', v: 'Flange to upright' }],
    vibration: [{ k: 'Excitation', v: 'Rotor imbalance, 0–80 Hz' }, { k: 'Operating point', v: `${fx.toFixed(1)} Hz` }, { k: 'Damping', v: '2 % (steel, welded)' }],
    cfd: [{ k: 'Inflow', v: '1.5 m/s, fresh water' }, { k: 'Domain', v: '2 × 1 × 1 m around the rig' }, { k: 'Turbulence', v: 'k-ω SST' }],
    soft: [{ k: 'Soft parts', v: '4 rubber pads, Shore 60A' }, { k: 'Fluid', v: 'Water as viscous damping' }, { k: 'Drive', v: `Run-up to ${s.rpm} rpm` }],
  };
  const results: Record<string, KV[]> = {
    static: [{ k: 'Peak von Mises', v: P.stress }, { k: 'Safety factor', v: `${P.sf} (target ${Number(s.settings.sfTarget).toFixed(1)})` }, { k: 'Max deflection', v: `${by({ 1: '0.41', 2: '0.18', 3: '0.29' })} mm` }],
    modal: [{ k: 'First mode', v: `${freqs[0]} Hz` }, { k: 'Excitation', v: `${fx.toFixed(1)} Hz` }, { k: 'Margin', v: `${(freqs[0] / fx).toFixed(1)}× ${freqs[0] / fx > 3 ? '(safe)' : '(too close)'}` }],
    motion: [{ k: 'Peak bearing load', v: `${peakN} N` }, { k: 'Speed reached after', v: '2.4 s' }, { k: 'Max bracket reaction', v: `${Math.round(peakN * 0.6)} N` }],
    thermal: [{ k: 'Max bracket temperature', v: `${by({ 1: '22', 2: '21', 3: '24' })} °C` }, { k: 'Generator housing', v: '38 °C' }],
    vibration: [{ k: `Peak amplitude at ${fx.toFixed(0)} Hz`, v: `${by({ 1: '0.12', 2: '0.05', 3: '0.08' })} mm` }, { k: 'Resonance peak', v: `${freqs[0]} Hz` }, { k: 'Dynamic stress', v: `${by({ 1: '31', 2: '14', 3: '22' })} MPa` }],
    cfd: [{ k: 'Drag on the mount', v: `${by({ 1: '42', 2: '47', 3: '39' })} N` }, { k: 'Lift / side force', v: '6 N' }, { k: 'Max flow speed', v: '2.3 m/s at the upright edge' }],
    soft: [{ k: 'Vibration into the rig', v: '−38 % with pads' }, { k: 'Max pad compression', v: '1.1 mm' }, { k: 'Settling after run-up', v: '0.8 s' }],
  };
  const legend: Record<string, [string, string, string]> = {
    static: ['low', 'von Mises stress', 'high'], modal: ['0', 'displacement (exaggerated)', 'max'], thermal: ['12 °C', 'temperature', '38 °C'],
    vibration: ['0', 'vibration amplitude', 'max'], cfd: ['−', 'surface pressure', '+'], soft: ['0', 'contact pressure', 'max'],
  };
  const running = s.studyRun === S0.id;
  return {
    S0, done, running, setup: setup[S0.id], results: results[S0.id], legend: done ? legend[S0.id] : undefined,
    badge: running ? 'Running…' : done ? `${S0.group} · done` : S0.group,
    runLabel: running ? 'Running…' : done ? 'Re-run' : `Run ${S0.title.toLowerCase()}`,
    animated: done && (S0.id === 'modal' || S0.id === 'motion'),
    freqs,
  };
}

function Legend({ lo, q, hi }: { lo: string; q: string; hi: string }) {
  return (
    <>
      <div className="legend truecol" />
      <div className="legendlbl"><span>{lo}</span><span>{q}</span><span>{hi}</span></div>
    </>
  );
}

function PlayRow({ info }: { info: string }) {
  const playing = useApp((s) => s.playing);
  const set = useApp((s) => s.set);
  return (
    <div className="playrow">
      <button className="pillbtn" onClick={() => set({ playing: !playing })}>{playing ? 'Pause' : 'Play'}</button>
      <span className="muted" style={{ fontSize: 12 }}>{info}</span>
    </div>
  );
}

/** Bearing-load trace for the MuJoCo run-up (mock curve). */
function loadPlot() {
  let d = '';
  for (let i = 0; i <= 52; i++) {
    const t = (i / 52) * 10;
    const L = (1 - Math.exp(-t / 0.8)) * (1 + 0.06 * Math.sin(2 * Math.PI * 1.3 * t)) + (t < 1.2 ? 0.25 * Math.sin((Math.PI * t) / 1.2) : 0);
    d += `${i ? ' L' : 'M'}${((i / 52) * 260).toFixed(1)} ${(66 - L * 50).toFixed(1)}`;
  }
  return d;
}
const PLOT = loadPlot();

export function CheckPanel() {
  const live = useApp((x) => !!x.eng);
  return live ? <EngineCheckPanel /> : <MockCheckPanel />;
}

function MockCheckPanel() {
  const s = useApp();
  const v = studyView(s);
  const groups: { title: string; items: typeof STUDIES }[] = [];
  for (const st of STUDIES) {
    let g = groups.find((x) => x.title === st.group);
    if (!g) { g = { title: st.group, items: [] }; groups.push(g); }
    g.items.push(st);
  }
  const animInfo = v.S0.id === 'motion' ? 'MuJoCo playback 0.1×' : `Mode ${s.mode} · ${v.freqs[s.mode - 1]} Hz · shape exaggerated`;

  return (
    <>
      {groups.map((g) => (
        <div key={g.title} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div className="sect">{g.title}</div>
          {g.items.map((st) => {
            const run = s.studyRun === st.id, dn = !!s.studyDone[`${st.id}:${s.version}`];
            return (
              <button key={st.id} className={cx('stitem', s.study === st.id && 'on')} onClick={() => s.set({ study: st.id })}>
                <span className="sticon">{st.icon}</span>
                <span className="stbody"><b>{st.title}</b><span className="muted">{st.sub}</span></span>
                <span className={cx('stbadge', run && 'run', !run && dn && 'done')}>{run ? 'Running' : dn ? 'Done' : 'Not run'}</span>
              </button>
            );
          })}
        </div>
      ))}
      <button className="linkbtn" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => { s.set({ chatOpen: true, chatText: 'New study: ' }); }}>+ New study</button>

      <div className="detail checkdetail">
        <h3>{v.S0.title}</h3>
        <span className="muted" style={{ fontSize: 12 }}>{v.S0.engine}</span>
        {v.setup.map((kv) => <div key={kv.k} className="kv"><span>{kv.k}</span><span>{kv.v}</span></div>)}
        {v.S0.id === 'motion' && (
          <>
            <label className="rpmlbl" htmlFor="rpm">Rotor speed <b>{s.rpm} rpm</b></label>
            <input id="rpm" type="range" min={50} max={600} step={10} value={s.rpm} onChange={(e) => s.set({ rpm: Number(e.target.value) })} style={{ accentColor: '#111' }} />
          </>
        )}
        <button className="pillbtn dark" disabled={!!s.studyRun} onClick={() => s.runStudy(v.S0.id)}>{v.runLabel}</button>
        {v.done && (
          <>
            <div className="sect">Results</div>
            {v.results.map((kv) => <div key={kv.k} className="kv"><span>{kv.k}</span><b>{kv.v}</b></div>)}
            {v.S0.id === 'modal' && (
              <div className="modes">
                {v.freqs.map((f, i) => (
                  <button key={i} className={cx('mode', s.mode === i + 1 && 'on')} onClick={() => s.set({ mode: i + 1 })}>
                    <b>Mode {i + 1}</b><span>{f} Hz</span><span className="muted">{MODE_NAMES[i]}</span>
                  </button>
                ))}
              </div>
            )}
            {v.S0.id === 'motion' && (
              <div className="plot" aria-label="Bearing load over time">
                <svg viewBox="0 0 260 70" width="100%" height="70" aria-hidden="true"><path d={PLOT} fill="none" stroke="#1D4ED8" strokeWidth="2" /></svg>
                <div className="legendlbl"><span>0 s</span><span>bearing load</span><span>10 s</span></div>
              </div>
            )}
            {v.animated && <PlayRow info={animInfo} />}
            {v.legend && <Legend lo={v.legend[0]} q={v.legend[1]} hi={v.legend[2]} />}
          </>
        )}
        <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>Results are mock values for the prototype.</p>
      </div>
    </>
  );
}

/** Floating card on the 3D view with the selected study's state. */
export function ResultOverlay() {
  const live = useApp((x) => !!x.eng);
  return live ? <EngineResultOverlay /> : <MockResultOverlay />;
}

function MockResultOverlay() {
  const s = useApp();
  const v = studyView(s);
  return (
    <div className="resov" aria-label="Study result">
      <div className="resovhead">
        <span className="sticon">{v.S0.icon}</span>
        <span className="resovt"><b>{v.S0.title}</b><span className="muted">{v.badge}</span></span>
      </div>
      {v.done ? (
        <>
          {v.legend && <Legend lo={v.legend[0]} q={v.legend[1]} hi={v.legend[2]} />}
          {v.results.map((kv) => <div key={kv.k} className="kv"><span>{kv.k}</span><b>{kv.v}</b></div>)}
          {v.animated && <PlayRow info={v.S0.id === 'motion' ? 'MuJoCo playback 0.1×' : `Mode ${s.mode} · ${v.freqs[s.mode - 1]} Hz`} />}
        </>
      ) : (
        <>
          <p className="muted" style={{ margin: '2px 0 8px', fontSize: 13 }}>{v.S0.sub}. Not run on this version yet.</p>
          <button className="pillbtn dark" disabled={!!s.studyRun} onClick={() => s.runStudy(v.S0.id)}>{v.runLabel}</button>
        </>
      )}
    </div>
  );
}
