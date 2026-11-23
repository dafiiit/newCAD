import { useState } from 'react';
import { MATE_TYPES } from '../../data/seed';
import { buildModel, interference, massProps, MATERIAL, modelBounds } from '../../model/parts';
import { useApp, type CutAxis, type Display } from '../../state/store';
import { CheckIcon, CloseIcon, CommentIcon, CursorIcon, DotsIcon, ImageIcon, PanelIcon, PathIcon, PencilIcon, ArrowRight, TrashIcon } from '../../components/icons';
import { ProjectTitle } from '../../components/chrome/TopChrome';
import { DrawerResizer } from '../../components/chrome/DrawerResizer';
import { cx, MenuCheck, QBox, Segmented } from '../../components/ui';
import { ResultOverlay } from '../check/CheckPanel';
import { SolutionDrawer } from './SolutionDrawer';
import { Viewport3D } from './Viewport3D';

const DISPLAY: Record<string, Display> = { Edges: 'edges', Shaded: 'shaded', Wire: 'wire' };
const CUT_AXES = ['X', 'Y', 'Z'] as const;

/** How? (the design) and Check (simulations) share the 3D view, the side panel and the tool rail. */
export function HowScreen() {
  const s = useApp();
  const { set, toggleMenu } = s;
  const isCheck = s.layer === 'check';
  const codeWide = !isCheck && s.expert && s.howTab === 'code';
  const width = codeWide ? s.drawerW.code : s.drawerW.main;

  return (
    <>
      <Viewport3D />
      <ProjectTitle />
      {s.drawer ? (
        <>
          <SolutionDrawer width={width} />
          <DrawerResizer which={codeWide ? 'code' : 'main'} width={width} />
        </>
      ) : (
        <button className="openDrawer" aria-label="Open solution panel" onClick={() => set({ drawer: true })}><PanelIcon /></button>
      )}
      {isCheck && <ResultOverlay />}

      <div className="rail" aria-label="3D tools">
        <button className="round plain" aria-label="View cube: standard views" aria-expanded={s.menu === 'cube'} onClick={() => toggleMenu('cube')} style={{ border: 0 }}>
          <svg width="46" height="46" viewBox="0 0 46 46" fill="none" stroke="#111" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
            <path d="M23 6l15 8v18l-15 8-15-8V14z" fill="#fff" /><path d="M8 14l15 8 15-8M23 22v18" />
            <circle cx="23" cy="22" r="2.6" fill="#111" /><circle cx="8" cy="32" r="2.6" fill="#111" /><circle cx="38" cy="32" r="2.6" fill="#111" /><circle cx="23" cy="6" r="2.6" fill="#111" />
          </svg>
        </button>
        <div className="capsule">
          <span className="vslider" aria-hidden="true" style={{ transform: `translateY(${s.tool === 'comment' ? 200 : s.menu === 'mate' ? 100 : s.menu === 'export' ? 300 : s.menu === 'analysis' || s.analysis ? 500 : 0}%)` }} />
          <button className={cx('rbtn', !s.tool && 'on')} aria-label="Select and orbit" onClick={() => set({ tool: null, menu: null })}><CursorIcon size={20} /></button>
          <button className="rbtn" aria-label="Mates: add a mate connector or mate" aria-expanded={s.menu === 'mate'} onClick={() => toggleMenu('mate')}>
            <PathIcon d="M12 2v5M12 17v5M2 12h5M17 12h5M12 8.5a3.5 3.5 0 1 1 0 7a3.5 3.5 0 1 1 0-7z" size={22} width={1.7} />
          </button>
          <button className={cx('rbtn', s.tool === 'comment' && 'on')} aria-label="Comment on a part with text, sketch or image" disabled={isCheck}
            onClick={() => set({ tool: s.tool === 'comment' ? null : 'comment', menu: null })}><CommentIcon size={20} /></button>
          <button className="rbtn" aria-label="Export" aria-expanded={s.menu === 'export'} onClick={() => toggleMenu('export')}>
            <PathIcon d="M12 15V4M8 8l4-4 4 4M5 11v8h14v-8" size={20} width={1.8} />
          </button>
          <button className="rbtn" aria-label="Measure between two parts" onClick={() => s.showToast('Measure: pick two parts (arrives with the engine’s B-rep picking)')}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="2" y="9" width="20" height="7" rx="1" /><path d="M6 9v3M10 9v4M14 9v3M18 9v4" /></svg>
          </button>
          <button className="rbtn" aria-label="Analysis: interference, mass, centre of gravity" aria-expanded={s.menu === 'analysis'} onClick={() => toggleMenu('analysis')}>
            <PathIcon d="M10.5 4a6.5 6.5 0 1 1 0 13a6.5 6.5 0 1 1 0-13zM15.5 15.5L21 21M7.5 12.5l2-3 2 2 2-3" size={22} width={1.7} />
          </button>
        </div>
        <button className={cx('round', s.menu === 'view' && 'on')} aria-label="View modes: section, wireframe, zebra" aria-expanded={s.menu === 'view'} onClick={() => toggleMenu('view')}>
          <PathIcon d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12zM12 9a3 3 0 1 1 0 6a3 3 0 1 1 0-6z" size={22} width={1.7} />
        </button>
        <button className="round" aria-label="More" aria-expanded={s.menu === 'more'} onClick={() => toggleMenu('more')}><DotsIcon size={22} /></button>
      </div>

      <RailMenus />
      {s.analysis && !isCheck && <AnalysisCard />}
      {s.openPin !== null && !isCheck && <CommentThread />}
    </>
  );
}

