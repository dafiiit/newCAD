# newCAD

Desktop CAD app. See the implementation plan for the full architecture (React + Vite web UI, Tauri shell, Python engine).

## Repository layout

- `apps/web` — the React + Vite + TypeScript UI (react-three-fiber for the 3D view). Runs in any browser.
- `engine` — the Python engine: git-backed projects, sandboxed build123d workers, REST + WebSocket API, MCP server, BuilderBot, job queue and simulation (Gmsh + CalculiX).
- `packages/protocol` — JSON Schemas shared by engine and app (the study file so far).
- `compute-node` — Docker image and notes for a remote compute target (`newcad-engine --worker`).
- `validation` — analytic FEM cases (cantilever, beam frequency, plate with hole, conduction) run in CI.

## Run the web UI

```sh
pnpm install
pnpm dev        # http://localhost:5173
pnpm build      # typecheck + production build
pnpm typecheck
```

Without an engine the UI runs on stub data (`apps/web/src/data/seed.ts`) and a mock model (`apps/web/src/model/parts.ts`). When an engine is running, the same UI loads real projects from it (see below); `apps/web/src/engine/` holds the client and the store sync.

## Run the engine

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
pnpm dev:engine   # engine on http://127.0.0.1:8765, creates a demo project on first start
pnpm dev          # in a second terminal; the dev server proxies /api and /mcp to the engine
pnpm test:engine  # engine tests
```

The engine keeps everything under `~/.newcad` (override with `NEWCAD_HOME`): one bare git repository per project, a content-addressed build cache, and `engine.json` with the port and a per-launch token. Every request except `/api/health` needs that token; the Vite dev server adds it for you.

### Simulation (Check tab)

Studies are files in the project: `studies/<id>.yaml` (static stress, natural frequencies, steady heat transfer). In the Check tab you add a study, click the faces that are held and loaded, and run it. The engine meshes with Gmsh, solves with CalculiX, and returns a field GLB with raw nodal values (von Mises, safety factor, displacement, temperature, mode shapes) that the viewport colours in its shader, so the legend range and the deformation scale change instantly. Results are cached by a hash of geometry and setup, so an unchanged version never re-runs.

It needs CalculiX on the engine machine: `apt install calculix-ccx` on Linux, `conda install -c conda-forge calculix` on macOS (or point `NEWCAD_CCX` at a `ccx` binary). Gmsh comes from pip with the engine. Both are GPL and only ever run in a separate process (`python -m newcad_engine.sim.pipeline`).

Jobs go to a compute target: this computer, or a compute node started with `newcad-engine --worker` (see `compute-node/README.md`), added under Check → Compute targets. BuilderBot and external agents use the same studies through the `sim_*` MCP tools (`sim_create_study`, `sim_list_faces`, `sim_add_boundary`, `sim_run`, `sim_results`, …).

```sh
cd engine && uv run --extra dev python ../validation/report.py   # FEM vs. beam theory table
```

### BuilderBot's model

BuilderBot needs a language model. Pick it under Settings → BuilderBot model:

- **Claude (Anthropic)**, the default: set `ANTHROPIC_API_KEY` in the engine's environment. Default model `claude-opus-5-5` with server-side fallbacks enabled (if the model is overloaded, the API retries on a fallback model; turned off automatically for a custom base URL).
- **OpenAI**: set `OPENAI_API_KEY`.
- **OpenAI-compatible** (LM Studio, Ollama, MLX, vLLM): set the endpoint URL and model name in Settings; `NEWCAD_COMPAT_API_KEY` if the server wants one.

A key can also be pasted in Settings; the engine keeps it in memory only. For offline UI checks, `NEWCAD_ALLOW_SCRIPTED=1` unlocks a scripted test model.

### Use NewCAD from Claude Desktop (MCP)

The engine is an MCP server: over HTTP at `http://127.0.0.1:<port>/mcp` (with the token as `Authorization: Bearer …`), and over stdio with `newcad-mcp`. For Claude Desktop add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "newcad": {
      "command": "uv",
      "args": ["--directory", "/path/to/newCAD/engine", "run", "newcad-mcp"]
    }
  }
}
```

Claude Desktop then sees the same projects as the app (tools for projects and versions, the What? spec, part code, rebuilds, measurements, snapshots and 3D comments). Edits it makes show up in a running app within about two seconds.

### Where things live in `apps/web/src`

- `state/store.ts` — one zustand store for the whole app (layers, questions, parts, studies, chat).
- `screens/what` — What? (requirements board and interview).
- `screens/how` — How? (3D viewport, parts/notes/code drawer, tool rail).
- `screens/check` — Check (studies, mock results overlay).
- `screens/pages` — Home, Team, Settings.
- `screens/overlays` — version history, part library, assembly picker, feedback.
- `components` — shared chrome (top bar, Bot chat) and UI atoms.
- `styles/app.css` — design tokens and styles ported from the design. Dark mode inverts `.app` and re-inverts `.truecol` elements.
