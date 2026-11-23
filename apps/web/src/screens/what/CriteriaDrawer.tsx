import { useState } from 'react';
import { ivCurrent, useApp } from '../../state/store';
import { ChevronDown, PanelIcon } from '../../components/icons';
import { cx } from '../../components/ui';

const scrollTo = (id: string, block: ScrollLogicalPosition = 'start') =>
  setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block }), 60);

/** Left panel on What?: Overview plus the design criteria and their questions. */
export function CriteriaDrawer({ width }: { width: number }) {
  const s = useApp();
  const { set } = s;
  const [newCat, setNewCat] = useState('');
  const ivKey = ivCurrent(s);
  const countCat = (id: string) => Object.keys(s.cards).reduce((n, k) => (k.startsWith(`${id}:`) ? n + s.cards[k].length : n), 0);
  const overviewOn = s.whatView === 'overview';

  return (
    <nav className="drawer" aria-label="Design criteria" style={{ width }}>
      <div className="drawerhead">
        <span className="label">Design for:</span>
        <button className="iconbtn" aria-label="Collapse panel" onClick={() => set({ drawer: false })}><PanelIcon /></button>
      </div>
      <div className="catrow ovrow">
        <button className={cx('catbtn', overviewOn && 'on')} onClick={() => { set({ whatView: 'overview' }); scrollTo('sec-overview'); }}>
          <span className={cx('dot', s.overview.trim() && 'full')} />Overview
        </button>
      </div>
      <div className="ovsep" aria-hidden="true" />
      {s.cats.map((c) => {
        const n = countCat(c.id);
        const open = !!s.expanded[c.id];
        return (
          <div key={c.id}>
            <div className="catrow">
              <button className={cx('catbtn', c.id === s.cat && !overviewOn && 'on')} onClick={() => { set({ cat: c.id, q: 0, whatView: 'cat' }); scrollTo(`sec-${c.id}`); }}>
                <span className={cx('dot', n > 0 && 'full')} />{c.name}<span className="count">{n > 0 ? n : ''}</span>
              </button>
              <button className="chev" aria-label={`${open ? 'Collapse' : 'Show questions of'} ${c.name}`} aria-expanded={open}
                onClick={() => set({ expanded: { ...s.expanded, [c.id]: !open } })}>
                <ChevronDown size={16} width={2.2} style={{ transform: `rotate(${open ? 180 : 0}deg)`, transition: 'transform .15s' }} />
              </button>
            </div>
            {open && (
              <div className="sublist">
                {c.qs.map((qt, i) => {
                  const k = `${c.id}:${i}`;
                  const has = (s.cards[k] ?? []).length > 0;
                  return (
                    <button key={k} className={cx('subq', c.id === s.cat && i === s.q && !overviewOn && 'on', ivKey === k && 'asking')}
                      onClick={() => { set({ cat: c.id, q: i, whatView: 'cat' }); scrollTo(`q-${c.id}-${i}`, 'center'); }}>
                      <span className="sqn">{i + 1}</span><span className="sqt">{qt}</span><span className={cx('sdot', has && 'full')} />
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      {s.addingCat ? (
        <div className="addcat">
          <input aria-label="New criterion name" placeholder="e.g. Safety" value={newCat} autoFocus onChange={(e) => setNewCat(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { s.addCategory(newCat); setNewCat(''); } if (e.key === 'Escape') set({ addingCat: false }); }} />
          <button className="pillbtn dark" onClick={() => { s.addCategory(newCat); setNewCat(''); }}>Add</button>
        </div>
      ) : (
        <button className="plus" aria-label="Add a design criterion" onClick={() => set({ addingCat: true })}>+</button>
      )}
    </nav>
  );
}