function RailMenus() {
  const s = useApp();
  const { set, showToast, setCamera } = s;
  const close = () => set({ menu: null });
  const bb = modelBounds(buildModel(s.version));
  const cutPosLabel = s.cut ? (() => {
    const ai = { x: 0, y: 2, z: 1 }[s.cut.ax];
    return `${Math.round(bb.mn[ai] + ((bb.mx[ai] - bb.mn[ai]) * s.cut.pct) / 100)} mm`;
  })() : '';
  const toggleAnalysis = (a: 'interf' | 'mass' | 'cg') => set({ analysis: s.analysis === a ? null : a, menu: null, anHi: null });

  switch (s.menu) {
    case 'cube':
      return (
        <div className="menu" style={{ bottom: 420 }} role="menu">
          <button className="mi" role="menuitem" onClick={() => setCamera('iso')}>Isometric</button>
          <button className="mi" role="menuitem" onClick={() => setCamera('front')}>Front</button>
          <button className="mi" role="menuitem" onClick={() => setCamera('top')}>Top</button>
          <button className="mi" role="menuitem" onClick={() => setCamera('side')}>Side</button>
          <div className="sep" />
          <button className="mi" role="menuitem" onClick={() => setCamera(s.camera.view)}>Reset zoom</button>
        </div>
      );
    case 'mate':
      return (
        <div className="menu matemenu" style={{ bottom: 316 }} role="menu" aria-label="Mates">
          {MATE_TYPES.map((m, i) => (
            <button key={m.id} className={cx('mi', i === 0 && 'first')} role="menuitem" onClick={() => { close(); showToast(`${m.name}: pick two mate connectors on the model`); }}>
              <PathIcon d={m.d} size={20} width={1.5} /><span style={{ flex: 1 }}>{m.name}</span><span className="muted">{m.dof === null ? '' : `${m.dof} DOF`}</span>
            </button>
          ))}
        </div>
      );
    case 'export':
      return (
        <div className="menu" style={{ bottom: 224 }} role="menu">
          {[['STEP assembly', '.step'], ['Mesh for 3D printing', '.stl'], ['Drawings', '.pdf']].map(([l, ext]) => (
            <button key={ext} className="mi" role="menuitem" onClick={() => { close(); showToast(`${l} (${ext}) is exported by the engine`); }}>{l} <span className="muted">{ext}</span></button>
          ))}
        </div>
      );
    case 'analysis':
      return (
        <div className="menu" style={{ bottom: 134 }} role="menu">
          <label>Analysis</label>
          <button className="mi" role="menuitemcheckbox" aria-checked={s.analysis === 'interf'} onClick={() => toggleAnalysis('interf')}>Interference detection <MenuCheck on={s.analysis === 'interf'} /></button>
          <button className="mi" role="menuitemcheckbox" aria-checked={s.analysis === 'mass'} onClick={() => toggleAnalysis('mass')}>Mass estimation <MenuCheck on={s.analysis === 'mass'} /></button>
          <button className="mi" role="menuitemcheckbox" aria-checked={s.analysis === 'cg'} onClick={() => toggleAnalysis('cg')}>Centre of gravity <MenuCheck on={s.analysis === 'cg'} /></button>
        </div>
      );
    case 'view': {
      const dispLabel = (Object.keys(DISPLAY).find((k) => DISPLAY[k] === s.display) ?? 'Edges') as keyof typeof DISPLAY;
      return (
        <div className="menu viewmenu" style={{ bottom: 80 }} role="menu">
          <label>Display</label>
          <Segmented options={Object.keys(DISPLAY)} value={dispLabel} onChange={(v) => set({ display: DISPLAY[v] })} label="Display style" style={{ margin: '4px 8px 6px' }} />
          <button className="mi" role="menuitemcheckbox" aria-checked={s.xray} onClick={() => set({ xray: !s.xray })}>X-ray <MenuCheck on={s.xray} /></button>
          <button className="mi" role="menuitemcheckbox" aria-checked={s.showResolved} onClick={() => set({ showResolved: !s.showResolved })}>Show resolved comments <MenuCheck on={s.showResolved} /></button>
          <button className="mi" role="menuitemcheckbox" aria-checked={s.zebra} onClick={() => set({ zebra: !s.zebra })}>Zebra stripes <MenuCheck on={s.zebra} /></button>
          <div className="sep" />
          <button className="mi" role="menuitemcheckbox" aria-checked={!!s.cut} onClick={() => set({ cut: s.cut ? null : { ax: 'x', pct: 50 } })}>Section view <MenuCheck on={!!s.cut} /></button>
          {s.cut && (
            <>
              <Segmented options={CUT_AXES} value={s.cut.ax.toUpperCase() as (typeof CUT_AXES)[number]} onChange={(v) => set({ cut: { ...s.cut!, ax: v.toLowerCase() as CutAxis } })} label="Section plane" style={{ margin: '2px 8px 4px' }} />
              <label htmlFor="cutpos">Plane position: {cutPosLabel}</label>
              <input id="cutpos" type="range" min={0} max={100} value={s.cut.pct} onChange={(e) => set({ cut: { ...s.cut!, pct: Number(e.target.value) } })} />
            </>
          )}
          <div className="sep" />
          <label htmlFor="explode">Explode parts</label>
          <input id="explode" type="range" min={0} max={100} value={Math.round(s.explode * 100)} onChange={(e) => set({ explode: Number(e.target.value) / 100 })} />
        </div>
      );
    }
    case 'more':
      return (
        <div className="menu" style={{ bottom: 28 }} role="menu">
          <button className="mi" role="menuitem" onClick={() => set({ display: 'edges', xray: false, zebra: false, cut: null, explode: 0, menu: null })}>Reset display settings</button>
          <button className="mi" role="menuitem" onClick={() => setCamera('iso')}>Reset camera</button>
          <div className="sep" />
          <button className="mi" role="menuitem" onClick={() => set({ menu: null, feedbackOpen: true })}>Send developer feedback</button>
        </div>
      );
    default:
      return null;
  }
}

