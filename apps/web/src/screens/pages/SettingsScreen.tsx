import { useState } from 'react';
import { SETTINGS_DEF } from '../../data/seed';
import type { SettingRow } from '../../data/types';
import { defaultSettings, useApp } from '../../state/store';
import { cx, Segmented, Switch } from '../../components/ui';

function fmt(r: SettingRow, v: number) {
  if (r.fmt === 'pct') return `${v} %`;
  if (r.fmt === 'sf') return v.toFixed(1);
  if (r.fmt === 'x') return `${v.toFixed(1)}×`;
  return String(v);
}

/** Settings. Values live in the app store for now and reset on reload. */
export function SettingsScreen() {
  const settings = useApp((s) => s.settings);
  const set = useApp((s) => s.set);
  const [section, setSection] = useState(SETTINGS_DEF[0].id);
  const cur = SETTINGS_DEF.find((x) => x.id === section) ?? SETTINGS_DEF[0];
  const put = (key: string, v: string | number | boolean) => set({ settings: { ...settings, [key]: v } });

  return (
    <main className="home" aria-label="Settings">
      <div className="homehead">
        <div><h1>Settings</h1><p className="muted">Changes save automatically.</p></div>
        <button className="pillbtn" onClick={() => set({ settings: defaultSettings() })}>Reset to defaults</button>
      </div>
      <div className="setwrap">
        <nav className="setnav" aria-label="Settings sections">
          {SETTINGS_DEF.map((x) => <button key={x.id} className={cx(x.id === section && 'on')} aria-current={x.id === section} onClick={() => setSection(x.id)}>{x.title}</button>)}
        </nav>
        <section className="pcardx setpanel" aria-label={cur.title}>
          <h2>{cur.title}</h2>
          <p className="muted" style={{ margin: '-6px 0 10px', fontSize: 13 }}>{cur.intro}</p>
          {cur.rows.map((r) => {
            const v = settings[r.key];
            return (
              <div key={r.key} className="srow">
                <div className="slabel"><b>{r.label}</b><span className="muted">{r.help}</span></div>
                <div className="sctl">
                  {r.type === 'toggle' && <Switch on={!!v} label={r.label} onToggle={() => put(r.key, !v)} />}
                  {r.type === 'seg' && <Segmented options={r.opts ?? []} value={String(v)} onChange={(o) => put(r.key, o)} label={r.label} />}
                  {r.type === 'select' && (
                    <select aria-label={r.label} value={String(v)} onChange={(e) => put(r.key, e.target.value)}>{(r.opts ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</select>
                  )}
                  {r.type === 'text' && <input className="stext" aria-label={r.label} value={String(v)} onChange={(e) => put(r.key, e.target.value)} />}
                  {r.type === 'range' && (
                    <div className="srange">
                      <input type="range" aria-label={r.label} min={r.min} max={r.max} step={r.step} value={Number(v)} onChange={(e) => put(r.key, Number(e.target.value))} />
                      <span>{fmt(r, Number(v))}</span>
                    </div>
                  )}
                  {r.type === 'connect' && <button className={cx('connbtn', !!v && 'on')} onClick={() => put(r.key, !v)}>{v ? 'Connected' : 'Connect'}</button>}
                </div>
              </div>
            );
          })}
        </section>
      </div>
    </main>
  );
}
