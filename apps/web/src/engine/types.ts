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
  source?: 'chat' | 'comment' | 'generate' | 'interview';
  note?: number;
  thread?: string | null;
  trace?: TraceEvent[];
  status?: BotTask['status'];
}

/** One step the Bot took: its reasoning, text it wrote between tool calls, or a tool call with its result. */
export interface TraceEvent {
  kind: 'thinking' | 'text' | 'tool';
  t: number;
  text?: string;
  tool?: string;
  label?: string;
  args?: Record<string, unknown>;
  status?: 'running' | 'ok' | 'error';
  ms?: number;
  result?: string;
  images?: number;
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
  thread?: string | null;
  trace?: TraceEvent[];
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

// ---------- simulation ----------

export type StudyType = 'static' | 'modal' | 'thermal';
export type BoundaryType = 'fixed' | 'force' | 'pressure' | 'gravity' | 'temperature' | 'heat_flux' | 'convection';

export interface FaceRef { part: string; tag: string; sig?: Record<string, unknown> | null }
export interface StudyBoundary {
  id: string;
  type: BoundaryType;
  label?: string;
  faces: FaceRef[];
  vector?: [number, number, number];
  value?: number;
  ambient?: number;
}

export interface Where { point: [number, number, number]; part: string | null; face: string | null }
export interface FieldInfo { label: string; unit: string; min: number; max: number }

export interface StudySummary {
  type: StudyType;
  study: string;
  mesh: { nodes: number; elements: number; order: number; min_quality: number; mean_quality: number; poor_elements: number };
  warnings: string[];
  fields: Record<string, FieldInfo>;
  timing_s: { mesh: number; solve: number; total: number };
  solver: { name: string; version: string | null; threads: number };
  deform_scale?: number;
  target?: string;
  // static
  max_von_mises_mpa?: number;
  max_von_mises_at?: Where;
  min_safety_factor?: number;
  min_safety_factor_at?: Where;
  max_displacement_mm?: number;
  max_displacement_at?: Where;
  safety_target?: number | null;
  reactions_n?: number[][];
  // modal
  frequencies_hz?: number[];
  modes?: { index: number; frequency_hz: number; max_at: Where }[];
  // thermal
  max_temperature_c?: number;
  max_temperature_at?: Where;
  min_temperature_c?: number;
}

export interface EngineJob {
  id: string;
  kind: string;
  project: string;
  study: string;
  name: string;
  ref: string;
  commit: string;
  key: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  stage: string;
  target: string | null;
  error: string | null;
  summary: StudySummary | null;
  cached: boolean;
  attempts: number;
  created: number;
}

export interface StudyState {
  status: 'none' | 'queued' | 'running' | 'done' | 'failed' | 'problem';
  problem?: string;
  key?: string;
  commit?: string;
  warnings?: string[];
  summary?: StudySummary;
  files?: Record<string, string>;
  job?: EngineJob;
}

export interface EngineStudy {
  id: string;
  name: string;
  type: StudyType;
  parts?: string[] | null;
  materials: Record<string, string>;
  boundaries: StudyBoundary[];
  mesh: { size?: number | null; order: 1 | 2 };
  modes: number;
  safety_target?: number | null;
  target: string;
  state?: StudyState;
}

export interface EngineTarget {
  id: string;
  name: string;
  kind: 'local' | 'remote';
  online: boolean;
  url?: string;
  slots?: number;
  running?: number;
  problem?: string;
  devices: {
    cpu: { model: string; performance_cores: number; logical_cores: number; arch: string };
    memory_gb: number | null;
    gpus: { name: string; memory_gb: number }[];
    platform: string;
    solvers: Record<string, string | null>;
  } | null;
}

export interface Material { name: string; E: number; nu: number; density: number; yield: number; conductivity: number }

export interface SimState {
  studies: EngineStudy[];
  jobs: Record<string, EngineJob>;
  targets: EngineTarget[] | null;
  materials: Material[];
  loaded: boolean;
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
  /** joints between parts of the checked-out version (assembly.yaml) */
  mates: EngineMate[];
  sim: SimState;
}

export interface EngineMate {
  id: string;
  type: 'fixed' | 'revolute' | 'slider' | 'cylindrical' | 'planar' | 'ball';
  a: string;
  b: string;
  name?: string;
  origin?: [number, number, number];
  axis?: [number, number, number];
  limits?: [number, number];
}
