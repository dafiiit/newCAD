// App state. Without an engine everything here is client-side mock behaviour.
// When an engine answers, engine/sync.ts loads the project into this store and
// swaps the mock actions for ones that call the engine (REST + WebSocket).
import { create } from 'zustand';
import {
  AHEAD_STAGES, BRANCH_COLORS, CATS, CHAT_SEED, EXTRA_COLORS, FOLLOWUPS, FOLLOWUPS_GEN, MORE_QS, MORE_QS_GEN,
  OVERVIEW_FACTS, OVERVIEW_SEED, PROPS, QINFO, QINFO_GEN, SEED_COMMITS, SETTINGS_DEF, STUDIES,
} from '../data/seed';
import type { BoundaryType, EngineState, MateType } from '../engine/types';
import type { Card, CardType, Category, ChatMessage, ChatThread, Commit, FollowUp, Layer, Member, Pin, QuestionInfo, Version } from '../data/types';

export type Menu = null | 'account' | 'more' | 'cube' | 'mate' | 'export' | 'analysis' | 'view';
export type Display = 'edges' | 'shaded' | 'wire';
export type HowTab = 'parts' | 'notes' | 'code';
export type Analysis = null | 'interf' | 'mass' | 'cg';
export type CutAxis = 'x' | 'y' | 'z';
export type CameraView = 'iso' | 'front' | 'top' | 'side';

interface Agent { label: string; step: number; total: number; pct: number }
/** Faces being picked on the model for a new support or load (engine Check tab). */
export interface SimPick { type: BoundaryType; faces: { part: string; tag: string; key: string | null }[]; vector: [number, number, number]; value: number | null; ambient: number | null; label: string }
export interface MatePick { type: MateType; faces: { part: string; tag: string; key: string | null }[]; label: string }
export interface SimProbe { value: number; unit: string; label: string; point: [number, number, number]; part: string | null; face: string | null }
interface Interview { keys: string[]; i: number; answered: number; r1: number; fq: number }
type Settings = Record<string, string | number | boolean>;
type Cat = Category & { orig: (number | null)[] };

export interface AppState {
  // navigation and chrome
  layer: Layer;
  lastLayer: Layer;
  menu: Menu;
  toast: string | null;
  expert: boolean;
  drawer: boolean;
  drawerW: Record<'main' | 'code', number>;
  projectName: string;
  agent: Agent | null;

  // What?
  cats: Cat[];
  cards: Record<string, Card[]>;
  qMeta: Record<string, 'you' | 'more'>;
  fups: Record<string, FollowUp[]>;
  ansDraft: Record<string, string>;
  overview: string;
  ovBy: 'you' | 'agent';
  ovFacts: string[];
  whatView: 'overview' | 'cat';
  cat: string;
  q: number;
  expanded: Record<string, boolean>;
  iv: Interview | null;
  ahead: number;
  agentBarHidden: boolean;
  newQCat: string | null;
  addingCat: boolean;

  // How?
  version: Version;
  selected: string | null;
  hovered: string | null;
  howTab: HowTab;
  display: Display;
  xray: boolean;
  zebra: boolean;
  cut: { ax: CutAxis; pct: number } | null;
  explode: number;
  analysis: Analysis;
  anHi: string[] | null;
  hiConn: number | null;
  camera: { view: CameraView; nonce: number };
  tool: null | 'comment';
  pins: Pin[];
  openPin: number | null;
  showResolved: boolean;
  folders: { id: string; name: string; open: boolean }[];
  floc: Record<string, string | null>;
  libParts: { id: string; name: string; variant: string; qty: number }[];

  // Check
  study: string;
  studyDone: Record<string, boolean>;
  studyRun: string | null;
  mode: number;
  playing: boolean;
  rpm: number;
  /** engine Check tab: selected study, face picking, probe, result display */
  simSel: string | null;
  simPick: SimPick | null;
  simProbe: SimProbe | null;
  simField: string | null;
  simRange: [number, number] | null;
  simDeform: number;
  /** engine Check tab, motion studies: joint picking, playback time (s), grab-and-drag preview, live poses of a running job */
  matePick: MatePick | null;
  motionT: number;
  motionSpeed: number;
  motionPreview: boolean;
  motionLive: { study: string; key: string; frame: Record<string, number[]> } | null;

