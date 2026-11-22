import { useState } from 'react';
import { CONNS, MATE_TYPES } from '../../data/seed';
import { buildModel, MATERIAL } from '../../model/parts';
import { headCommit, useApp } from '../../state/store';
import { BooksIcon, ChevronRight, CloseIcon, CodeIcon, CubeIcon, FolderIcon, PanelIcon, PathIcon } from '../../components/icons';
import { cx, sliderOf, Switch } from '../../components/ui';
import { codeLines } from './codeLines';
import { CheckPanel } from '../check/CheckPanel';

/** Left panel on How? (Parts / Notes / Code) and Check (studies). */
export function SolutionDrawer({ width }: { width: number }) {
  const layer = useApp((s) => s.layer);
  const tab = useApp((s) => s.howTab);
  const expert = useApp((s) => s.expert);
  const set = useApp((s) => s.set);
  const isCheck = layer === 'check';
  const tabs = expert ? (['parts', 'notes', 'code'] as const) : (['parts', 'notes'] as const);
  const cur = !expert && tab === 'code' ? 'parts' : tab;

  return (
    <aside className={cx('drawer howdrawer', !isCheck && cur === 'code' && 'wide')} aria-label="Solution panel" style={{ width }}>
      <div className="drawerhead">
        <span className="label" style={{ fontSize: 30 }}>{isCheck ? 'Check' : 'Solution'}</span>
        <button className="iconbtn" aria-label="Collapse panel" onClick={() => set({ drawer: false })}><PanelIcon /></button>
      </div>
      {!isCheck && (
        <div className="tabs" role="tablist">
          <span className="slider" aria-hidden="true" style={sliderOf(tabs as readonly string[], cur)} />
          <button role="tab" aria-selected={cur === 'parts'} className={cx(cur === 'parts' && 'on')} onClick={() => set({ howTab: 'parts' })}>Parts</button>
          <button role="tab" aria-selected={cur === 'notes'} className={cx(cur === 'notes' && 'on')} onClick={() => set({ howTab: 'notes' })}>Notes</button>
          {expert && <button role="tab" aria-selected={cur === 'code'} className={cx(cur === 'code' && 'on')} onClick={() => set({ howTab: 'code' })}>Code</button>}
        </div>
      )}
      {!isCheck && cur === 'parts' && (
        <div className="addrow">
          <button className="pillbtn libbtn" onClick={() => set({ libOpen: true })}><BooksIcon size={16} />Add from part library</button>
          <button className="pillbtn libbtn" onClick={() => set({ asmPick: true })}><CubeIcon size={16} width={1.8} />Add other assembly</button>
        </div>
      )}
      <div className="dscroll">
        {isCheck && <CheckPanel />}
        {!isCheck && cur === 'parts' && <PartsTab />}
        {!isCheck && cur === 'notes' && <NotesTab />}
        {!isCheck && cur === 'code' && <CodeTab />}
      </div>
    </aside>
  );
}

