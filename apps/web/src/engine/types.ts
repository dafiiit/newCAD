// Shapes of the engine's REST responses (only the fields the app reads).

export interface ProjectSummary {
  id: string;
  name: string;
  goal: string;
  created: number;
  updated: number;
  head: string;
  headCommit: string;
  branches: string[];
  parts: { id: string; name: string }[];
}

export interface BBox { min: [number, number, number]; max: [number, number, number] }

export interface ManifestPart {
  id: string;
  name: string;
  color: string;
  material: string;
  file: string;
  ok: boolean;
  key?: string;
  cached?: boolean;
  glb?: string;
  mass_kg?: number;
  volume_mm3?: number;
  center?: [number, number, number];
  /** Z-up assembly coordinates. */
  bbox?: BBox;
  faces?: number;
  triangles?: number;
  log?: string;
  error?: string;
  line?: number | null;
}

export interface Manifest {
  project: string;
  ref: string;
  commit: string;
  parts: ManifestPart[];
  ok: boolean;
  mass_kg: number;
  cg: [number, number, number] | null;
  bbox: BBox | null;
  build_ms: number;
}

export interface EngineCommit {
  id: string;
  short: string;
  branch: string;
  parents: string[];
  message: string;
  author: string;
  time: number;
  files: string[];
}

export interface EngineLog {
  commits: EngineCommit[];
  tips: Record<string, string>;
  head: string;
  headBranch: string | null;
  headCommit: string;
  branches: string[];
}

export interface SpecAnswer { text: string; by: 'you' | 'bot' | 'agent'; assumption?: boolean }
export interface SpecQuestion {
  id: string;
  text: string;
  examples?: string[];
  assume?: string;
  by?: string;
  parent?: string;
  answers?: SpecAnswer[];
}
export interface SpecCategory { id: string; name: string; questions: SpecQuestion[] }
export interface Spec { goal?: string; overview?: string; categories: SpecCategory[] }

export interface EngineNote {
  id: number;
  part: string;
  point: [number, number, number] | null;
  face: string | null;
  status: 'open' | 'queued' | 'resolved';
  msgs: { who: string; text: string }[];
  face_now?: string | null;
}

export interface EngineChatMessage {
  who: 'you' | 'bot' | 'system';
  text: string;
  t: number;
  ctx?: string | null;
  task?: string;
  branch?: string;
  actions?: ('apply' | 'checkout' | 'history')[];
  question?: string | null;
  group?: string;
}

export interface BotTask {
  id: string;
  project: string;
  mode: string;
  goal: string;
  branch: string;
  status: 'running' | 'done' | 'failed' | 'stopped';
  label: string;
  step: number;
  max_steps: number;
  reply: string;
  problem: string;
  group: string | null;
  concept: string | null;
  mass_kg: number | null;
  builds: boolean | null;
}

export interface BotGroup { id: string; project: string; status: 'running' | 'done' | 'failed'; tasks: BotTask[] }

export interface ProviderInfo { id: string; label: string; defaultModel: string; keyEnv: string }
export interface BotStatus {
  provider: string;
  model: string;
  base_url?: string;
  ready: boolean;
  problem?: string;
  key_source?: string;
  providers: ProviderInfo[];
  effort?: string;
  max_steps?: number;
  [k: string]: unknown;
}

/** Engine slice of the app store; null while the app runs on mock data. */
export interface EngineState {
  online: boolean;
  pid: string | null;
  projects: ProjectSummary[];
  manifest: Manifest | null;
  building: boolean;
  log: EngineLog | null;
  files: Record<string, string>;
  bot: BotStatus | null;
  tasks: Record<string, BotTask>;
  /** question key on the sheet ('cat:i', 'cat:i:f0') ↔ spec question id */
  keyOf: Record<string, string>;
  qidOf: Record<string, string>;
  /** card id → index of the answer in spec.yaml */
  cardAns: Record<number, { qid: string; idx: number }>;
  compare: Record<string, { mass_kg: number; ok: boolean }>;
}