function AnalysisCard() {
  const s = useApp();
  const model = buildModel(s.version);
  const mp = massProps(model);
  type Row = { k: string; v: string; parts?: string[]; cls?: string };
  let title = '', sub = '', headline = '', note = '';
  let rows: Row[] = [];
  if (s.analysis === 'interf') {
    const itf = interference(model);
    title = 'Interference detection';
    sub = `${itf.bodies} bodies · ${itf.pairs} pairs checked`;
    headline = itf.hits.length ? `${itf.hits.length} interference${itf.hits.length > 1 ? 's' : ''} found` : 'No interferences found';
    rows = [...itf.hits.map((h) => ({ k: h.name, v: `${Math.round(h.depth)} mm overlap`, parts: [h.a, h.b], cls: 'on' })), ...itf.contacts.map((c) => ({ k: c.name, v: 'touching', parts: [c.a, c.b] }))];
    note = 'Checks every body pair for overlapping volume (bounding boxes, radial test for coaxial cylinders). Hover a row to highlight it in 3D.';
  } else if (s.analysis === 'mass') {
    title = 'Mass estimation';
    sub = 'From exact part volumes × material density';
    headline = `Total ${mp.total.toFixed(2)} kg · bracket ${mp.bracket.toFixed(2)} kg`;
    rows = [...mp.parts.map((q) => ({ k: `${q.name} · ${MATERIAL[q.id]}`, v: `${q.mass.toFixed(q.mass < 0.1 ? 3 : 2)} kg`, parts: [q.id] })), { k: 'Total', v: `${mp.total.toFixed(2)} kg`, cls: 'total' }];
    note = 'Densities: steel 7.85, aluminium 2.70, stainless 8.00 g/cm³. Generator is a bought-in 4 kg part. Holes not yet modelled.';
  } else {
    title = 'Centre of gravity';
    sub = `Whole assembly, ${mp.total.toFixed(2)} kg`;
    headline = `X ${mp.cg[0].toFixed(1)} · Y ${mp.cg[2].toFixed(1)} · Z ${mp.cg[1].toFixed(1)} mm`;
    rows = [
      { k: 'Height above base', v: `${mp.cg[1].toFixed(1)} mm` },
      { k: 'Offset from plate centre', v: `${Math.hypot(mp.cg[0], mp.cg[2]).toFixed(1)} mm` },
      { k: 'Inside bolt pattern?', v: Math.abs(mp.cg[0]) <= 85 && Math.abs(mp.cg[2]) <= 55 ? 'Yes' : 'No' },
    ];
    note = 'Marked in the 3D view. Z is up, as in the build123d code.';
  }
  return (
    <section className="thread ancard" aria-label="Analysis results">
      <header>
        <div style={{ display: 'flex', flexDirection: 'column', marginRight: 'auto' }}><strong>{title}</strong><span className="sub">{sub}</span></div>
        <button className="iconbtn" aria-label="Close analysis" onClick={() => s.set({ analysis: null, anHi: null })}><CloseIcon size={16} color="#111" /></button>
      </header>
      <div className="tmsgs">
        <div className="anhead">{headline}</div>
        {rows.map((r) => (
          <button key={r.k} className={cx('anrow', r.cls, r.parts && 'click')}
            onClick={() => r.parts && s.set({ selected: r.parts[0] })}
            onMouseEnter={() => r.parts && s.set({ anHi: r.parts })} onMouseLeave={() => r.parts && s.set({ anHi: null })}>
            <span>{r.k}</span><b>{r.v}</b>
          </button>
        ))}
        <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>{note}</p>
      </div>
    </section>
  );
}