function PartsTab() {
  const s = useApp();
  const { set } = s;
  const model = buildModel(s.version);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);
  const sel = model.parts.find((p) => p.id === s.selected);
  const items = [
    ...model.parts.map((p) => ({ id: p.id, name: p.name, color: p.color, removable: false })),
    ...s.libParts.map((p) => ({ id: p.id, name: `${p.name} · ${p.variant}${p.qty > 1 ? ` × ${p.qty}` : ''}`, color: '#ffffff', removable: true })),
  ];
  const moveTo = (folder: string | null) => { if (dragId) set({ floc: { ...s.floc, [dragId]: folder } }); setDragId(null); };
  const rename = (id: string) => { set({ folders: s.folders.map((f) => (f.id === id ? { ...f, name: draft.trim() || f.name } : f)) }); setEditing(null); };

  const row = (it: (typeof items)[number], inFolder: boolean) => (
    <div key={it.id} className={cx('prow tree', inFolder && 'infold', s.selected === it.id && 'on')} draggable title="Drag onto a folder to move it"
      onDragStart={() => setDragId(it.id)} onClick={() => !it.removable && s.select(it.id)}>
      <span className={cx('swatch', it.removable && 'asmsw')} style={{ background: it.color }} /><span className="pname">{it.name}</span>
      {it.removable && (
        <button className="iconbtn ansx" style={{ opacity: 1 }} aria-label="Remove" onClick={(e) => { e.stopPropagation(); set({ libParts: s.libParts.filter((p) => p.id !== it.id) }); }}>
          <CloseIcon size={11} color="#555" />
        </button>
      )}
    </div>
  );

  return (
    <>
      <div className="sect parthead" onDragOver={(e) => e.preventDefault()} onDrop={() => moveTo(null)}>
        Parts
        <button className="linkbtn newfolder" onClick={() => { const id = `f${Date.now()}`; set({ folders: [...s.folders, { id, name: 'New folder', open: true }] }); setEditing(id); setDraft('New folder'); }}>+ Folder</button>
      </div>
      {s.folders.map((f) => {
        const inside = items.filter((it) => s.floc[it.id] === f.id);
        return (
          <div key={f.id}>
            <div className="frow" onDragOver={(e) => e.preventDefault()} onDrop={() => moveTo(f.id)}>
              <button className="fbtn" aria-expanded={f.open} onClick={() => set({ folders: s.folders.map((x) => (x.id === f.id ? { ...x, open: !x.open } : x)) })}>
                <ChevronRight size={12} width={2.6} style={{ transform: `rotate(${f.open ? 90 : 0}deg)` }} />
                <FolderIcon size={16} />
                {editing !== f.id && <span className="fname" title="Double-click to rename" onDoubleClick={() => { setEditing(f.id); setDraft(f.name); }}>{f.name}</span>}
              </button>
              {editing === f.id && (
                <input className="finput" aria-label="Folder name" value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} onBlur={() => rename(f.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter') rename(f.id); if (e.key === 'Escape') setEditing(null); }} />
              )}
              <span className="fcount">{inside.length}</span>
              <button className="iconbtn ansx fdel" aria-label="Delete folder (keeps its parts)" title="Delete folder, keep parts"
                onClick={() => set({ folders: s.folders.filter((x) => x.id !== f.id), floc: Object.fromEntries(Object.entries(s.floc).map(([k, v]) => [k, v === f.id ? null : v])) })}>
                <CloseIcon size={11} color="#555" />
              </button>
            </div>
            {f.open && inside.map((it) => row(it, true))}
          </div>
        );
      })}
      {items.filter((it) => !s.floc[it.id] || !s.folders.some((f) => f.id === s.floc[it.id])).map((it) => row(it, false))}

      {sel && (
        <div className="detail">
          <h3>{sel.name}</h3>
          <div className="kv"><span>Material</span><span>{MATERIAL[sel.id] ?? '—'}</span></div>
          <div className="kv"><span>Connected to</span><span>{CONNS.filter((c) => c.a === sel.id || c.b === sel.id).map((c) => model.parts.find((p) => p.id === (c.a === sel.id ? c.b : c.a))?.name).filter(Boolean).join(', ') || '—'}</span></div>
          <button className="pillbtn" onClick={() => { set({ chatOpen: true, chatText: `About the ${sel.name.toLowerCase()}: ` }); }}>Ask Bot about it</button>
        </div>
      )}

      <div className="sect matehead">Mates<span>{CONNS.length}</span></div>
      {CONNS.map((c, i) => {
        const mt = MATE_TYPES.find((m) => m.id === c.type);
        return (
          <button key={c.title} className={cx('conn mate', s.hiConn === i && 'on')}
            onClick={() => set({ hiConn: s.hiConn === i ? null : i, anHi: s.hiConn === i ? null : [c.a, c.b] })}
            onMouseEnter={() => set({ anHi: [c.a, c.b] })} onMouseLeave={() => set({ anHi: s.hiConn !== null ? [CONNS[s.hiConn].a, CONNS[s.hiConn].b] : null })}>
            <span className="mateic">{mt && <PathIcon d={mt.d} size={18} width={1.6} />}</span>
            <span className="matetx"><b>{mt?.name}</b><span>{c.title} · {c.how[String(s.version)]}</span></span>
            <span className="matedof">{mt?.dof === null || mt?.dof === undefined ? '' : `${mt.dof} DOF`}</span>
          </button>
        );
      })}
    </>
  );
}

function NotesTab() {
  const pins = useApp((s) => s.pins);
  const showResolved = useApp((s) => s.showResolved);
  const set = useApp((s) => s.set);
  const model = buildModel(useApp((s) => s.version));
  const visible = pins.filter((p) => showResolved || !p.resolved);
  return (
    <>
      <div className="srow" style={{ borderTop: 0, padding: '4px 0 8px' }}>
        <div className="slabel"><b>Show resolved comments</b><span className="muted">{pins.filter((p) => p.resolved).length} resolved</span></div>
        <Switch on={showResolved} label="Show resolved comments" onToggle={() => set({ showResolved: !showResolved })} />
      </div>
      <div className="sect">3D comments</div>
      {visible.map((p) => (
        <button key={p.id} className="note" onClick={() => set({ openPin: p.id })}>
          <span className="nnum">{pins.indexOf(p) + 1}</span>
          <span><b>{model.parts.find((x) => x.id === p.part)?.name ?? p.part}</b><br />{p.msgs[0]?.text ?? 'New comment'}</span>
        </button>
      ))}
      {!visible.length && <p className="muted" style={{ fontSize: 13 }}>No comments yet. Pick the bubble on the right, click a part, then write, sketch or add images.</p>}
    </>
  );
}

function CodeTab() {
  const s = useApp();
  const lines = codeLines(s.projectName, s.version, headCommit(s));
  const file = `${s.projectName.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.py`;
  return (
    <>
      <div className="codehead">
        <span className="codefile"><CodeIcon size={14} />{file}</span>
        <button className="pillbtn" onClick={() => { void navigator.clipboard?.writeText(lines.map((l) => l.text).join('\n')); s.showToast('Code copied'); }}>Copy</button>
        <button className="pillbtn dark" onClick={() => s.runAgent(['Running build123d', 'Tessellating', 'Updating the view'], () => s.showToast('Rebuilt from code (mock)'))}>Run</button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '0 0 6px' }}>build123d source of this version. Selected parts are highlighted. Edits here become a new version.</p>
      <div className="code" role="region" aria-label="build123d Python code">
        {lines.map((l, i) => (
          <div key={i} className={cx('cl', l.kind, l.part && l.part === s.selected && 'hl')} onClick={() => l.part && s.select(l.part)}>
            <span className="lno">{i + 1}</span><span className="ltx">{l.text || ' '}</span>
          </div>
        ))}
      </div>
    </>
  );
}
