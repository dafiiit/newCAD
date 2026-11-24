// Thin client for the NewCAD engine (REST + WebSocket).
// In development the Vite dev server proxies /api and /mcp to the engine and adds the
// engine token, so the browser never needs it. A build served elsewhere can point at an
// engine with VITE_ENGINE_URL and pass the token once as ?token=… in the page URL.

const BASE: string = (import.meta.env.VITE_ENGINE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

function readToken(): string {
  try {
    const q = new URLSearchParams(window.location.search).get('token');
    if (q) { sessionStorage.setItem('newcad.token', q); return q; }
    return sessionStorage.getItem('newcad.token') ?? (import.meta.env.VITE_ENGINE_TOKEN as string | undefined) ?? '';
  } catch {
    return '';
  }
}
const TOKEN = readToken();

export class EngineError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (TOKEN) h.set('X-NewCAD-Token', TOKEN);
  return h;
}

/** URL for things the browser loads by itself (images, downloads). */
export function assetUrl(path: string): string {
  if (!TOKEN) return BASE + path;
  return `${BASE}${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(TOKEN)}`;
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    method: init.method ?? (init.body === undefined ? 'GET' : 'POST'),
    headers: headers(init.body === undefined ? undefined : { 'Content-Type': 'application/json' }),
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    signal: init.signal,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch { /* not JSON */ }
    throw new EngineError(res.status, detail);
  }
  const ct = res.headers.get('content-type') ?? '';
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>;
}

export async function apiBuffer(path: string): Promise<ArrayBuffer> {
  const res = await fetch(BASE + path, { headers: headers() });
  if (!res.ok) throw new EngineError(res.status, res.statusText);
  return res.arrayBuffer();
}

export async function apiBlob(path: string, body: unknown): Promise<{ blob: Blob; name: string }> {
  const res = await fetch(BASE + path, { method: 'POST', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    throw new EngineError(res.status, detail);
  }
  const cd = res.headers.get('content-disposition') ?? '';
  const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd)?.[1] ?? 'export';
  return { blob: await res.blob(), name: decodeURIComponent(name) };
}

/** True when an engine answers on /api/health (and, if it needs one, accepts our token). */
export async function probe(): Promise<boolean> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 4000);
    const h = await api<{ ok: boolean; name: string }>('/api/health', { signal: ctl.signal });
    clearTimeout(t);
    if (!h?.ok || h.name !== 'newcad-engine') return false;
    await api('/api/version'); // checks the token
    return true;
  } catch {
    return false;
  }
}

export type EngineEvent = { type: string; [k: string]: unknown };

/** Opens the event socket and reconnects with backoff. Returns a function that closes it. */
export function connectEvents(onEvent: (e: EngineEvent) => void, onState?: (up: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let delay = 500;
  const open = () => {
    const base = BASE || window.location.origin;
    const url = `${base.replace(/^http/, 'ws')}/api/ws${TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ''}`;
    ws = new WebSocket(url);
    ws.onopen = () => { delay = 500; onState?.(true); };
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data as string)); } catch { /* ignore bad frames */ } };
    ws.onclose = () => {
      onState?.(false);
      if (closed) return;
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 8000);
    };
  };
  open();
  return () => { closed = true; ws?.close(); };
}