  // Bot chat
  chatOpen: boolean;
  chatFull: boolean;
  chatSide: boolean;
  chatText: string;
  typing: boolean;
  msgs: ChatMessage[];
  chats: ChatThread[];
  activeChat: string;
  chatSearch: string;
  botLogOpen: boolean;
  attachOpen: boolean;

  // overlays
  review: boolean;
  commits: Commit[];
  head: string;
  selCommit: string;
  branchColors: Record<string, string>;
  libOpen: boolean;
  asmPick: boolean;
  feedbackOpen: boolean;

  // engine (null = mock mode)
  eng: EngineState | null;
  /** Engine mode: suggestions and default assumption per question key. */
  qInfo: Record<string, QuestionInfo | FollowUp>;

  // pages
  settings: Settings;
  members: Member[];
  flags: Record<string, boolean>;
  commFilter: string;
  liked: Record<string, boolean>;
  remixed: string[];
}

export interface AppActions {
  set: (patch: Partial<AppState>) => void;
  go: (layer: Layer) => void;
  toggleMenu: (m: Exclude<Menu, null>) => void;
  showToast: (text: string) => void;
  runAgent: (steps: string[], done?: () => void) => void;
  userSays: (text: string, ctx?: string | null) => void;
  say: (text: string) => void;
  sendChat: () => void;

  addCard: (key: string, type: CardType, text?: string, by?: Card['by']) => void;
  updateCard: (key: string, id: number, patch: Partial<Card>) => void;
  removeCard: (key: string, id: number) => void;
  submitAnswer: (key: string, text: string) => void;
  addQuestion: (catId: string, text: string) => void;
  deleteQuestion: (catId: string, i: number) => void;
  addCategory: (name: string) => void;
  startInterview: () => void;
  answerIv: (text: string, mode: 'answer' | 'assume' | 'skip') => void;
  buildNow: () => void;
  generate: () => void;

  select: (id: string | null) => void;
  setCamera: (view: CameraView) => void;
  checkout: (id: string) => void;
  addCommit: (opts: { msg: string; diff?: string; who?: string; branch?: string; ver?: Version; from?: string }) => Commit;
  runStudy: (id: string) => void;
  addPin: (part: string, p: [number, number, number], extra?: { face?: string | null; key?: string | null }) => void;
  sendPinComment: (id: number, text: string, queue: boolean) => void;
}

export type Store = AppState & AppActions;

// ---------- helpers ----------

let nextId = 100;
const timers = new Set<ReturnType<typeof setTimeout>>();
function later(fn: () => void, ms: number) {
  const t = setTimeout(() => { timers.delete(t); fn(); }, ms);
  timers.add(t);
}
let aheadTimer: ReturnType<typeof setTimeout> | null = null;

function hhmm() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function newHash() { return Math.floor(Math.random() * 0xffff).toString(16).padStart(4, '0'); }

export function defaultSettings(): Settings {
  const o: Settings = {};
  for (const s of SETTINGS_DEF) for (const r of s.rows) o[r.key] = r.def;
  return o;
}

function initialCards(): Record<string, Card[]> {
  let id = 1;
  const mk = (type: CardType, text = '', label = ''): Card => ({ id: id++, type, text, label, by: 'you', strokes: [], doodle: type === 'sketch' });
  return {
    'function:0': [
      mk('text', 'Hold the generator coaxial with the turbine shaft.'),
      mk('text', 'Carry the generator weight and rotor vibration into the rig frame.'),
      mk('sketch', '', 'Side view – L-bracket idea'),
      mk('image', '', 'Photo: current test rig'),
      mk('model', '', 'turbine_shaft.step (reference)'),
    ],
    'function:1': [mk('text', 'Generator about 4 kg, mounted overhanging.'), mk('video', '', 'Rig running at full flow')],
    'function:2': [mk('text', 'Generator flange: 4 × M8 bolts.'), mk('text', 'Base bolts onto the existing frame rails.')],
    'manufacturing:0': [mk('text', 'Laser-cut steel plates, welded.')],
    'compatibility:0': [mk('text', 'Must fit between the frame rails without modifying them.')],
    'sustainability:0': [mk('text', 'Submerged in water – must resist corrosion.')],
    'sustainability:1': [mk('text', 'Prefer recyclable metals over composites.')],
  };
}

