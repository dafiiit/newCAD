import { useMemo } from 'react';
import type { BotTask, TraceEvent } from '../../engine/types';
import type { ChatMessage, ChatThread } from '../../data/types';
import { CHAT_PROJECTS, MODES } from '../../data/seed';
import { aheadStage, ivCurrent, openKeys, useApp } from '../../state/store';
import { partNameOf } from '../../engine/model';
import { applyBranch, checkoutRef, stopTask, stopTasks } from '../../engine/sync';
import { BotGlyph, ChevronRight, ChevronUp, CloseIcon, CollapseIcon, CubeIcon, ExpandIcon, ImageIcon, PlusIcon, SidebarIcon, ArrowRight, StopIcon, VideoIcon } from '../icons';
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
  const engThreads = useMemo(() => (s.eng ? threadsOf(s.msgs) : null), [s.eng, s.msgs]);
  const activeThread = s.activeChat === 'live' ? null : (engThreads ?? s.chats).find((c) => c.id === s.activeChat);
  const msgs = activeThread ? activeThread.msgs : s.msgs;
  const full = s.chatOpen && s.chatFull;
  const running: BotTask[] = s.eng
    ? Object.values(s.eng.tasks).filter((t) => t.status === 'running' && t.project === s.eng!.pid && t.mode !== 'interview'
      && (!activeThread || t.id === activeThread.id || t.thread === activeThread.id || (t.group && activeThread.id === `g:${t.group}`)))
    : [];

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
    if (engThreads) {
      const items = engThreads
        .filter((c) => !q || `${c.title} ${c.msgs.map((m) => m.text).join(' ')}`.toLowerCase().includes(q))
        .map((c) => ({ id: c.id, title: c.title, when: c.when }));
      return [{ id: 'eng', name: s.projectName, items: [{ id: 'live', title: 'All messages', when: '' }, ...items] }];
    }
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
  }, [s.chats, s.chatSearch, s.projectName, engThreads]);

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
                {!full && engThreads && engThreads.length > 0 && (
                  <button className="linkbtn" style={{ fontSize: 12 }} onClick={() => set({ chatFull: true, chatSide: true })}>{engThreads.length} conversation{engThreads.length === 1 ? '' : 's'}</button>
                )}
                <button className="iconbtn" aria-label={full ? 'Exit full screen' : 'Full screen'} title={full ? 'Exit full screen' : 'Full screen'} onClick={() => set({ chatFull: !s.chatFull })}>
                  {full ? <CollapseIcon size={16} /> : <ExpandIcon size={16} />}
                </button>
              </div>
              <div className="msgs">
                {running.map((t) => (
                  <div key={t.id} className="msg bot live" aria-live="polite">
                    <div className="liverow">
                      <span className="bsdot busy" aria-hidden="true" />
                      <span className="livelabel">{t.concept ? `Concept ${t.concept}: ` : ''}{t.label}{t.step ? ` · step ${t.step}` : ''}</span>
                      <button className="pillbtn stopbtn" onClick={() => void stopTask(t.id)} disabled={t.label === 'Stopping'}>
                        <StopIcon size={10} />{t.label === 'Stopping' ? 'Stopping…' : 'Stop'}
                      </button>
                    </div>
                    <Trace events={t.trace ?? []} live />
                  </div>
                ))}
                {s.typing && !running.length && <div className="msg bot"><p className="muted">thinking…</p></div>}
                {msgs.slice().reverse().map((m, i) => (
                  <div key={msgs.length - i} className={cx('msg', m.who === 'you' ? 'you' : 'bot')}>
                    {(m.ctx || m.source === 'comment') && <span className="msgctx"><CubeIcon size={11} width={2} />{m.source === 'comment' ? `3D comment${m.ctx ? ` · ${m.ctx}` : ''}` : m.ctx}</span>}
                    {!activeThread && engThreads && m.thread && m.who === 'you' && (
                      <button className="linkbtn msgthread" onClick={() => set({ activeChat: m.thread!, chatFull: true, chatSide: true })}>Open conversation</button>
                    )}
                    <p>{m.text}</p>
                    {m.who === 'bot' && !!m.trace?.length && <Trace events={m.trace} />}
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
          {s.chatText.trim() ? (
            <button className="send" aria-label="Send message" onClick={sendChat}><ArrowRight size={16} color="#fff" width={2.2} /></button>
          ) : live && s.agent ? (
            <button className="send" aria-label="Stop Bot" title="Stop Bot" onClick={() => void stopTasks()}><StopIcon size={14} color="#fff" /></button>
          ) : null}
        </div>
      </div>
    </>
  );
}

/** What the Bot thought and did: reasoning, notes between tool calls, and every tool call with its arguments and result. */
function Trace({ events, live = false }: { events: TraceEvent[]; live?: boolean }) {
  if (!events.length) return live ? <p className="muted tracewait">Waiting for the model…</p> : null;
  const tools = events.filter((e) => e.kind === 'tool').length;
  const items = events.map((e, i) => <TraceItem key={i} e={e} />);
  if (live) return <ol className="trace">{items.slice(-12)}</ol>;
  return (
    <details className="tracebox">
      <summary>{tools ? `${tools} tool call${tools === 1 ? '' : 's'}` : 'Reasoning'}{events.some((e) => e.kind === 'thinking') && tools ? ' and reasoning' : ''}</summary>
      <ol className="trace">{items}</ol>
    </details>
  );
}

function TraceItem({ e }: { e: TraceEvent }) {
  if (e.kind === 'thinking') return <li className="tr think"><span className="trk">Thought</span><span className="trtext">{e.text}</span></li>;
  if (e.kind === 'text') return <li className="tr note"><span className="trk">Note</span><span className="trtext">{e.text}</span></li>;
  const args = e.args && Object.keys(e.args).length ? JSON.stringify(e.args, null, 1) : '';
  return (
    <li className={cx('tr tool', e.status)}>
      <details>
        <summary>
          <span className={cx('trdot', e.status)} aria-label={e.status === 'error' ? 'failed' : e.status === 'running' ? 'running' : 'done'} />
          <span className="trlabel">{e.label || e.tool}</span>
          <code className="trname">{e.tool}</code>
          {e.ms !== undefined && <span className="trms">{e.ms < 1000 ? `${e.ms} ms` : `${(e.ms / 1000).toFixed(1)} s`}</span>}
        </summary>
        {args && <pre className="trpre">{args}</pre>}
        {e.result && <pre className={cx('trpre', e.status === 'error' && 'err')}>{e.result}{e.images ? `\n(+${e.images} image${e.images === 1 ? '' : 's'})` : ''}</pre>}
      </details>
    </li>
  );
}

const KIND: Record<string, string> = { comment: '3D comment', generate: 'Prototypes', interview: 'Interview', chat: 'Chat' };

function ago(t?: number) {
  if (!t) return '';
  const d = Date.now() / 1000 - t;
  if (d < 60) return 'Now';
  if (d < 3600) return `${Math.round(d / 60)} min`;
  if (d < 86400) return `${Math.round(d / 3600)} h`;
  return `${Math.round(d / 86400)} d`;
}

/** Engine mode: one conversation per Bot task (chat requests, 3D comments and their follow-ups), plus prototype runs and the interview. */
function threadsOf(msgs: ChatMessage[]): ChatThread[] {
  const by = new Map<string, ChatMessage[]>();
  for (const m of msgs) {
    if (!m.thread) continue;
    const list = by.get(m.thread) ?? [];
    list.push(m);
    by.set(m.thread, list);
  }
  const out: (ChatThread & { last: number })[] = [];
  for (const [id, list] of by) {
    const first = list.find((m) => m.who === 'you') ?? list[0];
    const kind = KIND[first.source ?? list[0].source ?? 'chat'] ?? 'Chat';
    const text = id === 'interview' ? 'What? interview' : first.text.replace(/\s+/g, ' ');
    const title = `${kind === 'Chat' || id === 'interview' ? '' : `${kind}: `}${text.length > 60 ? `${text.slice(0, 58)}…` : text}`;
    const last = list[list.length - 1].t ?? 0;
    out.push({ id, project: 'eng', title, when: ago(last), msgs: list, last });
  }
  return out.sort((a, b) => b.last - a.last);
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
