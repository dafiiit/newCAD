# newCAD

Desktop CAD app. See the implementation plan for the full architecture (React + Vite web UI, Tauri shell, Python engine).

## Repository layout

- `apps/web` — the React + Vite + TypeScript UI (react-three-fiber for the 3D view). Runs in any browser.
- `packages/` — shared packages (protocol schemas later).

## Run the web UI

```sh
pnpm install
pnpm dev        # http://localhost:5173
pnpm build      # typecheck + production build
pnpm typecheck
```

The UI currently runs on stub data (`apps/web/src/data/seed.ts`) and a mock model (`apps/web/src/model/parts.ts`). No engine is needed yet.

### Where things live in `apps/web/src`

- `state/store.ts` — one zustand store for the whole app (layers, questions, parts, studies, chat).
- `screens/what` — What? (requirements board and interview).
- `screens/how` — How? (3D viewport, parts/notes/code drawer, tool rail).
- `screens/check` — Check (studies, mock results overlay).
- `screens/pages` — Home, Team, Settings.
- `screens/overlays` — version history, part library, assembly picker, feedback.
- `components` — shared chrome (top bar, Bot chat) and UI atoms.
- `styles/app.css` — design tokens and styles ported from the design. Dark mode inverts `.app` and re-inverts `.truecol` elements.