const withOrig = (c: Category): Cat => ({ ...c, orig: c.qs.map((_, j) => j) });

/** Question info (suggestions and the assumption Bot makes) for 'cat:i' and follow-up keys 'cat:i:f0'. */
export function infoOf(s: Pick<AppState, 'cats' | 'fups'> & Partial<Pick<AppState, 'qInfo'>>, key: string): QuestionInfo | FollowUp | null {
  if (s.qInfo && s.qInfo[key]) return s.qInfo[key];
  const a = key.split(':');
  if (a.length > 2) return s.fups[`${a[0]}:${a[1]}`]?.[Number(a[2].slice(1))] ?? null;
  const c = s.cats.find((x) => x.id === a[0]);
  if (!c) return null;
  const o = c.orig[Number(a[1])];
  if (o === null || o === undefined) return null;
  // -1 marks the extra question Bot adds per topic in the second round
  if (o === -1) return (c.src === 'gen' ? MORE_QS_GEN : MORE_QS)[c.id] ?? null;
  return (c.src === 'gen' ? QINFO_GEN : QINFO)[`${a[0]}:${o}`] ?? null;
}

export function allQKeys(s: Pick<AppState, 'cats' | 'fups'>): string[] {
  const out: string[] = [];
  for (const c of s.cats) c.qs.forEach((_, i) => {
    const k = `${c.id}:${i}`;
    out.push(k);
    (s.fups[k] ?? []).forEach((_, j) => out.push(`${k}:f${j}`));
  });
  return out;
}

export function openKeys(s: Pick<AppState, 'cats' | 'fups' | 'cards'>): string[] {
  return allQKeys(s).filter((k) => !(s.cards[k] ?? []).length);
}

export function ivCurrent(s: Pick<AppState, 'iv'>): string | null {
  return s.iv && s.iv.i < s.iv.keys.length ? s.iv.keys[s.iv.i] : null;
}

export function aheadStage(p: number): string {
  let label = AHEAD_STAGES[0][1];
  for (const [at, l] of AHEAD_STAGES) if (p >= at) label = l;
  return label;
}

export function headCommit(s: Pick<AppState, 'commits' | 'head'>): Commit | undefined {
  return s.commits.find((c) => c.id === s.head);
}

function scrollToId(id: string, block: ScrollLogicalPosition = 'start') {
  later(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block }), 60);
}

// ---------- store ----------

