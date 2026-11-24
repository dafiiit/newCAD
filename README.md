# newCAD

Desktop CAD app. See the implementation plan for the full architecture (React + Vite web UI, Tauri shell, Python engine).

## Repository layout

- `apps/web` — the React + Vite + TypeScript UI (react-three-fiber for the 3D view). Runs in any browser.
- `engine` — the Python engine: git-backed projects, sandboxed build123d workers, REST + WebSocket API, MCP server, BuilderBot, job queue and simulation (Gmsh + CalculiX for FEM, MuJoCo for motion).
- `packages/protocol` — JSON Schemas shared by engine and app (study and joint files).
- `compute-node` — Docker image and notes for a remote compute target (`newcad-engine --worker`).
- `validation` — analytic cases run in CI: FEM (cantilever, beam frequency, plate with hole, conduction) and motion (four-bar linkage, rotating link, bearing load hand-off).

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

It needs CalculiX on the engine machine. The repository ships it through [Pixi](https://pixi.sh) (`brew install pixi`, or see pixi.sh for Linux and Windows):

```sh
pnpm setup:sim   # pixi install: CalculiX from conda-forge into .pixi/envs/default
```

The engine finds `ccx` there by itself; restart it after the first install. A `ccx` on PATH (`apt install calculix-ccx`) or `NEWCAD_CCX=/path/to/ccx` works too. Gmsh comes from pip with the engine. Both are GPL and only ever run in a separate process (`python -m newcad_engine.sim.pipeline`).

Jobs go to a compute target: this computer, or a compute node started with `newcad-engine --worker` (see `compute-node/README.md`), added under Check → Compute targets. BuilderBot and external agents use the same studies through the `sim_*` MCP tools (`sim_create_study`, `sim_list_faces`, `sim_add_boundary`, `sim_run`, `sim_results`, …).

```sh
cd engine && uv run --extra dev python ../validation/report.py   # FEM and motion vs. analytic results
```

### Motion (MuJoCo)

A motion study (Check → New study → Motion) moves the parts as rigid bodies. Joints are mates in `assembly.yaml`: add a revolute, slider, ball or fixed joint and click the faces it connects (the bore of each part; one part alone is joined to ground). The engine takes the joint centre and axis from the picked round faces, builds an MJCF model (closed loops such as a four-bar become equality constraints) and runs MuJoCo. Drivers (speed, torque, move-to), springs and dampers are set per joint.

Results: the peak bearing load of every joint (force on each part, when it happens), driver effort, joint ranges, a time plot and playback of the motion in the viewport (`motion.glb`, one animation track per part). The `MJCF model` link downloads `model.xml` for MuJoCo's own viewer. **Use bearing load** turns a joint's peak load into a static stress study of that part: the load goes on the bore faces, the part is held at its other joints, and you can run CalculiX on it without retyping anything.

A parameter sweep (driver value, spring stiffness or damping, part mass, joint damping) runs every value as one job. On a compute target with an NVIDIA GPU and `mujoco-warp` installed (`pip install '.[cuda]'`, the compute-node image does this) all values run as parallel worlds on the GPU; elsewhere, including Macs, they run on a CPU process pool. Contacts between parts are off by default; switched on, boxes, cylinders and spheres stay primitives and other parts are split into convex pieces with CoACD.

**Grab and drag** runs a Rapier simulation of the same bodies and joints in the browser, so you can pull a part and feel how the mechanism moves. It is labelled as preview physics: every number in the Check tab comes from MuJoCo. Agents use the same setup through `motion_add_joint`, `motion_configure` and `sim_bearing_load`.

### BuilderBot's model

BuilderBot needs a language model. Pick it under Settings → BuilderBot model:

- **Claude (Anthropic)**, the default: set `ANTHROPIC_API_KEY` in the engine's environment. Default model `claude-opus-5-5` with server-side fallbacks enabled (if the model is overloaded, the API retries on a fallback model; turned off automatically for a custom base URL).
- **OpenAI**: set `OPENAI_API_KEY`.
- **OpenAI-compatible** (LM Studio, Ollama, MLX, vLLM): set the endpoint URL and model name in Settings; `NEWCAD_COMPAT_API_KEY` if the server wants one.

A key can also be pasted in Settings; the engine keeps it in memory only. For offline UI checks, `NEWCAD_ALLOW_SCRIPTED=1` unlocks a scripted test model.

### Developer feedback

"Send developer feedback" (menu on the What? and How? screens) goes through the engine, which saves every report in `~/.newcad/feedback/<id>.json` first and then files it as a GitHub issue in `dafiiit/newCAD` with the labels `feedback` and `feedback:bug` / `feedback:idea` / `feedback:question`. An attached model picture is committed to the `feedback-assets` branch and linked from the issue. The token comes from `NEWCAD_GITHUB_TOKEN`, `GITHUB_TOKEN` or the GitHub CLI login (`gh auth login`); `NEWCAD_FEEDBACK_REPO` points it at another repo. Reports that could not be sent stay `pending` and are retried on the next report and at engine start (`POST /api/feedback/retry` retries now).

To work through feedback: open issues with the `feedback` label, fix one, and close it from the PR (`Fixes #N`).

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
