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

export type StudyType = 'static' | 'modal' | 'thermal' | 'motion';
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
  // motion (MuJoCo)
  duration_s?: number;
  steps?: number;
  mates?: MotionMateResult[];
  drivers?: MotionDriverResult[];
  bodies?: { id: string; mass_kg: number }[];
  peak_bearing?: { mate: string; label: string; part: string | null; force_n: number; at_s: number };
  loop_error_mm?: number;
  sweep?: { parameter: string; backend: string; device: string; wall_s: number; variants: number; failed: number; rows: SweepRow[] };
  // thermal
  max_temperature_c?: number;
  max_temperature_at?: Where;
  min_temperature_c?: number;
}

export interface MotionMateResult {
  id: string;
  label: string;
  type: MateType;
  parts: [string, string];
  role: 'tree' | 'loop';
  peak_force_n: number;
  peak_at_s: number;
  peak_force_world: [number, number, number];
  /** force on each (non-ground) part from the other, in that part's modelled axes */
  peak_force_on: Record<string, [number, number, number]>;
  peak_moment_nm: number;
  range: [number, number] | null;
  range_unit: string;
  max_speed: number | null;
  speed_unit: string;
}

export interface MotionDriverResult { mate: string; kind: DriverKind; value: number; unit: string; peak_effort: number; rms_effort: number; effort_unit: string }

export interface SweepRow { value: number; ok: boolean; error?: string; peak_force_n?: Record<string, number>; peak_effort?: Record<string, number>; range?: Record<string, [number, number] | null> }

export interface MotionSeries {
  t: number[];
  mates: Record<string, { q: (number | null)[]; qd: (number | null)[]; force: [number, number, number][]; force_mag: number[]; moment_mag: number[] }>;
  drivers: Record<string, number[]>;
}

export type MateType = 'revolute' | 'prismatic' | 'ball' | 'fixed';
export type DriverKind = 'speed' | 'torque' | 'position';

export interface MotionDriver { mate: string; kind: DriverKind; value: number; ramp: number }
export interface MotionSpring { mate: string; stiffness: number; damping: number; rest: number }
export interface MotionSetup {
  duration: number;
  timestep: number;
  gravity: [number, number, number];
  contacts: boolean;
  damping: number;
  drivers: MotionDriver[];
  springs: MotionSpring[];
  sweep?: { parameter: string; values: number[] } | null;
  samples: number;
}

/** A mate (joint) from assembly.yaml, with its centre and axis as the engine resolves them from the picked faces. */
export interface MotionMate {
  id: string;
  type: MateType;
  parts: [string, string];
  label: string;
  faces: FaceRef[];
  origin?: [number, number, number] | null;
  axis?: [number, number, number] | null;
  limits?: [number, number] | null;
  origin_mm?: [number, number, number];
  axis_dir?: [number, number, number];
  problem?: string;
  warnings?: string[];
}

/** Bodies and joints of a motion study (engine coordinates: Z-up mm), for the Rapier preview. */
export interface Mechanism {
  key: string;
  bodies: { id: string; name: string; key: string; glb: string; mass_kg: number; com: [number, number, number]; inertia_kgmm2: number[][] }[];
  joints: { id: string; label: string; type: MateType; parts: [string, string]; origin: [number, number, number]; axis: [number, number, number]; role: 'tree' | 'loop'; limits_si: [number, number] | null }[];
  drivers: { mate: string; kind: DriverKind; value: number; value_si: number; ramp: number; unit: string }[];
  springs: { mate: string; stiffness_si: number; damping_si: number; rest_si: number }[];
  settings: { duration: number; timestep: number; gravity: [number, number, number]; contacts: boolean; damping: number };
  roots: string[];
  warnings: string[];
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
  motion?: MotionSetup | null;
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
  mates: MotionMate[];
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