export const useApp = create<Store>()((set, get) => ({
  layer: 'what',
  lastLayer: 'what',
  menu: null,
  toast: null,
  expert: false,
  drawer: true,
  drawerW: { main: 320, code: 520 },
  projectName: 'Generator mount',
  agent: null,

  cats: CATS.map(withOrig),
  cards: initialCards(),
  qMeta: {},
  fups: {},
  ansDraft: {},
  overview: OVERVIEW_SEED,
  ovBy: 'you',
  ovFacts: OVERVIEW_FACTS,
  whatView: 'overview',
  cat: 'function',
  q: 0,
  expanded: { function: true },
  iv: null,
  ahead: 0,
  agentBarHidden: false,
  newQCat: null,
  addingCat: false,

  version: 2,
  selected: null,
  hovered: null,
  howTab: 'parts',
  display: 'edges',
  xray: false,
  zebra: false,
  cut: null,
  explode: 0,
  analysis: null,
  anHi: null,
  hiConn: null,
  camera: { view: 'iso', nonce: 0 },
  tool: null,
  pins: [{
    id: 1, part: 'upright', p: [-100, 50, 0],
    msgs: [
      { who: 'You', text: 'Cable gland exits here, keep about 20 mm clear.' },
      { who: 'Bot', text: 'Noted. Concept B keeps the area between the gussets free for the gland.' },
    ],
  }],
  openPin: null,
  showResolved: false,
  folders: [{ id: 'f1', name: 'Bracket', open: true }, { id: 'f2', name: 'Drive', open: true }],
  floc: { plate: 'f1', upright: 'f1', gusset: 'f1', bolts: 'f1', flange: 'f2', gen: 'f2', shaft: 'f2', hub: 'f2' },
  libParts: [],

  study: 'static',
  studyDone: {},
  studyRun: null,
  mode: 1,
  playing: true,
  rpm: 300,
  simSel: null,
  simPick: null,
  simProbe: null,
  simField: null,
  simRange: null,
  simDeform: 1,
  matePick: null,
  motionT: 0,
  motionSpeed: 0.25,
  motionPreview: false,
  motionLive: null,

  chatOpen: false,
  chatFull: false,
  chatSide: true,
  chatText: '',
  typing: false,
  msgs: [{ who: 'bot', text: 'Hi, I am Bot. Tell me what you want to build, in a sentence or two. I will ask the right questions for each part of the spec, note your answers on the board, and start building prototypes while we talk.' }],
  chats: CHAT_SEED.slice(),
  activeChat: 'live',
  chatSearch: '',
  botLogOpen: false,
  attachOpen: false,

  review: false,
  commits: SEED_COMMITS.slice(),
  head: '9b11',
  selCommit: '9b11',
  branchColors: { ...BRANCH_COLORS },
  libOpen: false,
  asmPick: false,
  feedbackOpen: false,

  eng: null,
  qInfo: {},

  settings: defaultSettings(),
  members: [
    { id: 'm0', name: 'You', email: 'you@example.com', role: 'Owner', owner: true },
    { id: 'm1', name: 'Mara Weber', email: 'mara@example.com', role: 'Editor' },
    { id: 'm2', name: 'Tom Becker', email: 'tom@example.com', role: 'Commenter' },
  ],
  flags: { link: false, linkComment: true, agentEdit: true, agentComment: true, agentGuest: false },
  commFilter: 'All',
  liked: {},
  remixed: [],

  // ---------- actions ----------

  set: (patch) => set(patch),

  go: (layer) => {
    const s = get();
    if (layer === 'home' && s.layer === 'home') return;
    const patch: Partial<AppState> = { layer, menu: null, tool: null, openPin: null, review: false };
    if (layer === 'what' || layer === 'how' || layer === 'check') patch.lastLayer = layer;
    if (layer === 'check') patch.drawer = true;
    set(patch);
  },

  toggleMenu: (m) => set((s) => ({ menu: s.menu === m ? null : m })),

  showToast: (text) => {
    set({ toast: text });
    later(() => { if (get().toast === text) set({ toast: null }); }, 2400);
  },

  runAgent: (steps, done) => {
    let i = 0;
    const tick = () => {
      if (i >= steps.length) { set({ agent: null }); done?.(); return; }
      set({ agent: { label: steps[i], step: i + 1, total: steps.length, pct: Math.round(((i + 1) / steps.length) * 100) } });
      i++;
      later(tick, 900);
    };
    tick();
  },

  userSays: (text, ctx) => set((s) => ({ msgs: [...s.msgs, { who: 'you', text, ctx: ctx ?? null }], chatOpen: true, typing: true })),
  say: (text) => set((s) => ({ typing: false, msgs: [...s.msgs, { who: 'bot', text }] })),

  sendChat: () => {
    const s = get();
    const text = s.chatText.trim();
    if (!text) return;
    const ctx = (s.layer === 'how' || s.layer === 'check') && s.selected ? s.selected : null;
    if (s.activeChat !== 'live') {
      const cid = s.activeChat;
      const push = (m: ChatMessage) => set((st) => ({ chats: st.chats.map((c) => (c.id === cid ? { ...c, msgs: [...c.msgs, m], when: 'Just now' } : c)) }));
      set({ chatText: '', typing: true });
      push({ who: 'you', text });
      later(() => { set({ typing: false }); push({ who: 'bot', text: 'Got it. I keep this in this thread. Switch to "Current session" to change the open design directly.' }); }, 800);
      return;
    }
    set({ chatText: '' });
    get().userSays(text, ctx);
    if (s.layer === 'home' || s.layer === 'team' || s.layer === 'settings') {
      later(() => get().say('I can\'t reach the engine right now, so I can\'t create the project yet. Start it with `pnpm dev:engine`; I connect by myself as soon as it is up, then send this again.'), 800);
      return;
    }
    if (s.layer === 'what') {
      if (s.iv) { get().answerIv(text, 'answer'); return; }
      const key = `${s.cat}:${s.q}`;
      const cat = s.cats.find((c) => c.id === s.cat);
      later(() => {
        get().addCard(key, 'text', text, 'agent');
        get().say(`Added to ${cat?.name ?? 'the spec'} · Q${s.q + 1} as a requirement. How strict is it: must-have or nice-to-have?`);
      }, 800);
      return;
    }
    const name = PROPS[s.version].name;
    later(() => {
      get().say(ctx ? 'On it. I am working on the part you selected.' : 'On it.');
      get().runAgent([`Reading your request${ctx ? ' and the selected part' : ''}`, `Updating ${name}`, 'Re-checking stress'], () => {
        const c = get().addCommit({ msg: `Change request: ${text.length > 42 ? `${text.slice(0, 40)}…` : text}`, who: 'Bot', diff: 'requested by you in chat' });
        get().say(`Done. I committed it as version ${c.id} on ${c.branch}. Open the history to compare it with the previous version.`);
      });
    }, 600);
  },

  addCard: (key, type, text = '', by = 'you') => {
    const labels: Record<CardType, string> = { image: 'New image – drop a file here', video: 'New video – drop a file here', model: 'New 3D model (.step, .stl)', sketch: 'New sketch', text: '' };
    const card: Card = { id: nextId++, type, text, label: labels[type], by, strokes: [], doodle: false };
    set((s) => ({ cards: { ...s.cards, [key]: [...(s.cards[key] ?? []), card] } }));
  },
  updateCard: (key, id, patch) => set((s) => ({ cards: { ...s.cards, [key]: (s.cards[key] ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c)) } })),
  removeCard: (key, id) => set((s) => ({ cards: { ...s.cards, [key]: (s.cards[key] ?? []).filter((c) => c.id !== id) } })),

  submitAnswer: (key, raw) => {
    const text = raw.trim();
    if (!text) return;
    if (ivCurrent(get()) === key) { get().answerIv(text, 'answer'); return; }
    get().addCard(key, 'text', text);
    set((s) => { const d = { ...s.ansDraft }; delete d[key]; return { ansDraft: d }; });
  },

  addQuestion: (catId, raw) => {
    let text = raw.trim();
    if (!text) { set({ newQCat: null }); return; }
    if (!text.endsWith('?')) text += '?';
    let idx = 0;
    set((s) => {
      const meta = { ...s.qMeta };
      const cats = s.cats.map((c) => {
        if (c.id !== catId) return c;
        idx = c.qs.length;
        meta[`${c.id}:${idx}`] = 'you';
        return { ...c, qs: [...c.qs, text], orig: [...c.orig, null] };
      });
      return { cats, qMeta: meta, newQCat: null };
    });
    later(() => document.getElementById(`ans-${catId}-${idx}`)?.focus(), 120);
  },

  deleteQuestion: (catId, i) => set((s) => {
    const cats = s.cats.map((c) => (c.id !== catId ? c : { ...c, qs: c.qs.filter((_, j) => j !== i), orig: c.orig.filter((_, j) => j !== i) }));
    // shift the keys of later questions down by one
    function mv<T>(src: Record<string, T>): Record<string, T> {
      const dst: Record<string, T> = {};
      for (const k of Object.keys(src)) {
        const a = k.split(':'), j = Number(a[1]), sfx = a[2] ? `:${a[2]}` : '';
        if (a[0] !== catId || j < i) dst[k] = src[k];
        else if (j > i) dst[`${catId}:${j - 1}${sfx}`] = src[k];
      }
      return dst;
    }
    return { cats, cards: mv(s.cards), qMeta: mv(s.qMeta), fups: mv(s.fups), q: 0 };
  }),

  addCategory: (name) => {
    const n = name.trim();
    if (!n) { set({ addingCat: false }); return; }
    const id = n.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `c${nextId++}`;
    set((s) => ({
      cats: [...s.cats, { id, name: n, qs: ['What should this criterion capture?', 'How will you judge whether it is met?', 'Any hard limits?'], orig: [null, null, null] }],
      addingCat: false, cat: id, q: 0, whatView: 'cat', expanded: { ...s.expanded, [id]: true },
    }));
    scrollToId(`sec-${id}`);
  },

  startInterview: () => {
    const s = get();
    let open = openKeys(s);
    if (!open.length) open = allQKeys(s);
    // round 1: one open question per section, then the rest
    const first: string[] = [];
    for (const c of s.cats) {
      const k = open.find((x) => x.split(':').length === 2 && x.startsWith(`${c.id}:`));
      if (k) first.push(k);
    }
    const keys = [...first, ...open.filter((k) => !first.includes(k))];
    set({ agentBarHidden: false, iv: { keys, i: 0, answered: 0, r1: first.length, fq: 0 }, ahead: Math.max(s.ahead, 8), layer: 'what', lastLayer: 'what' });
    later(askIv, 300);
    tickAhead();
  },

  answerIv: (text, mode) => {
    const s = get();
    const k = ivCurrent(s);
    if (!k || !s.iv) return;
    const info = infoOf(s, k);
    if (mode !== 'skip') {
      const card: Card = mode === 'assume'
        ? { id: nextId++, type: 'text', text: `Assumption: ${info?.assume ?? 'Bot decides.'}`, label: '', by: 'agent' }
        : { id: nextId++, type: 'text', text, label: '', by: 'you' };
      set((st) => { const d = { ...st.ansDraft }; delete d[k]; return { cards: { ...st.cards, [k]: [...(st.cards[k] ?? []), card] }, ansDraft: d }; });
    }
    // a real answer to a main question can trigger one follow-up from Bot
    const parts = k.split(':');
    const cat0 = s.cats.find((c) => c.id === parts[0]);
    let fu: FollowUp | null = null;
    if (mode === 'answer' && parts.length === 2 && cat0 && !(s.fups[k] ?? []).length) {
      const o = cat0.orig[Number(parts[1])];
      if (typeof o === 'number') fu = (cat0.src === 'gen' ? FOLLOWUPS_GEN : FOLLOWUPS)[`${parts[0]}:${o}`] ?? null;
    }
    set((st) => {
      if (!st.iv) return {};
      const keys = st.iv.keys.slice();
      let fq = st.iv.fq;
      const patch: Partial<AppState> = {};
      if (fu) {
        patch.fups = { ...st.fups, [k]: [fu] };
        const at = st.iv.i < st.iv.r1 ? st.iv.r1 + fq : st.iv.i + 1;
        keys.splice(at, 0, `${k}:f0`);
        if (st.iv.i < st.iv.r1) fq++;
      }
      const iv = { ...st.iv, fq, keys, i: st.iv.i + 1, answered: st.iv.answered + (mode === 'skip' ? 0 : 1) };
      patch.iv = iv;
      patch.ahead = Math.max(st.ahead, Math.min(99, Math.round(10 + (90 * iv.i) / iv.keys.length)));
      return patch;
    });
    if (fu && cat0) get().say(`Follow-up noted under ${cat0.name} · Q${Number(parts[1]) + 1}. I come back to it after one question per section.`);
    later(() => { if (ivCurrent(get())) askIv(); else nextRound(); }, 250);
  },

  buildNow: () => {
    const s = get();
    const add: Record<string, Card[]> = {};
    let n = 0;
    for (const k of allQKeys(s)) {
      if ((s.cards[k] ?? []).length) continue;
      add[k] = [{ id: nextId++, type: 'text', text: `Assumption: ${infoOf(s, k)?.assume ?? 'Bot decides.'}`, label: '', by: 'agent' }];
      n++;
    }
    set((st) => ({ cards: { ...st.cards, ...add }, iv: null, ahead: Math.max(st.ahead, 12) }));
    get().userSays('Skip the rest, build now');
    later(() => {
      get().say(n ? `Okay, I stopped the interview. ${n} open question${n > 1 ? 's became assumptions' : ' became an assumption'}, marked as mine on the sheet. Change them any time and I update the prototypes.` : 'Okay, building now.');
      get().generate();
    }, 500);
  },

  generate: () => {
    const a = get().ahead;
    const open = () => { set({ layer: 'how', lastLayer: 'how', review: true, selected: null, tool: null, openPin: null, menu: null, iv: null }); get().checkout('9b11'); };
    if (a >= 100) {
      get().userSays('Open the prototypes');
      open();
      later(() => get().say('Here they are. I built them while we were talking, so there was nothing left to wait for.'), 400);
      return;
    }
    get().userSays('Generate 3 prototypes');
    set({ iv: null });
    const left = a > 0
      ? AHEAD_STAGES.filter(([at]) => at > a && at < 100).map(([, l]) => l)
      : ['Reading requirements', 'Sketching 3 concepts', 'Sizing parts and connections', 'Running static and vibration check', 'Ranking proposals'];
    later(() => {
      get().say(a > 0
        ? `I am ${a}% there already. Finishing the last steps with what we have; open points become assumptions you can change later.`
        : 'Working on it. I am reading all five criteria and will come back with three concepts.');
      get().runAgent(left.length ? left : ['Finishing'], () => {
        set({ ahead: 100 });
        open();
        get().say('Three concepts are ready, each on its own branch. I merged Concept B into main as my recommendation. Browse the history to compare versions.');
      });
    }, 400);
  },

  select: (id) => set((s) => ({ selected: s.selected === id ? null : id })),
  setCamera: (view) => set((s) => ({ camera: { view, nonce: s.camera.nonce + 1 }, menu: null })),

  checkout: (id) => {
    const c = get().commits.find((x) => x.id === id);
    if (c) set({ head: id, selCommit: id, version: c.ver, selected: null });
  },

  addCommit: (opts) => {
    const s = get();
    const h = headCommit(s) ?? s.commits[s.commits.length - 1];
    const branch = opts.branch ?? h.branch;
    let colors = s.branchColors;
    if (!colors[branch]) colors = { ...colors, [branch]: EXTRA_COLORS[(Object.keys(colors).length - 3) % EXTRA_COLORS.length] };
    const c: Commit = { id: newHash(), branch, parents: [opts.from ?? h.id], ver: opts.ver ?? h.ver, msg: opts.msg, who: opts.who ?? 'Bot', t: hhmm(), diff: opts.diff ?? '' };
    set({ commits: [...s.commits, c], branchColors: colors, head: c.id, selCommit: c.id, version: c.ver, selected: null });
    return c;
  },

  runStudy: (id) => {
    const st = STUDIES.find((x) => x.id === id);
    if (!st || get().studyRun) return;
    const steps: Record<string, string[]> = {
      static: ['Meshing parts', 'Applying loads', 'Solving linear static'],
      modal: ['Meshing parts', 'Assembling mass + stiffness', 'Solving eigenmodes'],
      motion: ['Building MuJoCo model', 'Simulating 10 s', 'Extracting joint loads'],
      thermal: ['Meshing parts', 'Applying heat source', 'Solving heat flow'],
      vibration: ['Reusing the modal model', 'Sweeping 0–80 Hz', 'Extracting response peaks'],
      cfd: ['Building the water volume', 'Meshing 1.8 M cells', 'Solving the flow', 'Integrating forces'],
      soft: ['Adding flexible pads', 'Simulating 10 s with water damping', 'Extracting contact pressure'],
    };
    set({ study: id, studyRun: id, layer: 'check', lastLayer: 'check', drawer: true });
    get().runAgent(steps[id], () => {
      set((s) => ({ studyDone: { ...s.studyDone, [`${id}:${s.version}`]: true }, studyRun: null, playing: true }));
      get().showToast(`${st.title} finished (mock results)`);
    });
  },

  addPin: (part, p) => {
    const id = Math.max(0, ...get().pins.map((x) => x.id)) + 1;
    set((s) => ({ pins: [...s.pins, { id, part, p, msgs: [] }], openPin: id, tool: null }));
  },

  sendPinComment: (id, raw, queue) => {
    const text = raw.trim();
    if (!text) return;
    set((s) => ({ pins: s.pins.map((p) => (p.id === id ? { ...p, msgs: [...p.msgs, { who: 'You', text }] } : p)) }));
    if (!queue) return;
    get().runAgent(['Reading comment', 'Updating the design', 'Re-checking stress'], () => {
      const c = get().addCommit({ msg: `Comment ${id}: ${text.length > 36 ? `${text.slice(0, 34)}…` : text}`, diff: `from 3D comment ${id}` });
      set((s) => ({ pins: s.pins.map((p) => (p.id === id ? { ...p, msgs: [...p.msgs, { who: 'Bot', text: `Done. Committed as ${c.id} on ${c.branch}.` }] } : p)) }));
    });
  },
}));