function CommentThread() {
  const s = useApp();
  const pin = s.pins.find((p) => p.id === s.openPin);
  const [text, setText] = useState('');
  const [queue, setQueue] = useState(true);
  if (!pin) return null;
  const n = s.pins.indexOf(pin) + 1;
  const part = buildModel(s.version).parts.find((p) => p.id === pin.part);
  const send = () => { s.sendPinComment(pin.id, text, queue); setText(''); };

  return (
    <section className="thread" aria-label="Comment thread">
      <header>
        <span className="nnum">{n}</span>
        <div style={{ display: 'flex', flexDirection: 'column', marginRight: 'auto' }}>
          <strong>{part?.name ?? pin.part}</strong><span className="sub">3D comment · {pin.msgs.length} message{pin.msgs.length === 1 ? '' : 's'}</span>
        </div>
        <button className={cx('resbtn', pin.resolved && 'done')} onClick={() => s.set({ pins: s.pins.map((p) => (p.id === pin.id ? { ...p, resolved: !p.resolved } : p)) })}>
          <CheckIcon size={14} width={2.4} />{pin.resolved ? 'Resolved' : 'Resolve'}
        </button>
        <button className="iconbtn" aria-label="Delete comment" onClick={() => s.set({ pins: s.pins.filter((p) => p.id !== pin.id), openPin: null })}><TrashIcon size={16} /></button>
        <button className="iconbtn" aria-label="Close thread" onClick={() => s.set({ openPin: null })}><CloseIcon size={16} color="#111" /></button>
      </header>
      <div className="tmsgs">
        {pin.msgs.map((m, i) => <div key={i} className="tmsg"><span className="who">{m.who}</span>{m.text}</div>)}
        {!pin.msgs.length && <p className="muted" style={{ margin: 0, fontSize: 13 }}>Write a comment, and if it helps, sketch on top or add images. Bot reads every comment.</p>}
      </div>
      <div className="composer">
        <input aria-label="Comment" placeholder="Add a comment…" value={text} autoFocus onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send(); }} />
        <div className="ctools">
          <button className="ctool" onClick={() => s.showToast('Sketching on the model arrives with the comment service')}><PencilIcon size={14} />Sketch</button>
          <button className={cx('ctool queue')} role="checkbox" aria-checked={queue} onClick={() => setQueue(!queue)} title="When checked, sending also queues this comment for Bot">
            <QBox on={queue} />Queue for Bot
          </button>
          <button className="ctool" onClick={() => s.showToast('Image upload arrives with the comment service')}><ImageIcon size={14} width={1.8} />Image</button>
          <button className="send" style={{ marginLeft: 'auto' }} aria-label="Send comment" onClick={send}><ArrowRight size={16} color="#fff" width={2.2} /></button>
        </div>
      </div>
    </section>
  );
}
