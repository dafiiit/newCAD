import { useEffect, useState } from 'react';
import { api, assetUrl } from '../../engine/client';
import { applyBranch, branchFrom, compareCommit, fullId } from '../../engine/sync';
import { LIB_CATS, LIBRARY, PROPS } from '../../data/seed';
import { buildModel, massProps } from '../../model/parts';
import { ModelThumb } from '../../model/ModelThumb';
import { useApp } from '../../state/store';
import { CloseIcon, CubeIcon } from '../../components/icons';
import { cx, Modal, QBox, Segmented } from '../../components/ui';

/** Versions & branches: a git graph of every change by you or Bot. */
export function VersionHistory() {
  const s = useApp();
  const close = () => s.set({ review: false });
  const ROW = 56, LANE = 22;
  const lanes: Record<string, number> = {};
  let laneN = 0;
  for (const c of s.commits) if (lanes[c.branch] === undefined) lanes[c.branch] = c.branch === 'main' ? 0 : ++laneN;
  const ordered = s.commits.slice().reverse();
  const pos: Record<string, { x: number; y: number }> = {};
  ordered.forEach((c, r) => { pos[c.id] = { x: 14 + lanes[c.branch] * LANE, y: r * ROW + ROW / 2 }; });
  const colorOf = (b: string) => s.branchColors[b] ?? '#111';
  const gw = 28 + laneN * LANE, gh = ordered.length * ROW;
  const edges = s.commits.flatMap((c) => c.parents.map((pid, k) => {
    const a = pos[c.id], b = pos[pid];
    if (!b) return null;
    const col = k === 0 ? colorOf(c.branch) : colorOf(s.commits.find((q) => q.id === pid)?.branch ?? 'main');
    const my = (a.y + b.y) / 2;
    return { d: a.x === b.x ? `M${a.x} ${a.y} L${b.x} ${b.y}` : `M${a.x} ${a.y} C${a.x} ${my} ${b.x} ${my} ${b.x} ${b.y}`, color: col, key: `${c.id}-${pid}` };
  })).filter((e): e is NonNullable<typeof e> => !!e);
  const tips: Record<string, string> = {};
  for (const c of s.commits) tips[c.branch] = c.id;
  const sel = s.commits.find((c) => c.id === s.selCommit) ?? s.commits[s.commits.length - 1];
  const live = !!s.eng?.log;
  useEffect(() => { if (live && sel) void compareCommit(sel.id); }, [live, sel?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!sel) return null;
  const P = PROPS[sel.ver];
  const num = live ? s.eng!.compare[sel.id] : undefined;
  const headBranch = s.eng?.log?.headBranch ?? null;
  const isTip = live && s.eng!.log!.tips[sel.branch] === fullId(sel.id);

  return (
    <Modal label="Version history" onClose={close}>
      <div className="modalhead">
        <div style={{ marginRight: 'auto' }}><h2>Versions &amp; branches</h2><p>Every change by you or Bot is a version. Concepts live on their own branches.{live ? ' Mass is measured by the engine; stress and cost arrive with the Check phase.' : ' Values are mock data.'}</p></div>
        <button className="iconbtn" aria-label="Close history" onClick={close}><CloseIcon size={20} color="#111" /></button>
      </div>
      <div className="branchbar">
        <span className="muted" style={{ fontSize: 12 }}>Branches</span>
        {Object.keys(tips).map((b) => (
          <button key={b} className="bchip" onClick={() => s.set({ selCommit: tips[b] })}>
            <span className="bdot truecol" style={{ background: colorOf(b) }} />{b}<span className="muted">{s.commits.filter((c) => c.branch === b).length}</span>
          </button>
        ))}
      </div>
      <div className="histgrid">
        <div className="histlist">
          <div className="graph" style={{ width: gw, height: gh }}>
            <svg className="layer truecol" viewBox={`0 0 ${gw} ${gh}`} aria-hidden="true">
              {edges.map((e) => <path key={e.key} d={e.d} fill="none" stroke={e.color} strokeWidth="2.5" />)}
              {ordered.map((c) => {
                const p = pos[c.id], hd = c.id === s.head;
                return <circle key={c.id} cx={p.x} cy={p.y} r={hd ? 7 : 5.5} fill={hd ? colorOf(c.branch) : '#fff'} stroke={colorOf(c.branch)} strokeWidth="2.5" />;
              })}
            </svg>
          </div>
          <div className="rows">
            {ordered.map((c) => (
              <button key={c.id} className={cx('crow', c.id === s.selCommit && 'on')} onClick={() => s.set({ selCommit: c.id })}>
                <span className="rmsg">{c.msg}</span>
                <span className="rmeta">
                  <span className="btag" style={{ borderColor: colorOf(c.branch), color: colorOf(c.branch) }}>{c.branch}</span>
                  {c.id === s.head && <span className="headtag">HEAD</span>}
                  <span className="muted">{c.id} · {c.who} · {c.t}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
        <aside className="histdetail">
          <div className="thumb">{live ? <img className="histthumb" alt={`Model at ${sel.id}`} src={assetUrl(`/api/projects/${s.eng!.pid}/snapshot.png?ref=${fullId(sel.id)}&w=480&h=320`)} /> : <ModelThumb version={sel.ver} />}</div>
          <div className="ptitle">
            <span className="btag" style={{ borderColor: colorOf(sel.branch), color: colorOf(sel.branch) }}>{sel.branch}</span>
            <span className="muted" style={{ fontSize: 12 }}>{sel.id} · {sel.who} · {sel.t}</span>
          </div>
          <h3 style={{ margin: 0, fontSize: 17 }}>{sel.msg}</h3>
          <p className="diff">{sel.diff || '—'}</p>
          <div className="metrics">
            <div className="metric"><span>Mass</span><b>{live ? (num ? (!num.ok ? 'build error' : num.mass_kg > 0 ? `${num.mass_kg.toFixed(2)} kg` : 'no parts') : '…') : `${massProps(buildModel(sel.ver)).bracket.toFixed(2)} kg`}</b></div>
            <div className="metric"><span>Safety factor</span><b>{live ? '—' : P.sf}</b></div>
            <div className="metric"><span>Peak stress</span><b>{live ? '—' : P.stress}</b></div>
            <div className="metric"><span>Part cost</span><b>{live ? '—' : P.cost}</b></div>
          </div>
          <div className="pactions" style={{ flexWrap: 'wrap' }}>
            <button className="pillbtn dark" onClick={() => { s.checkout(sel.id); s.showToast(live && isTip ? `Checked out ${sel.branch}` : `Checked out ${sel.branch} @ ${sel.id}`); }}>{sel.id === s.head ? 'Checked out' : 'Check out this version'}</button>
            {live && isTip && headBranch && sel.branch !== headBranch && (
              <button className="pillbtn" onClick={() => void applyBranch(sel.branch)}>Apply {sel.branch} to {headBranch}</button>
            )}
            <button className="pillbtn" onClick={() => {
              if (live) { void branchFrom(sel.id); return; }
              const name = `concept-${String.fromCharCode(97 + Object.keys(s.branchColors).length)}`;
              s.addCommit({ branch: name, from: sel.id, ver: sel.ver, msg: `Branch ${name} from ${sel.id}`, who: 'You', diff: 'no geometry change yet' });
              s.showToast(`Created ${name}`);
            }}>Branch from here</button>
            <button className="pillbtn" onClick={() => s.set({ review: false, chatOpen: true, chatText: `Changes to ${sel.id}: ` })}>Ask for changes</button>
          </div>
        </aside>
      </div>
    </Modal>
  );
}

const LIB_ICONS: Record<string, React.ReactNode> = {
  bolt: <svg width="90" height="70" viewBox="0 0 90 70" fill="none" stroke="#111" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="M8 22h16v26H8z" fill="#fff" /><path d="M24 28h56v14H24z" fill="#fff" /><path d="M32 28l-3 14M40 28l-3 14M48 28l-3 14M56 28l-3 14M64 28l-3 14M72 28l-3 14" /></svg>,
  nut: <svg width="70" height="70" viewBox="0 0 70 70" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><path d="M35 8l23 13v28L35 62 12 49V21z" fill="#fff" /><circle cx="35" cy="35" r="11" /></svg>,
  profile: <svg width="80" height="80" viewBox="0 0 80 80" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><path d="M12 12h56v56H12z" fill="#fff" /><path d="M34 12v10h12V12M34 68V58h12v10M12 34h10v12H12M68 34H58v12h10" /><circle cx="40" cy="40" r="6" /></svg>,
  bearing: <svg width="80" height="80" viewBox="0 0 80 80" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><circle cx="40" cy="40" r="30" fill="#fff" /><circle cx="40" cy="40" r="12" /><circle cx="40" cy="19" r="5" /><circle cx="58" cy="30" r="5" /><circle cx="58" cy="50" r="5" /><circle cx="40" cy="61" r="5" /><circle cx="22" cy="50" r="5" /><circle cx="22" cy="30" r="5" /></svg>,
  motor: <svg width="90" height="70" viewBox="0 0 90 70" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><path d="M14 14h44v42H14z" fill="#fff" /><path d="M58 30h20v10H58z" /><path d="M14 24h44M14 46h44" /></svg>,
  robot: <svg width="90" height="80" viewBox="0 0 90 80" fill="none" stroke="#111" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 72h32" strokeWidth="3" /><path d="M30 72V54" /><circle cx="30" cy="50" r="5" fill="#fff" /><path d="M30 50l18-22" /><circle cx="48" cy="26" r="5" fill="#fff" /><path d="M48 26l22 8" /><path d="M70 34l6-6M70 34l6 6" /></svg>,
  gear: <svg width="80" height="80" viewBox="0 0 100 100" fill="none" stroke="#111" strokeWidth="2" aria-hidden="true"><path d="M50 14l6 10 11-4 2 12 12 3-4 11 10 6-10 6 4 11-12 3-2 12-11-4-6 10-6-10-11 4-2-12-12-3 4-11-10-6 10-6-4-11 12-3 2-12 11 4z" fill="#fff" /><circle cx="50" cy="50" r="12" /></svg>,
  assembly: <svg width="90" height="80" viewBox="0 0 90 80" fill="none" stroke="#111" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="M16 66V26l12-6v40l50 0-12 6z" fill="#fff" /><circle cx="54" cy="38" r="14" fill="#fff" /><path d="M68 38h12" /></svg>,
};

/** Full-screen part library: standard parts, catalogue parts and community assemblies. */
export function PartLibrary() {
  const s = useApp();
  const [cat, setCat] = useState(LIB_CATS[0]);
  const [query, setQuery] = useState('');
  const [selId, setSelId] = useState<string | null>(null);
  const [variant, setVariant] = useState<Record<string, string>>({});
  const [qty, setQty] = useState(1);
  const q = query.toLowerCase().trim();
  const items = LIBRARY.filter((x) => (q ? `${x.name} ${x.std} ${x.spec} ${x.cat}`.toLowerCase().includes(q) : x.cat === cat));
  const sel = LIBRARY.find((x) => x.id === selId) ?? null;
  const v = sel ? variant[sel.id] ?? sel.variants[0] : '';
  const catIdx = LIB_CATS.indexOf(cat);

  return (
    <div className="libscreen" role="dialog" aria-label="Part library">
      <header className="libhead">
        <h2>Part library</h2>
        <input className="libsearch" aria-label="Search parts" placeholder="Search screws, profiles, motors, robots…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="iconbtn" aria-label="Close part library" onClick={() => s.set({ libOpen: false })}><CloseIcon size={20} color="#111" /></button>
      </header>
      <div className="libbody">
        <nav className="libnav" aria-label="Categories">
          <div className="libcats">
            <span className="libsl" aria-hidden="true" style={{ transform: `translateY(${catIdx * 42}px)`, opacity: q ? 0 : 1 }} />
            {LIB_CATS.map((c) => (
              <button key={c} className={cx('libcat', !q && c === cat && 'on')} onClick={() => { setCat(c); setQuery(''); }}>
                <span>{c}</span><span className="muted">{LIBRARY.filter((x) => x.cat === c).length}</span>
              </button>
            ))}
          </div>
        </nav>
        <section className="libgrid" aria-label="Parts">
          {items.map((it) => (
            <button key={it.id} className={cx('libcard', selId === it.id && 'on')} onClick={() => setSelId(it.id)}>
              <div className="libthumb">{LIB_ICONS[it.icon]}<span className="libstd">{it.std}</span></div>
              <b>{it.name}</b><span className="muted">{it.spec}</span>
            </button>
          ))}
          {!items.length && <p className="muted">No parts match “{query}”.</p>}
        </section>
        <aside className="libdetail" aria-label="Part details">
          {sel ? (
            <>
              <h3>{sel.name}</h3>
              <span className="muted" style={{ fontSize: 13 }}>{sel.std} · {sel.source}</span>
              <label className="sect" htmlFor="libvariant">Variant</label>
              <select id="libvariant" value={v} onChange={(e) => setVariant({ ...variant, [sel.id]: e.target.value })}>{sel.variants.map((x) => <option key={x} value={x}>{x}</option>)}</select>
              <div className="kv"><span>Material</span><span>{sel.material}</span></div>
              <div className="kv"><span>Mass</span><span>{sel.mass}</span></div>
              <div className="kv"><span>Files</span><span>STEP · STL · build123d</span></div>
              <label className="sect" htmlFor="libqty">Quantity</label>
              <input id="libqty" className="stext" type="number" min={1} value={qty} onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))} style={{ width: 90 }} />
              <button className="pillbtn dark" onClick={() => {
                s.set({ libParts: [...s.libParts, { id: `lib-${sel.id}-${Date.now()}`, name: sel.name, variant: v, qty }], libOpen: false, howTab: 'parts' });
                s.showToast(`${qty} × ${sel.name} (${v}) added to ${s.projectName}`);
              }}>Insert into {s.projectName}</button>
              <button className="pillbtn" onClick={() => s.set({ libOpen: false, chatOpen: true, chatText: `Where should I use the ${sel.name} (${v})?` })}>Ask Bot where to use it</button>
            </>
          ) : <p className="muted">Pick a part to see its variants and insert it.</p>}
        </aside>
      </div>
    </div>
  );
}

const ASSEMBLIES = [
  { name: 'Sensor bracket', meta: 'Your project · 1 branch' },
  { name: 'Gripper finger', meta: 'Your project · 4 branches' },
  { name: 'Pump housing cover', meta: 'Your project · 2 branches' },
];

export function AssemblyPicker() {
  const s = useApp();
  const close = () => s.set({ asmPick: false });
  return (
    <Modal label="Add another assembly" onClose={close} className="asmbox">
      <div className="modalhead">
        <div style={{ marginRight: 'auto' }}><h2>Add other assembly</h2><p>Bring in one of your projects as a sub-assembly.</p></div>
        <button className="iconbtn" aria-label="Close" onClick={close}><CloseIcon size={20} color="#111" /></button>
      </div>
      {ASSEMBLIES.map((a) => (
        <button key={a.name} className="asmrow" onClick={() => {
          s.set({ asmPick: false, libParts: [...s.libParts, { id: `asm-${Date.now()}`, name: a.name, variant: 'latest', qty: 1 }] });
          s.showToast(`${a.name} added as a sub-assembly`);
        }}>
          <span className="asmthumb"><CubeIcon size={22} color="#111" width={1.6} /></span>
          <span className="asmtx"><b>{a.name}</b><span className="muted">{a.meta}</span></span>
          <span className="asmadd">Add</span>
        </button>
      ))}
    </Modal>
  );
}

const FB_TYPES = ['Bug', 'Idea', 'Question'] as const;

interface FeedbackRecord { id: string; status: 'sent' | 'pending'; issue: { number: number; url: string } | null; error: string | null }

export function FeedbackDialog() {
  const s = useApp();
  const [type, setType] = useState<(typeof FB_TYPES)[number]>('Bug');
  const [text, setText] = useState('');
  const [shot, setShot] = useState(true);
  const [ctx, setCtx] = useState(true);
  const [busy, setBusy] = useState(false);
  const close = () => s.set({ feedbackOpen: false });
  const live = !!s.eng;
  const send = async () => {
    if (!text.trim()) { s.showToast('Write a few words first'); return; }
    if (!live) { s.showToast('Feedback needs the engine. Start it with pnpm dev:engine, then send again.'); return; }
    setBusy(true);
    const context = ctx ? {
      project: s.projectName, projectId: s.eng?.pid ?? undefined, branch: s.eng?.log?.headBranch ?? undefined,
      head: s.head, screen: s.layer, browser: navigator.userAgent,
    } : undefined;
    try {
      const r = await api<FeedbackRecord>('/api/feedback', { body: { type, text, context, screenshot: shot, project: s.eng?.pid ?? null, ref: s.eng?.log?.headBranch ?? null } });
      close();
      s.showToast(r.status === 'sent' && r.issue ? `${type} filed as issue #${r.issue.number}. Thank you!` : `${type} saved on this computer. It goes to GitHub once the engine can reach it.`);
    } catch (e) {
      s.showToast(`Could not send feedback: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal label="Send developer feedback" onClose={close} className="fbbox">
      <div className="modalhead">
        <div style={{ marginRight: 'auto' }}><h2>Send developer feedback</h2><p>Filed as an issue in the NewCAD repo on GitHub. Thank you!</p></div>
        <button className="iconbtn" aria-label="Close" onClick={close}><CloseIcon size={20} color="#111" /></button>
      </div>
      <Segmented options={FB_TYPES} value={type} onChange={setType} label="Feedback type" />
      <textarea className="fbtext" aria-label="Your feedback" placeholder="What happened, or what would you like to see?" value={text} onChange={(e) => setText(e.target.value)} />
      <button className="fbcheck" role="checkbox" aria-checked={shot} onClick={() => setShot(!shot)}><QBox on={shot} />Attach a picture of the current model</button>
      <button className="fbcheck" role="checkbox" aria-checked={ctx} onClick={() => setCtx(!ctx)}><QBox on={ctx} />Include project and version info ({s.projectName} · {s.head})</button>
      <div className="pactions">
        <button className="pillbtn" onClick={close}>Cancel</button>
        <button className="pillbtn dark" disabled={busy} onClick={() => { void send(); }}>{busy ? 'Sending…' : 'Send feedback'}</button>
      </div>
    </Modal>
  );
}