// ---------- interview flow (module-private) ----------

export function askIv() {
  const s = useApp.getState();
  const iv = s.iv;
  if (!iv) return;
  let i = iv.i;
  while (i < iv.keys.length && (s.cards[iv.keys[i]] ?? []).length) i++;
  if (i >= iv.keys.length) { nextRound(); return; }
  if (i !== iv.i) useApp.setState({ iv: { ...iv, i } });
  const k = iv.keys[i];
  const parts = k.split(':');
  const qi = Number(parts[1]);
  useApp.setState((st) => ({ cat: parts[0], q: qi, expanded: { ...st.expanded, [parts[0]]: true }, whatView: 'cat' }));
  later(() => {
    const sfx = parts[2] ? `-${parts[2]}` : '';
    document.getElementById(`q-${parts[0]}-${qi}${sfx}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    (document.getElementById(`ans-${parts[0]}-${qi}${sfx}`) as HTMLInputElement | null)?.focus({ preventScroll: true });
  }, 120);
}

/** After every section had its turn, Bot adds one extra question per topic once, then finishes. */
function nextRound() {
  const s = useApp.getState();
  const more = s.cats.filter((c) => (c.src === 'gen' ? MORE_QS_GEN : MORE_QS)[c.id] && !c.orig.includes(-1));
  if (more.length && !s.cats.some((c) => c.orig.includes(-1))) {
    const keys: string[] = [];
    const meta = { ...s.qMeta };
    const cats = s.cats.map((c) => {
      const extra = (c.src === 'gen' ? MORE_QS_GEN : MORE_QS)[c.id];
      if (!extra) return c;
      const k = `${c.id}:${c.qs.length}`;
      keys.push(k);
      meta[k] = 'more';
      return { ...c, qs: [...c.qs, extra.text], orig: [...c.orig, -1] };
    });
    useApp.setState({ cats, qMeta: meta, iv: { keys, i: 0, answered: s.iv?.answered ?? 0, r1: keys.length, fq: 0 } });
    useApp.getState().say(`Every section had its turn. ${keys.length} more questions from me, then the spec is complete.`);
    later(askIv, 300);
    return;
  }
  useApp.setState({ iv: null, ahead: 100 });
  useApp.getState().say('That was the last question. The prototypes are ready; open them from the bar on top.');
}

function tickAhead() {
  if (aheadTimer) return;
  const step = () => {
    aheadTimer = null;
    const s = useApp.getState();
    if (!s.iv) return;
    const cap = Math.round(10 + (90 * (s.iv.i + 1)) / s.iv.keys.length) - 4;
    if (s.ahead < cap) useApp.setState({ ahead: s.ahead + 1 });
    aheadTimer = setTimeout(step, 1400);
  };
  aheadTimer = setTimeout(step, 1400);
}
