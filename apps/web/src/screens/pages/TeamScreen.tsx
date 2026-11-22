import { useState } from 'react';
import { AV_COLORS, ROLES } from '../../data/seed';
import type { Role } from '../../data/types';
import { useApp } from '../../state/store';
import { CloseIcon } from '../../components/icons';
import { Switch } from '../../components/ui';

const LINK_FLAGS: [string, string, string][] = [
  ['link', 'Anyone with the link can view', 'People outside the team see the model and history, read-only.'],
  ['linkComment', 'Link viewers can comment', 'Requires link sharing.'],
];
const AGENT_FLAGS: [string, string, string][] = [
  ['agentEdit', 'Bot can edit this project', 'Creates versions on branches; main stays protected.'],
  ['agentComment', 'Agents reply in comment threads', ''],
  ['agentGuest', 'Allow teammates’ own agents', 'Agents brought by other members may read the project.'],
];

const initials = (name: string) => name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('');

/** Team & sharing: members, link sharing and what agents may do. */
export function TeamScreen() {
  const s = useApp();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('Editor');
  const slug = s.projectName.toLowerCase().replace(/[^a-z0-9]+/g, '-');

  const invite = () => {
    const e = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) { s.showToast('Enter an email address to invite'); return; }
    s.set({ members: [...s.members, { id: `m${Date.now()}`, name: e.split('@')[0], email: e, role, pending: true }] });
    setEmail('');
    s.showToast(`Invite sent to ${e}`);
  };
  const flagRows = (list: [string, string, string][]) => list.map(([key, label, help]) => (
    <div key={key} className="srow">
      <div className="slabel"><b>{label}</b><span className="muted">{help}</span></div>
      <Switch on={!!s.flags[key]} label={label} onToggle={() => s.set({ flags: { ...s.flags, [key]: !s.flags[key] } })} />
    </div>
  ));

  return (
    <main className="home" aria-label="Team and sharing">
      <div className="homehead">
        <div><h1>Team &amp; sharing</h1><p className="muted">Who can see and change <b>{s.projectName}</b>, and what Bot may do in it.</p></div>
      </div>
      <div className="pagecols">
        <section className="pcardx" aria-label="Members">
          <h2>Members</h2>
          <div className="invite">
            <input aria-label="Email to invite" placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') invite(); }} />
            <select aria-label="Role for invite" value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((o) => <option key={o} value={o}>{o}</option>)}</select>
            <button className="pillbtn dark" onClick={invite}>Invite</button>
          </div>
          {s.members.map((m, i) => (
            <div key={m.id} className="member">
              <span className="initials truecol" style={{ background: AV_COLORS[i % AV_COLORS.length] }}>{initials(m.name)}</span>
              <div className="mwho"><b>{m.name}</b><span className="muted">{m.email}</span></div>
              {m.pending && <span className="pend">Invite sent</span>}
              {m.owner ? <span className="ownertag">Owner</span> : (
                <>
                  <select aria-label={`Role of ${m.name}`} value={m.role} onChange={(e) => s.set({ members: s.members.map((x) => (x.id === m.id ? { ...x, role: e.target.value as Role } : x)) })}>
                    {ROLES.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                  <button className="iconbtn" aria-label={`Remove ${m.name}`} onClick={() => s.set({ members: s.members.filter((x) => x.id !== m.id) })}><CloseIcon size={16} color="#111" /></button>
                </>
              )}
            </div>
          ))}
          <p className="muted" style={{ fontSize: 12, margin: '10px 0 0' }}>Owner: everything · Editor: change design and requirements · Commenter: comment and sketch · Viewer: look only.</p>
        </section>
        <div className="pagestack">
          <section className="pcardx" aria-label="Link sharing">
            <h2>Link sharing</h2>
            {flagRows(LINK_FLAGS)}
            <div className="linkrow">
              <code>newcad.app/p/{slug}</code>
              <button className="pillbtn" onClick={() => { void navigator.clipboard?.writeText(`https://newcad.app/p/${slug}`); s.showToast('Link copied'); }}>Copy link</button>
            </div>
          </section>
          <section className="pcardx" aria-label="Agents">
            <h2>Agents</h2>
            {flagRows(AGENT_FLAGS)}
          </section>
        </div>
      </div>
    </main>
  );
}
