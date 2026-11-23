export type Version = 1 | 2 | 3;
export type Layer = 'home' | 'what' | 'how' | 'check' | 'team' | 'settings';
export type CardType = 'text' | 'image' | 'video' | 'model' | 'sketch';
export type Role = 'Owner' | 'Editor' | 'Commenter' | 'Viewer';

export interface Category {
  id: string;
  name: string;
  qs: string[];
  /** 'gen' marks the generic question set a fresh project starts with. */
  src?: 'gen';
}

export interface QuestionInfo {
  ask?: string;
  ex: string[];
  assume: string;
}

export interface FollowUp {
  text: string;
  ex: string[];
  assume: string;
}

export interface Card {
  id: number;
  type: CardType;
  text: string;
  label: string;
  by: 'you' | 'agent';
  doodle?: boolean;
  strokes?: [number, number][][];
}

export interface Concept {
  name: string;
  tag: string;
  mass: string;
  sf: string;
  stress: string;
  cost: string;
  note: string;
  rec?: boolean;
}

export interface Connection {
  type: string;
  a: string;
  b: string;
  title: string;
  how: Record<string, string>;
}

export interface MateType {
  id: string;
  name: string;
  dof: number | null;
  d: string;
}

export interface Commit {
  id: string;
  branch: string;
  parents: string[];
  ver: Version;
  msg: string;
  who: string;
  t: string;
  diff: string;
}

export interface CommunityDesign {
  id: string;
  name: string;
  author: string;
  tag: string;
  kind: 'gear' | 'bracket' | 'turbine' | 'clamp';
  likes: number;
  remixes: number;
}

export interface ChatMessage {
  who: 'you' | 'bot';
  text: string;
  ctx?: string | null;
  /** Buttons under a Bot reply (engine mode): apply or check out its branch, open the history. */
  actions?: ('apply' | 'checkout' | 'history')[];
  branch?: string;
  /** Engine mode: which conversation it belongs to (a Bot task, a prototype run, the interview), where it came from, and when (s). */
  thread?: string;
  source?: 'chat' | 'comment' | 'generate' | 'interview';
  t?: number;
  /** Engine mode: the Bot task behind the message, and for a Bot reply the steps it took to get there. */
  task?: string;
  trace?: import('../engine/types').TraceEvent[];
  status?: 'running' | 'done' | 'failed' | 'stopped';
}

export interface ChatThread {
  id: string;
  project: string;
  title: string;
  when: string;
  msgs: ChatMessage[];
}

export type LibraryIcon = 'bolt' | 'nut' | 'profile' | 'bearing' | 'motor' | 'robot' | 'gear' | 'assembly';

export interface LibraryPart {
  id: string;
  cat: string;
  name: string;
  std: string;
  icon: string;
  spec: string;
  variants: string[];
  material: string;
  mass: string;
  source: string;
}

export interface Study {
  id: string;
  group: string;
  icon: string;
  title: string;
  sub: string;
  engine: string;
}

export type SettingType = 'text' | 'select' | 'toggle' | 'seg' | 'range' | 'connect';

export interface SettingRow {
  key: string;
  label: string;
  help: string;
  type: string;
  def: string | number | boolean;
  opts?: string[];
  min?: number;
  max?: number;
  step?: number;
  fmt?: string;
}

export interface SettingsSection {
  id: string;
  title: string;
  intro: string;
  rows: SettingRow[];
}

export interface Member {
  id: string;
  name: string;
  email: string;
  role: Role;
  owner?: boolean;
  pending?: boolean;
}

export interface Pin {
  id: number;
  part: string;
  /** World position in model millimetres. */
  p: [number, number, number];
  resolved?: boolean;
  msgs: { who: string; text: string }[];
  /** Engine mode: face tag under the pin, cache key of the build it came from, and whether Bot has it queued. */
  face?: string | null;
  key?: string | null;
  queued?: boolean;
  /** Not saved in the engine yet (a pin placed but no text sent). */
  draft?: boolean;
}
