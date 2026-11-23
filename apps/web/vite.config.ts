import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server forwards /api and /mcp to the NewCAD engine and adds the engine's
// per-launch token, which the engine writes to ~/.newcad/engine.json (or $NEWCAD_HOME).
// Start the engine with `pnpm dev:engine` (port 8765). Without an engine the app runs on mock data.
const home = process.env.NEWCAD_HOME ?? join(homedir(), '.newcad');

function runtime(): { url: string; token: string } {
  try {
    const j = JSON.parse(readFileSync(join(home, 'engine.json'), 'utf8'));
    return { url: j.url, token: j.token };
  } catch {
    return { url: process.env.NEWCAD_ENGINE_URL ?? 'http://127.0.0.1:8765', token: process.env.NEWCAD_TOKEN ?? '' };
  }
}

const target = process.env.NEWCAD_ENGINE_URL ?? runtime().url;

const proxy: ProxyOptions = {
  target,
  changeOrigin: true,
  ws: true,
  configure: (p) => {
    // read the token per request, so restarting the engine doesn't need a dev-server restart
    p.on('proxyReq', (req) => { const t = runtime().token; if (t) req.setHeader('X-NewCAD-Token', t); });
    p.on('proxyReqWs', (req) => { const t = runtime().token; if (t) req.setHeader('X-NewCAD-Token', t); });
    p.on('error', () => { /* engine not running: the app falls back to mock data */ });
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': proxy, '/mcp': proxy } },
  preview: { proxy: { '/api': proxy, '/mcp': proxy } },
});
