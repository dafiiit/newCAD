import { useEffect, useState } from 'react';
import { deleteProfile, listProfileModels, loadBotStatus, saveBotSettings, saveProfile, setProfileKey, switchProfile } from '../../engine/sync';
import { useApp } from '../../state/store';
import { Segmented } from '../../components/ui';

const EFFORTS = ['low', 'medium', 'high', 'max'] as const;
const AUTHS = [
  { id: 'auto', label: 'Provider default' },
  { id: 'bearer', label: 'Authorization: Bearer' },
  { id: 'x-api-key', label: 'x-api-key header' },
] as const;

/** Which language models BuilderBot can use, which one is active, and whether it can run. Stored by the engine;
 *  API keys go to the OS keychain, never into the settings file. */
export function EngineSettings() {
  const bot = useApp((s) => s.eng?.bot);
  const profiles = bot?.profiles ?? [];
  const active = profiles.find((p) => p.id === bot?.active_profile);
  const [name, setName] = useState(active?.name ?? '');
  const [model, setModel] = useState(bot?.model ?? '');
  const [base, setBase] = useState(bot?.base_url ?? '');
  const [key, setKey] = useState('');
  const [found, setFound] = useState<{ models: string[]; error?: string } | null>(null);
  const [looking, setLooking] = useState(false);
  useEffect(() => { void loadBotStatus(); }, []);
  useEffect(() => { setModel(bot?.model ?? ''); setBase(bot?.base_url ?? ''); }, [bot?.provider, bot?.model, bot?.base_url]);
  useEffect(() => { setName(active?.name ?? ''); setFound(null); setKey(''); }, [active?.id, active?.name]);
  if (!bot) return <p className="muted">Loading…</p>;
  const prov = bot.providers.find((p) => p.id === bot.provider);
  const local = bot.provider === 'openai-compatible';
  const onThisMachine = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(base);
  const lookUp = async () => {
    if (!active) return;
    setLooking(true);
    const r = await listProfileModels(active.id);
    setLooking(false);
    setFound(r);
    if (r.models.length && !model) { setModel(r.models[0]); void saveBotSettings({ model: r.models[0] }); }
  };
  return (
    <>
      <div className="srow">
        <div className="slabel"><b>Status</b><span className="muted">{bot.ready ? `Ready: ${active?.name ?? prov?.label ?? bot.provider} · ${bot.model}` : bot.problem}</span></div>
        <div className="sctl"><span className="engbadge"><span className={`dot${bot.ready ? '' : ' off'}`} />{bot.ready ? 'Ready' : 'Needs setup'}</span></div>
      </div>
      <div className="srow">
        <div className="slabel"><b>Model in use</b><span className="muted">Keep several models (say a local one and one on a server) and switch here or in the Bot chat. The fields below edit the one in use.</span></div>
        <div className="sctl" style={{ display: 'flex', gap: 6 }}>
          <select aria-label="Model in use" value={bot.active_profile ?? ''} onChange={(e) => void switchProfile(e.target.value)}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="pillbtn" onClick={() => void saveProfile({ name: 'New model', provider: 'openai-compatible', activate: true })}>Add</button>
          {profiles.length > 1 && active && (
            <button className="pillbtn" onClick={() => { if (window.confirm(`Remove ${active.name} and its saved key?`)) void deleteProfile(active.id); }}>Remove</button>
          )}
        </div>
      </div>
      {active && (
        <div className="srow">
          <div className="slabel"><b>Name</b><span className="muted">How this model shows up in the switcher.</span></div>
          <div className="sctl"><input className="stext" aria-label="Profile name" value={name} maxLength={60} onFocus={(e) => e.target.select()} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== active.name && void saveProfile({ id: active.id, name: name.trim() })} /></div>
        </div>
      )}
      <div className="srow">
        <div className="slabel"><b>Provider</b><span className="muted">Where the model runs. A server that speaks the OpenAI API (LM Studio, Ollama, vLLM, a gateway) uses OpenAI-compatible; one that speaks the Anthropic API uses Claude with an endpoint URL.</span></div>
        <div className="sctl">
          <select aria-label="Provider" value={bot.provider} onChange={(e) => void saveBotSettings({ provider: e.target.value, model: '', base_url: e.target.value === 'openai-compatible' || e.target.value === 'anthropic' ? base : '' })}>
            {bot.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
      </div>
      {(local || bot.provider === 'anthropic' || !!base) && (
        <div className="srow">
          <div className="slabel"><b>Endpoint URL</b><span className="muted">{local ? 'For example http://localhost:1234/v1' : 'Leave empty for the official API. Set it for a compatible server or gateway.'}</span></div>
          <div className="sctl"><input className="stext" aria-label="Endpoint URL" value={base} placeholder={local ? 'http://localhost:1234/v1' : 'official API'} onChange={(e) => setBase(e.target.value)} onBlur={() => base !== (bot.base_url ?? '') && void saveBotSettings({ base_url: base.trim() })} /></div>
        </div>
      )}
      <div className="srow">
        <div className="slabel">
          <b>Model</b>
          <span className="muted">{prov?.defaultModel ? `Leave empty for the default (${prov.defaultModel}).` : 'The model name the server exposes.'}{found?.error ? ` ${found.error}.` : found && !found.models.length ? ' The server lists no models.' : ''}</span>
        </div>
        <div className="sctl" style={{ display: 'flex', gap: 6 }}>
          {found?.models.length ? (
            <select aria-label="Model" value={found.models.includes(model) ? model : ''} onChange={(e) => { setModel(e.target.value); void saveBotSettings({ model: e.target.value }); }}>
              {!found.models.includes(model) && <option value="">{model || 'Pick a model'}</option>}
              {found.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input className="stext" aria-label="Model" value={model} placeholder={prov?.defaultModel || 'model name'} onChange={(e) => setModel(e.target.value)} onBlur={() => model !== bot.model && void saveBotSettings({ model })} />
          )}
          {(local || !!base) && <button className="pillbtn" disabled={looking} onClick={() => void lookUp()}>{looking ? 'Asking…' : 'List models'}</button>}
        </div>
      </div>
      <div className="srow">
        <div className="slabel"><b>Effort</b><span className="muted">Higher effort thinks longer per step: better parts, slower and more tokens.</span></div>
        <div className="sctl"><Segmented options={EFFORTS} value={(bot.effort ?? 'high') as (typeof EFFORTS)[number]} onChange={(v) => void saveBotSettings({ effort: v })} label="Effort" /></div>
      </div>
      {active && (
        <div className="srow">
          <div className="slabel">
            <b>API key</b>
            <span className="muted">
              {active.has_key ? 'A key is saved for this model. ' : local && onThisMachine ? 'Servers on this computer usually need none. ' : ''}
              {bot.keychain ? 'Saved in your system keychain, never in a file.' : 'This machine has no keychain: the key stays in the engine\'s memory until it stops.'}
              {prov?.keyEnv && !active.has_key ? ` ${prov.keyEnv} in the engine's environment works too.` : ''}
            </span>
          </div>
          <div className="sctl" style={{ display: 'flex', gap: 6 }}>
            <input className="stext" type="password" autoComplete="off" aria-label="API key" value={key} placeholder={active.has_key ? '•••••••• saved' : 'Paste key'} onChange={(e) => setKey(e.target.value)} />
            <button className="pillbtn" disabled={!key.trim()} onClick={() => { void setProfileKey(active.id, key.trim()); setKey(''); }}>Save key</button>
            {active.has_key && <button className="pillbtn" onClick={() => void setProfileKey(active.id, '')}>Remove</button>}
          </div>
        </div>
      )}
      {active && (!!base || active.auth !== 'auto') && (
        <div className="srow">
          <div className="slabel"><b>Send key as</b><span className="muted">Only for servers that expect the key in a different header than their API usually does.</span></div>
          <div className="sctl">
            <select aria-label="Send key as" value={active.auth ?? 'auto'} onChange={(e) => void saveBotSettings({ auth: e.target.value })}>
              {AUTHS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </div>
        </div>
      )}
    </>
  );
}
