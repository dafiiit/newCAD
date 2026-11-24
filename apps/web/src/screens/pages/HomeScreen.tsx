import { COMMUNITY } from '../../data/seed';
import type { CommunityDesign, Layer } from '../../data/types';
import { headCommit, useApp } from '../../state/store';
import { ModelThumb } from '../../model/ModelThumb';
import { PlaceholderCube, PlusIcon } from '../../components/icons';
import { cx, Segmented } from '../../components/ui';
import { assetUrl } from '../../engine/client';
import { openProject } from '../../engine/sync';

function ago(t: number) {
  const d = Date.now() / 1000 - t;
  if (d < 90) return 'just now';
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return `${Math.round(d / 86400)} days ago`;
}

const FILTERS = ['All', 'Robotics', 'Energy', 'Fixtures', '3D printing'] as const;

const phaseOf = (l: Layer) => (l === 'what' ? 'What?' : l === 'check' ? 'Check' : 'How?');

/** Home: your projects and community designs to remix. */
export function HomeScreen() {
  const s = useApp();
  const head = headCommit(s);
  const mock = (name: string) => () => s.showToast(`${name} is an example card. Only Generator mount is built in this prototype.`);
  const newProject = () => {
    s.set({ chatOpen: true, chatText: 'New project: ' });
    // put the cursor after "New project: " so the goal can be typed right away
    setTimeout(() => {
      const el = document.querySelector<HTMLInputElement>('input[aria-label="Chat with Bot"]');
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    }, 0);
  };
  const live = s.eng?.projects;
  const projects = live ? live.slice().sort((a, b) => b.updated - a.updated).map((p) => ({
    name: p.name,
    meta: `Edited ${ago(p.updated)} · ${p.branches.length} branch${p.branches.length === 1 ? '' : 'es'} · ${p.parts.length} part${p.parts.length === 1 ? '' : 's'}`,
    phase: p.parts.length ? 'How?' : 'What?',
    thumb: false,
    img: p.parts.length ? assetUrl(`/api/projects/${p.id}/snapshot.png?w=360&h=240&ref=${p.headCommit}`) : null,
    open: () => {
      if (p.id === s.eng?.pid) { s.go(s.lastLayer === 'home' ? 'what' : s.lastLayer); return; }
      openProject(p.id).then(() => useApp.getState().go(p.parts.length ? 'how' : 'what')).catch((e) => s.showToast(String(e.message ?? e)));
    },
  })) : [
    ...s.remixed.map((id) => { const c = COMMUNITY.find((x) => x.id === id)!; return { name: `Remix of ${c.name}`, meta: `Just now · from ${c.author}`, phase: 'What?', thumb: false, open: mock(`Remix of ${c.name}`) }; }),
    { name: s.projectName, meta: `Edited just now · ${head ? `${head.branch} · ${head.id}` : ''} · ${Object.keys(s.branchColors).length} branches`, phase: phaseOf(s.lastLayer), thumb: true, open: () => s.go(s.lastLayer) },
    { name: 'Sensor bracket', meta: 'Edited 2 days ago · 1 branch', phase: 'What?', thumb: false, open: mock('Sensor bracket') },
    { name: 'Gripper finger', meta: 'Edited last week · 4 branches', phase: 'How?', thumb: false, open: mock('Gripper finger') },
    { name: 'Pump housing cover', meta: 'Edited 3 weeks ago · 2 branches', phase: 'How?', thumb: false, open: mock('Pump housing cover') },
  ].map((p) => ({ ...p, img: null as string | null }));
  const community = COMMUNITY.filter((c) => s.commFilter === 'All' || c.tag === s.commFilter);

  return (
    <main className="home" aria-label="Projects">
      <div className="homehead">
        <div><h1>Projects</h1><p className="muted">Pick up where you left off, or describe something new to Bot.{s.eng && <> <span className="engbadge"><span className={cx('dot', !s.eng.online && 'off')} />{s.eng.online ? 'Engine connected' : 'Engine offline'}</span></>}</p></div>
        <button className="pillbtn dark" onClick={newProject}><PlusIcon size={14} width={2.4} />New project</button>
      </div>
      <div className="pgrid">
        {projects.map((p) => (
          <button key={p.name} className="pcard" onClick={p.open}>
            <div className="pthumb">
              {p.img ? <img className="histthumb" alt="" src={p.img} /> : p.thumb ? <ModelThumb version={s.version} /> : <span className="pph"><PlaceholderCube /></span>}
              <span className={cx('phase', p.phase === 'How?' && 'how')}>{p.phase}</span>
            </div>
            <div className="pinfo"><b>{p.name}</b><span className="muted">{p.meta}</span></div>
          </button>
        ))}
        <button className="pcard pnew" onClick={newProject}>
          <span className="pnewplus"><PlusIcon size={26} color="#111" /></span>
          <b>New project</b><span className="muted">Start with a goal, a sketch or a file</span>
        </button>
      </div>

      <div className="homehead" style={{ marginTop: 48 }}>
        <div><h2 className="commh">Explore the community</h2><p className="muted">Open designs from other builders. Remix one to start from it.</p></div>
        <Segmented options={FILTERS} value={s.commFilter as (typeof FILTERS)[number]} onChange={(v) => s.set({ commFilter: v })} label="Filter community designs" />
      </div>
      <div className="pgrid">
        {community.map((c) => {
          const liked = !!s.liked[c.id];
          const remixed = s.remixed.includes(c.id);
          return (
            <article key={c.id} className="pcard ccard">
              <div className="pthumb"><CommunityThumb kind={c.kind} /><span className="phase">{c.tag}</span></div>
              <div className="pinfo">
                <b>{c.name}</b>
                <span className="muted">{c.author} · {c.likes + (liked ? 1 : 0)} likes · {c.remixes + (remixed ? 1 : 0)} remixes</span>
                <div className="cactions">
                  <button className="pillbtn dark" onClick={() => { if (!remixed) { s.set({ remixed: [c.id, ...s.remixed] }); s.showToast(`Remix of ${c.name} added to your projects`); } }}>{remixed ? 'Remixed' : 'Remix'}</button>
                  <button className="pillbtn" aria-pressed={liked} onClick={() => s.set({ liked: { ...s.liked, [c.id]: !liked } })}>{liked ? 'Liked' : 'Like'}</button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}

function CommunityThumb({ kind }: { kind: CommunityDesign['kind'] }) {
  const gear = 'M50 14l6 10 11-4 2 12 12 3-4 11 10 6-10 6 4 11-12 3-2 12-11-4-6 10-6-10-11 4-2-12-12-3 4-11-10-6 10-6-4-11 12-3 2-12 11 4z';
  if (kind === 'gear') return <svg width="110" height="110" viewBox="0 0 100 100" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><path d={gear} fill="#fff" /><circle cx="50" cy="50" r="16" /><circle cx="50" cy="50" r="5" fill="#111" /></svg>;
  if (kind === 'bracket') return <svg width="120" height="100" viewBox="0 0 120 100" fill="none" stroke="#111" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="M20 80V20l14-8v60l66 0-14 8z" fill="#fff" /><path d="M34 72l66 0M34 12v60" /><circle cx="27" cy="34" r="4" /><circle cx="70" cy="76" r="3" /></svg>;
  if (kind === 'turbine') return <svg className="truecol" width="120" height="100" viewBox="0 0 120 100" fill="none" stroke="#111" strokeWidth="1.6" aria-hidden="true"><ellipse cx="60" cy="50" rx="40" ry="26" fill="#fff" /><path d="M60 50l-6-22c8-4 14 2 6 22zM60 50l22 6c4 8-2 14-22-6zM60 50l-20 10c-8-3-5-12 20-10z" fill="#D2A93B" /><circle cx="60" cy="50" r="5" fill="#111" /></svg>;
  return <svg width="120" height="100" viewBox="0 0 120 100" fill="none" stroke="#111" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="M24 20h56v14H40v32h40v14H24z" fill="#fff" /><path d="M70 34v22M62 56h16" strokeWidth="2.2" /><path d="M84 30l20-14 6 6-18 18" /></svg>;
}
