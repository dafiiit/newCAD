import { useMemo } from 'react';
import { CHAT_PROJECTS, MODES } from '../../data/seed';
import { aheadStage, ivCurrent, openKeys, useApp } from '../../state/store';
import { partNameOf } from '../../engine/model';
import { applyBranch, checkoutRef, stopTasks } from '../../engine/sync';
import { BotGlyph, ChevronRight, ChevronUp, CloseIcon, CollapseIcon, CubeIcon, ExpandIcon, ImageIcon, PlusIcon, SidebarIcon, ArrowRight, VideoIcon } from '../icons';
import { cx } from '../ui';

/** Bottom chat bar on How?, Check and the pages. Expands into a panel, or full screen with chat history. */
export function ChatBar() {
  const s = useApp();
  const { set, sendChat } = s;
  const isPage = s.layer === 'home' || s.layer === 'team' || s.layer === 'settings';
  const isCheck = s.layer === 'check';
  const selName = (s.layer === 'how' || isCheck) && s.selected ? partNameOf(s, s.selected) : undefined;
  const selPart = selName ? { name: selName } : undefined;
  const live = !!s.eng;
  const activeThread = s.activeChat === 'live' ? null : s.chats.find((c) => c.id === s.activeChat);
  const msgs = activeThread ? activeThread.msgs : s.msgs;
  const full = s.chatOpen && s.chatFull;

  const ask = (text: string) => { set({ chatText: text }); setTimeout(() => useApp.getState().sendChat(), 0); };
  const engineChips: { label: string; go: () => void }[] = isPage
    ? [{ label: 'Start a new project', go: () => set({ chatText: 'New project: ' }) }]
    : [
      { label: 'Make it lighter', go: () => ask('Make it lighter without losing stiffness') },
      { label: 'Explain this design', go: () => ask('Explain this design in a few sentences: what holds what, and the key numbers') },
      { label: 'Open versions', go: () => set({ review: true, chatOpen: false }) },
      ...(s.agent ? [{ label: 'Stop Bot', go: () => void stopTasks() }] : []),
    ];
  const chips: { label: string; go: () => void }[] = live ? engineChips : isPage
    ? [{ label: 'Start a new project', go: () => set({ chatText: 'New project: ' }) }]
    : isCheck
      ? [
        { label: 'Run all studies', go: () => { s.userSays('Run all studies'); setTimeout(() => { s.say('Running static stress first; the others are queued in the prototype as one click each.'); s.runStudy('static'); }, 500); } },
        { label: 'Is it safe at 600 rpm?', go: () => {
          s.userSays('Is it safe at 600 rpm?');
          setTimeout(() => { const f = MODES[useApp.getState().version][0]; const m = f / 10; s.say(`At 600 rpm the rotor excites 10 Hz. The first mode of this version is ${f} Hz, a margin of ${m.toFixed(1)}×. ${m > 3 ? 'That is comfortable.' : 'That is too close; I would stiffen the upright.'}`); }, 800);
        } },
      ]
      : [
        { label: 'Why Concept B?', go: () => { s.userSays('Why Concept B?'); setTimeout(() => s.say('B keeps the simple welded L but adds two gussets. In the check, that roughly halves the peak stress at the upright root compared with A, for about €6 more per part. C is lighter but needs more welding.'), 800); } },
        { label: 'Make it lighter', go: () => {
          s.userSays('Make it lighter');
          setTimeout(() => {
            s.say('Trying a lighter variant…');
            s.runAgent(['Thinning plates', 'Replacing gussets with ribs', 'Re-checking stress'], () => {
              const c = useApp.getState().addCommit({ branch: `lighter-${Math.floor(Math.random() * 255).toString(16)}`, ver: 3, msg: 'Lighter variant: thin plates + ribs', diff: 'plate → 6 mm, upright → 7 mm, gussets → 2 ribs 5 mm' });
              useApp.getState().say(`Done: ${c.branch} @ ${c.id}. It saves about 0.9 kg; the safety factor drops to 2.2.`);
            });
          }, 600);
        } },
        { label: 'Run vibration study', go: () => { s.userSays('Run vibration study'); s.runStudy('modal'); } },
      ];

  const groups = useMemo(() => {
    const q = s.chatSearch.toLowerCase().trim();
    const out: { id: string; name: string; items: { id: string; title: string; when: string }[] }[] = [
      { id: 'gm', name: s.projectName, items: [{ id: 'live', title: 'Current session', when: 'Now' }] },
    ];
    for (const c of s.chats) {
      if (q && !`${c.title} ${c.msgs.map((m) => m.text).join(' ')}`.toLowerCase().includes(q)) continue;
      const gname = CHAT_PROJECTS[c.project] ?? s.projectName;
      let g = out.find((x) => x.id === c.project);
      if (!g) { g = { id: c.project, name: gname, items: [] }; out.push(g); }
      g.items.push({ id: c.id, title: c.title, when: c.when });
    }
    return out.filter((g) => g.items.length);
  }, [s.chats, s.chatSearch, s.projectName]);

  return (
    <>
      {s.chatOpen && <div className="chatbackdrop" aria-hidden="true" onClick={() => set({ chatOpen: false, attachOpen: false })} />}
      <div className={cx('chatbar', s.chatOpen && 'open', full && 'full', full && !s.chatSide && 'noside')}>
        {s.chatOpen && (
          <section className="chatbody" aria-label="Chat with Bot">
            {full && s.chatSide && (
              <aside className="chatside" aria-label="Your chats">
                <button className="pillbtn dark newchat" onClick={() => set({ activeChat: 'live' })}><PlusIcon size={14} width={2.4} />New chat</button>
                <input className="chatsearch" aria-label="Search chats" placeholder="Search chats" value={s.chatSearch} onChange={(e) => set({ chatSearch: e.target.value })} />
                <div className="chatgroups">
                  {groups.map((g) => (
                    <div className="cgroup" key={g.id}>
                      <div className="cgtitle"><ChevronRight size={12} width={2.6} style={{ transform: 'rotate(90deg)' }} /><span style={{ flex: 1 }}>{g.name}</span><span className="muted">{g.items.length}</span></div>
                      {g.items.map((it) => (
                        <button key={it.id} className={cx('citem', s.activeChat === it.id && 'on')} onClick={() => set({ activeChat: it.id })}>
                          <span className="cititle">{it.title}</span><span className="ciwhen">{it.when}</span>
                        </button>
                      ))}
                    </div>
                  ))}
                  {!groups.length && <p className="muted" style={{ fontSize: 13, padding: '0 8px' }}>No chats match.</p>}
                </div>
              </aside>
            )}
            <div className="chatmain">
              <div className="chathead">
                {full && (
                  <button className="iconbtn" aria-label={s.chatSide ? 'Hide chats' : 'Show chats'} title={s.chatSide ? 'Hide chats' : 'Show chats'} onClick={() => set({ chatSide: !s.chatSide })}><SidebarIcon size={18} /></button>
                )}
                <span className="botmark"><BotGlyph size={16} /></span>
                <strong>Bot</strong>
                <span className="ctx">{activeThread ? activeThread.title : `${s.projectName} · ${s.layer === 'check' ? 'Check' : s.layer === 'how' ? 'How?' : 'Projects'}`}</span>
                <button className="iconbtn" aria-label={full ? 'Exit full screen' : 'Full screen'} title={full ? 'Exit full screen' : 'Full screen'} onClick={() => set({ chatFull: !s.chatFull })}>
                  {full ? <CollapseIcon size={16} /> : <ExpandIcon size={16} />}
                </button>
              </div>
              <div className="msgs">
                {s.typing && <div className="msg bot"><p className="muted">thinking…</p></div>}
                {msgs.slice().reverse().map((m, i) => (
                  <div key={msgs.length - i} className={cx('msg', m.who === 'you' ? 'you' : 'bot')}>
                    {m.ctx && <span className="msgctx"><CubeIcon size={11} width={2} />{m.ctx}</span>}
                    <p>{m.text}</p>
                    {!!m.actions?.length && (
                      <div className="msgacts">
                        {m.actions.includes('apply') && m.branch && <button className="pillbtn dark" onClick={() => void applyBranch(m.branch!)}>Apply to {s.eng?.log?.headBranch ?? 'main'}</button>}
                        {m.actions.includes('checkout') && m.branch && <button className="pillbtn" onClick={() => void checkoutRef(m.branch!)}>Check out {m.branch}</button>}
                        {m.actions.includes('history') && <button className="pillbtn" onClick={() => set({ review: true, chatOpen: false, layer: 'how', lastLayer: 'how' })}>Compare versions</button>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="chips">
                {chips.map((c) => <button key={c.label} className="chip" onClick={c.go}>{c.label}</button>)}
              </div>
            </div>
          </section>
        )}
        {selPart && (
          <div className="ctxrow">
            <span className="ctxchip" title="Bot sees this selection with your next message">
              <CubeIcon size={12} width={2} />{selPart.name}
              <button className="ctxx" aria-label="Don't send this selection" onClick={() => set({ selected: null })}><CloseIcon size={10} width={3} /></button>
            </span>
          </div>
        )}
        <div className="chatrow">
          {s.attachOpen && (
            <div className="attachpanel" role="menu" aria-label="Upload">
              <span className="aptitle">Add to {selPart ? selPart.name : s.projectName}</span>
              {[
                { icon: <ImageIcon size={20} color="#111" width={1.6} />, b: 'Upload images', sm: '.jpg, .png, .heic' },
                { icon: <CubeIcon size={20} color="#111" width={1.6} />, b: 'Upload STEP files', sm: '.step, .stp, .stl' },
                { icon: <VideoIcon size={20} color="#111" width={1.6} />, b: 'Upload a video', sm: '.mp4, .mov' },
              ].map((it) => (
                <button key={it.b} className="apitem" role="menuitem" onClick={() => { set({ attachOpen: false }); s.showToast(`${it.b}: file picker opens here in the app`); }}>
                  <span className="apicon">{it.icon}</span><span><b>{it.b}</b><small>{it.sm}</small></span>
                </button>
              ))}
            </div>
          )}
          <button className={cx('chatplus', s.attachOpen && 'open')} aria-label={s.attachOpen ? 'Close upload menu' : 'Upload'} aria-expanded={s.attachOpen} onClick={() => set({ attachOpen: !s.attachOpen })}>
            <PlusIcon size={22} color="#111" />
          </button>
          <input aria-label="Chat with Bot" placeholder="Chat with Bot …" value={s.chatText}
            onChange={(e) => set({ chatText: e.target.value })} onFocus={() => set({ chatOpen: true })}
            onKeyDown={(e) => { if (e.key === 'Enter') sendChat(); if (e.key === 'Escape') set({ chatOpen: false }); }} />
          {s.chatText.trim() && (
            <button className="send" aria-label="Send message" onClick={sendChat}><ArrowRight size={16} color="#fff" width={2.2} /></button>
          )}
        </div>
      </div>
    </>
  );
}

/** On What? the chat collapses into a status pill that shows what Bot is doing in the background. */
export function BotStatus() {
  const s = useApp();
  const ivKey = ivCurrent(s);
  const open = openKeys(s).length;
  let text = '', busy = false, pct = '';
  const asking = ivKey ? (() => { const a = ivKey.split(':'); const c = s.cats.find((x) => x.id === a[0]); return c ? `${c.name} · Q${Number(a[1]) + 1}${a[2] ? ' follow-up' : ''}` : ''; })() : '';
  if (s.agent) { text = s.agent.label; busy = true; pct = `${s.agent.pct}%`; }
  else if (s.typing) { text = 'Thinking …'; busy = true; }
  else if (s.ahead > 0 && s.ahead < 100) { text = `${asking ? `Asked ${asking} · ` : ''}${aheadStage(s.ahead)}`; busy = true; pct = `${s.ahead}%`; }
  else if (asking) text = `Asked ${asking} · waiting for your answer`;
  else if (s.ahead >= 100) text = 'Draft ready · kept in sync with your answers';
  else if (!open) text = 'Questionnaire complete · ready to build';
  else text = `Idle · ${open} question${open === 1 ? '' : 's'} open on the questionnaire`;
  const log = s.msgs.filter((m) => m.who === 'bot').slice(-6);

  return (
    <div className="bswrap">
      {s.botLogOpen && (
        <div className="botlog" role="log" aria-label="What Bot did">
          {log.map((m, i) => <p key={i} className={cx('blitem', i === log.length - 1 && 'last')}>{m.text}</p>)}
        </div>
      )}
      <button className="botstatus" aria-expanded={s.botLogOpen} title="What Bot is doing. Click for its recent activity." onClick={() => s.set({ botLogOpen: !s.botLogOpen })}>
        <span className="botmark"><BotGlyph size={14} /></span>
        <span className={cx('bsdot', busy && 'busy')} aria-hidden="true" />
        <span className="bstext">{text}</span>
        {pct && <span className="bspct">{pct}</span>}
        <ChevronUp size={14} width={2.2} className="bschev" style={{ transform: `rotate(${s.botLogOpen ? 180 : 0}deg)` }} />
      </button>
    </div>
  );
}
