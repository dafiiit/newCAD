import { useApp } from '../../state/store';
import { CommentIcon, CursorIcon, DotsIcon, PanelIcon } from '../../components/icons';
import { ProjectTitle } from '../../components/chrome/TopChrome';
import { DrawerResizer } from '../../components/chrome/DrawerResizer';
import { cx } from '../../components/ui';
import { Board } from './Board';
import { CriteriaDrawer } from './CriteriaDrawer';

/** What? — the spec sheet: overview plus one card per question, grouped by design criterion. */
export function WhatScreen() {
  const drawer = useApp((s) => s.drawer);
  const width = useApp((s) => s.drawerW.main);
  const menu = useApp((s) => s.menu);
  const tool = useApp((s) => s.tool);
  const { set, toggleMenu, showToast, generate } = useApp.getState();
  const specDone = useApp((s) => s.cats.every((c) => c.qs.every((_, i) => (s.cards[`${c.id}:${i}`] ?? []).length)));
  const boardLeft = drawer ? width + 24 : 84;

  return (
    <>
      <ProjectTitle />
      {drawer ? (
        <>
          <CriteriaDrawer width={width} />
          <DrawerResizer which="main" width={width} />
        </>
      ) : (
        <button className="openDrawer" aria-label="Open criteria panel" onClick={() => set({ drawer: true })}><PanelIcon /></button>
      )}
      <Board left={boardLeft} />

      <div className="rail" aria-label="Board tools">
        <div className="capsule">
          <span className="vslider" aria-hidden="true" style={{ transform: `translateY(${tool === 'comment' ? 100 : 0}%)` }} />
          <button className={cx('rbtn', !tool && 'on')} aria-label="Select" onClick={() => set({ tool: null })}><CursorIcon size={20} /></button>
          <button className={cx('rbtn', tool === 'comment' && 'on')} aria-label="Comment with text, sketch or image" onClick={() => set({ tool: tool === 'comment' ? null : 'comment' })}><CommentIcon size={20} /></button>
        </div>
        <button className="round" aria-label="More" aria-expanded={menu === 'more'} onClick={() => toggleMenu('more')}><DotsIcon size={22} /></button>
      </div>
      {menu === 'more' && (
        <div className="menu" style={{ bottom: 28 }} role="menu">
          <button className="mi" role="menuitem" onClick={() => { set({ menu: null }); showToast('Export requirements (PDF): needs the engine'); }}>Export requirements (PDF)</button>
          {specDone && <button className="mi" role="menuitem" onClick={() => { set({ menu: null }); generate(); }}>Generate 3 prototypes</button>}
          <div className="sep" />
          <button className="mi" role="menuitem" onClick={() => set({ menu: null, feedbackOpen: true })}>Send developer feedback</button>
        </div>
      )}
    </>
  );
}

export function useDraft(key: string) {
  const draft = useApp((s) => s.ansDraft[key] ?? '');
  const setDraft = (v: string) => useApp.setState((s) => ({ ansDraft: { ...s.ansDraft, [key]: v } }));
  return [draft, setDraft] as const;
}

