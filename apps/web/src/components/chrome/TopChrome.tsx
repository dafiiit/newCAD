import { useState } from 'react';
import { PROPS } from '../../data/seed';
import { headCommit, useApp } from '../../state/store';
import { BranchIcon, ChevronDown, HomeIcon, PencilIcon, UserIcon } from '../icons';
import { cx, sliderOf } from '../ui';

const LAYERS = ['what', 'how', 'check'] as const;

/** Home button, What? / How? / Check switch, account menu, agent progress and toast. */
export function TopChrome() {
  const layer = useApp((s) => s.layer);
  const menu = useApp((s) => s.menu);
  const expert = useApp((s) => s.expert);
  const agent = useApp((s) => s.agent);
  const toast = useApp((s) => s.toast);
  const tool = useApp((s) => s.tool);
  const { go, toggleMenu, set } = useApp.getState();
  const isPage = layer === 'home' || layer === 'team' || layer === 'settings';

  return (
    <>
      {(layer === 'what' || isPage) && <div className="bottomfade" aria-hidden="true" />}
      <button className={cx('homebtn', layer === 'home' && 'on')} aria-label="Home: all projects" onClick={() => go('home')}>
        <HomeIcon size={22} />
      </button>
      {!isPage && (
        <div className="seg" role="tablist" aria-label="Layer">
          <span className="slider" aria-hidden="true" style={sliderOf(LAYERS, layer as (typeof LAYERS)[number])} />
          <button role="tab" aria-selected={layer === 'what'} className={cx(layer === 'what' && 'on')} onClick={() => go('what')}>What?</button>
          <button role="tab" aria-selected={layer === 'how'} className={cx(layer === 'how' && 'on')} onClick={() => go('how')}>How?</button>
          <button role="tab" aria-selected={layer === 'check'} className={cx(layer === 'check' && 'on')} onClick={() => go('check')}>Check</button>
        </div>
      )}
      <button className="avatar" aria-label="Account" aria-expanded={menu === 'account'} onClick={() => toggleMenu('account')}>
        <UserIcon size={24} />
      </button>
      {menu === 'account' && (
        <div className="menu accmenu" role="menu">
          <button className="mi" role="menuitem" onClick={() => go('home')}>Projects</button>
          <button className="mi" role="menuitem" onClick={() => go('team')}>Team &amp; sharing</button>
          <button className="mi" role="menuitem" onClick={() => go('settings')}>Settings</button>
          <div className="sep" />
          <button className="mi" role="menuitemcheckbox" aria-checked={expert} onClick={() => set({ expert: !expert })}>
            Expert mode <span className={cx('switch', expert && 'on')}><span /></span>
          </button>
        </div>
      )}

      <div className="statusbar">
        {agent && (
          <div className="agentpill" role="status">
            <b>Bot</b><span>{agent.label}</span>
            <span className="bar"><span style={{ width: `${agent.pct}%` }} /></span>
            <span>{agent.step}/{agent.total}</span>
          </div>
        )}
        {tool === 'comment' && (
          <div className="hint">
            {layer === 'what' ? 'Click a question card to place a comment' : 'Click a part to place a comment in 3D'}
            <button className="linkbtn" onClick={() => set({ tool: null })}>Done</button>
          </div>
        )}
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}

/** Project name (click to rename) and the branch button that opens version history. */
export function ProjectTitle() {
  const name = useApp((s) => s.projectName);
  const version = useApp((s) => s.version);
  const head = useApp((s) => headCommit(s));
  const set = useApp((s) => s.set);
  const [draft, setDraft] = useState<string | null>(null);
  const save = () => { if (draft !== null) set({ projectName: draft.trim() || name }); setDraft(null); };

  return (
    <div className="howtitle">
      {draft !== null ? (
        <input className="nameinput" aria-label="Project name" value={draft} autoFocus
          onChange={(e) => setDraft(e.target.value)} onBlur={save}
          onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setDraft(null); }} />
      ) : (
        <h1>
          <button className="namebtn" title="Click to rename" onClick={() => setDraft(name)}>{name}<PencilIcon size={14} /></button>
        </h1>
      )}
      <button className="pillbtn" title="Versions and branches" onClick={() => set({ review: true, selCommit: head?.id ?? '9b11', menu: null })}>
        <BranchIcon size={16} />
        {head ? `${head.branch} · ${head.id}` : PROPS[version].name}
        <ChevronDown size={12} color="#111" width={2.4} />
      </button>
    </div>
  );
}
