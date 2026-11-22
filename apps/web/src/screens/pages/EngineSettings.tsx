import { useEffect, useState } from 'react';
import { loadBotStatus, saveBotSettings, setSessionKey } from '../../engine/sync';
import { useApp } from '../../state/store';
import { Segmented } from '../../components/ui';

const EFFORTS = ['low', 'medium', 'high', 'max'] as const;

/** Which language model BuilderBot uses, and whether it can run. Stored by the engine. */
export function EngineSettings() {
  const bot = useApp((s) => s.eng?.bot);
  const [model, setModel] = useState(bot?.model ?? '');
  const [base, setBase] = useState(bot?.base_url ?? '');
  const [key, setKey] = useState('');
  useEffect(() => { void loadBotStatus(); }, []);
  useEffect(() => { setModel(bot?.model ?? ''); setBase(bot?.base_url ?? ''); }, [bot?.provider, bot?.model, bot?.base_url]);
  if (!bot) return <p className="muted">Loading…</p>;
  const prov = bot.providers.find((p) => p.id === bot.provider);
  return (
    <>
      <div className="srow">
        <div className="slabel"><b>Status</b><span className="muted">{bot.ready ? `Ready: ${prov?.label ?? bot.provider} · ${bot.model}` : bot.problem}</span></div>
        <div className="sctl"><span className="engbadge"><span className={`dot${bot.ready ? '' : ' off'}`} />{bot.ready ? 'Ready' : 'Needs setup'}</span></div>
      </div>
      <div className="srow">
        <div className="slabel"><b>Provider</b><span className="muted">Where BuilderBot's model runs. A local server works if it speaks the OpenAI API (LM Studio, Ollama, vLLM).</span></div>
        <div className="sctl">
          <select aria-label="Provider" value={bot.provider} onChange={(e) => void saveBotSettings({ provider: e.target.value, model: '', base_url: e.target.value === 'openai-compatible' ? base : '' })}>
            {bot.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
      </div>
      <div className="srow">
        <div className="slabel"><b>Model</b><span className="muted">Leave empty for the default{prov?.defaultModel ? ` (${prov.defaultModel})` : ''}.</span></div>
        <div className="sctl"><input className="stext" aria-label="Model" value={model} placeholder={prov?.defaultModel || 'model name'} onChange={(e) => setModel(e.target.value)} onBlur={() => model !== bot.model && void saveBotSettings({ model })} /></div>
      </div>
      {bot.provider === 'openai-compatible' && (
        <div className="srow">
          <div className="slabel"><b>Endpoint URL</b><span className="muted">For example http://localhost:1234/v1</span></div>
          <div className="sctl"><input className="stext" aria-label="Endpoint URL" value={base} onChange={(e) => setBase(e.target.value)} onBlur={() => base !== bot.base_url && void saveBotSettings({ base_url: base })} /></div>
        </div>
      )}
      <div className="srow">
        <div className="slabel"><b>Effort</b><span className="muted">Higher effort thinks longer per step: better parts, slower and more tokens.</span></div>
        <div className="sctl"><Segmented options={EFFORTS} value={(bot.effort ?? 'high') as (typeof EFFORTS)[number]} onChange={(v) => void saveBotSettings({ effort: v })} label="Effort" /></div>
      </div>
      {prov?.keyEnv && (
        <div className="srow">
          <div className="slabel"><b>API key</b><span className="muted">Best set as {prov.keyEnv} where the engine starts. A key entered here stays in the engine's memory only and is never written to disk.</span></div>
          <div className="sctl" style={{ display: 'flex', gap: 6 }}>
            <input className="stext" type="password" aria-label="API key" value={key} placeholder={bot.ready ? 'Key is set' : prov.keyEnv} onChange={(e) => setKey(e.target.value)} />
            <button className="pillbtn" disabled={!key.trim()} onClick={() => { void setSessionKey(bot.provider, key.trim()); setKey(''); }}>Use key</button>
          </div>
        </div>
      )}
    </>
  );
}
