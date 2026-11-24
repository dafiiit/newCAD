// Connects the app store to a running engine.
//
// On start the app probes /api/health. Without an engine nothing changes and the
// prototype keeps its mock data. With one, this module loads the chosen project
// (spec, versions, notes, chat, model), keeps it fresh from the event socket, and
// replaces the mock store actions with ones that call the engine.
import { BRANCH_COLORS, EXTRA_COLORS } from '../data/seed';
import type { Card, ChatMessage, Commit, FollowUp, Pin, QuestionInfo } from '../data/types';
import { ivCurrent, openKeys, useApp, type AppActions, type AppState } from '../state/store';
import { api, apiBlob, connectEvents, EngineError, probe, type EngineEvent } from './client';
import { emptySim, loadStudies, onSimEvent, scheduleStudies } from './sim';
import type {
  BotGroup, BotStatus, EngineMate, BotTask, EngineChatMessage, EngineLog, EngineNote, EngineState, Manifest, ProjectSummary, Spec,
} from './types';

type Get = () => AppState & AppActions;
const get: Get = () => useApp.getState();
const set = (patch: Partial<AppState> | ((s: AppState) => Partial<AppState>)) => useApp.setState(patch as Partial<AppState>);

const eng = () => get().eng;
const pid = () => get().eng?.pid ?? null;
const P = (path = '') => `/api/projects/${encodeURIComponent(pid() ?? '')}${path}`;

function patchEng(patch: Partial<EngineState>) {
  const e = eng();
  if (e) set({ eng: { ...e, ...patch } });
}

function problem(e: unknown): string {
  if (e instanceof EngineError) return e.message;
  return e instanceof Error ? e.message : String(e);
}

function fail(e: unknown, prefix = '') {
  const msg = `${prefix}${problem(e)}`;
  set({ typing: false });
  get().showToast(msg.length > 140 ? `${msg.slice(0, 138)}…` : msg);
  return msg;
}

/** Bot can't run (no API key, no model): say so in the chat with a pointer to Settings. */
function botProblem(e: unknown) {
  const msg = problem(e);
  set({ typing: false, agent: null });
  get().say(`I can't run yet: ${msg}. You can pick the model and add a key under Settings → BuilderBot model.`);
}

// ---------- coordinates ----------
// The engine works in Z-up millimetres; the viewer (and GLB) is Y-up.
export const toView = (p: [number, number, number]): [number, number, number] => [p[0], p[2], -p[1]];
export const toEngine = (p: [number, number, number]): [number, number, number] => [p[0], -p[2], p[1]];

// ---------- spec ↔ sheet ----------

const cardIds = new Map<string, number>();
let nextCard = 1_000_000;
function cardId(qid: string, idx: number) {
  const k = `${qid}#${idx}`;
  let id = cardIds.get(k);
  if (id === undefined) { id = nextCard++; cardIds.set(k, id); }
  return id;
}

function mapSpec(spec: Spec) {
  const cats: AppState['cats'] = [];
  const cards: Record<string, Card[]> = {};
  const qMeta: AppState['qMeta'] = {};
  const fups: Record<string, FollowUp[]> = {};
  const qInfo: Record<string, QuestionInfo | FollowUp> = {};
  const keyOf: Record<string, string> = {};
  const qidOf: Record<string, string> = {};
  const cardAns: EngineState['cardAns'] = {};
  // keep local (non-text) cards such as sketches and images, which the engine doesn't store yet
  const keep = get().cards;

  const toCards = (key: string, qid: string, answers: Spec['categories'][number]['questions'][number]['answers']) => {
    const out: Card[] = (answers ?? []).map((a, idx) => {
      const id = cardId(qid, idx);
      cardAns[id] = { qid, idx };
      const text = a.assumption && !/^assumption:/i.test(a.text) ? `Assumption: ${a.text}` : a.text;
      return { id, type: 'text', text, label: '', by: a.by === 'you' && !a.assumption ? 'you' : 'agent' };
    });
    const local = (keep[key] ?? []).filter((c) => c.type !== 'text');
    cards[key] = [...out, ...local];
  };

  for (const c of spec.categories ?? []) {
    const ids = new Set(c.questions.map((q) => q.id));
    const mains = c.questions.filter((q) => !q.parent || !ids.has(q.parent));
    cats.push({ id: c.id, name: c.name, qs: mains.map((q) => q.text), orig: mains.map(() => null) });
    mains.forEach((q, i) => {
      const key = `${c.id}:${i}`;
      keyOf[q.id] = key; qidOf[key] = q.id;
      qInfo[key] = { ex: q.examples ?? [], assume: q.assume ?? '' };
      if (q.by === 'you') qMeta[key] = 'you';
      else if (q.by === 'bot' || q.by === 'agent') qMeta[key] = 'more';
      toCards(key, q.id, q.answers);
      const kids = c.questions.filter((x) => x.parent === q.id);
      if (kids.length) fups[key] = kids.map((k) => ({ text: k.text, ex: k.examples ?? [], assume: k.assume ?? '' }));
      kids.forEach((k, j) => {
        const fk = `${key}:f${j}`;
        keyOf[k.id] = fk; qidOf[fk] = k.id;
        qInfo[fk] = { ex: k.examples ?? [], assume: k.assume ?? '' };
        toCards(fk, k.id, k.answers);
      });
    });
  }
  return { cats, cards, qMeta, fups, qInfo, keyOf, qidOf, cardAns };
}

let lastOverview: string | null = null;

async function loadSpec() {
  const spec = await api<Spec>(P('/spec'));
  const m = mapSpec(spec);
  const s = get();
  const overview = spec.overview ?? spec.goal ?? '';
  const patch: Partial<AppState> = { cats: m.cats, cards: m.cards, qMeta: m.qMeta, fups: m.fups, qInfo: m.qInfo };
  // don't overwrite the overview while the person is typing in it
  if (lastOverview === null || s.overview === lastOverview) { patch.overview = overview; lastOverview = overview; }
  if (!m.cats.some((c) => c.id === s.cat)) { patch.cat = m.cats[0]?.id ?? ''; patch.q = 0; }
  set(patch);
  patchEng({ keyOf: m.keyOf, qidOf: m.qidOf, cardAns: m.cardAns });
}

// ---------- versions ----------

const hhmm = (t: number) => {
  const d = new Date(t * 1000);
  const today = new Date().toDateString() === d.toDateString();
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return today ? hm : `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${hm}`;
};

function mapLog(log: EngineLog) {
  const short = (id: string) => id.slice(0, 7);
  const commits: Commit[] = log.commits.map((c) => ({
    id: c.short || short(c.id), branch: c.branch, parents: c.parents.map(short), ver: 2,
    msg: c.message.split('\n')[0], who: c.author, t: hhmm(c.time), diff: c.files.length ? `Changed ${c.files.join(', ')}` : '',
  }));
  const colors: Record<string, string> = { ...BRANCH_COLORS };
  let extra = 0;
  for (const b of log.branches) if (!colors[b]) colors[b] = b === 'concept-a' ? '#0F766E' : EXTRA_COLORS[extra++ % EXTRA_COLORS.length];
  return { commits, head: short(log.headCommit), branchColors: colors };
}

async function loadLog() {
  const log = await api<EngineLog>(P('/log'));
  const m = mapLog(log);
  const s = get();
  const sel = m.commits.some((c) => c.id === s.selCommit) ? s.selCommit : m.head;
  set({ commits: m.commits, head: m.head, selCommit: sel, branchColors: m.branchColors });
  patchEng({ log });
  return log;
}

/** The ref to check out for a commit shown in the history: its branch if it is that branch's tip. */
export function refFor(shortId: string): string {
  const log = eng()?.log;
  if (!log) return shortId;
  const full = log.commits.find((c) => c.short === shortId || c.id.startsWith(shortId))?.id ?? shortId;
  const tips = Object.entries(log.tips).filter(([, id]) => id === full).map(([b]) => b);
  const own = log.commits.find((c) => c.id === full)?.branch;
  if (log.headBranch && tips.includes(log.headBranch)) return log.headBranch;
  if (own && tips.includes(own)) return own;
  return tips[0] ?? full;
}

export function fullId(shortId: string): string {
  return eng()?.log?.commits.find((c) => c.short === shortId || c.id.startsWith(shortId))?.id ?? shortId;
}

// ---------- model ----------

let buildSeq = 0;
async function loadModel() {
  const seq = ++buildSeq;
  patchEng({ building: true });
  try {
    const [man, files, asm] = await Promise.all([
      api<Manifest>(P('/build'), { method: 'POST', body: {} }),
      api<{ files: Record<string, string> }>(P('/files')),
      api<{ mates: EngineMate[] }>(P('/assembly')),
    ]);
    if (seq !== buildSeq) return;
    const s = get();
    const ids = new Set(man.parts.map((p) => p.id));
    patchEng({ manifest: man, files: files.files, mates: asm.mates ?? [], building: false });
    if (s.selected && !ids.has(s.selected) && !s.selected.startsWith('lib-')) set({ selected: null });
  } catch (e) {
    if (seq === buildSeq) patchEng({ building: false });
    fail(e, 'Build failed: ');
  }
}

// ---------- notes ----------

async function loadNotes() {
  const n = await api<{ notes: EngineNote[] }>(P('/notes'));
  const drafts = get().pins.filter((p) => p.draft);
  const pins: Pin[] = n.notes.map((x) => ({
    id: x.id, part: x.part, p: x.point ? toView(x.point) : [0, 0, 0], resolved: x.status === 'resolved',
    queued: x.status === 'queued', msgs: x.msgs, face: x.face_now ?? x.face,
  }));
  set({ pins: [...pins, ...drafts] });
}

// ---------- chat and Bot ----------

const mapMsg = (m: EngineChatMessage): ChatMessage => {
  const interview = m.source === 'interview' || m.question !== undefined;
  return {
    who: m.who === 'you' ? 'you' : 'bot', text: m.text, ctx: m.ctx ?? null, actions: m.actions, branch: m.branch, t: m.t,
    task: m.task, trace: m.trace, status: m.status,
    thread: m.thread ?? m.task ?? (m.group ? `g:${m.group}` : interview ? 'interview' : undefined),
    source: m.source ?? (m.group ? 'generate' : interview ? 'interview' : undefined),
  };
};

async function loadChat() {
  const log = await api<EngineChatMessage[]>(P('/bot/chat'));
  const msgs = log.filter((m) => m.who !== 'system').map(mapMsg);
  set({ msgs: msgs.length ? msgs : [{ who: 'bot', text: 'Hi, I am Bot. Answer the questions on the What? sheet, or tell me what to change. I build every change on its own branch, so nothing lands in your version until you apply it.' }] });
}

export async function loadBotStatus() {
  const bot = await api<BotStatus>(`/api/bot/status${pid() ? `?project=${encodeURIComponent(pid()!)}` : ''}`);
  patchEng({ bot });
  return bot;
}

function updateAgent() {
  const e = eng();
  if (!e) return;
  const running = Object.values(e.tasks).filter((t) => t.status === 'running' && t.project === e.pid && t.mode !== 'interview');
  if (!running.length) { set({ agent: null }); return; }
  const grouped = running.filter((t) => t.group);
  if (grouped.length) {
    const gid = grouped[0].group;
    const all = Object.values(e.tasks).filter((t) => t.group === gid);
    const done = all.filter((t) => t.status !== 'running').length;
    const steps = all.reduce((n, t) => n + t.step, 0);
    const lead = grouped.reduce((a, b) => (b.step > a.step ? b : a));
    set({ agent: { label: `${all.length} concepts · ${lead.concept ? `${lead.concept}: ` : ''}${lead.label}`, step: done, total: all.length, pct: Math.min(96, Math.round(100 * (1 - Math.exp(-steps / (6 * all.length))))) } });
    return;
  }
  const t = running[running.length - 1];
  set({ agent: { label: t.label, step: t.step, total: t.max_steps, pct: Math.min(96, Math.round(100 * (1 - Math.exp(-t.step / 6)))) } });
}

let pendingGroup: string | null = null;

// ---------- loading a project ----------

let reloadTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleReload(what: { spec?: boolean; log?: boolean; model?: boolean; notes?: boolean } = { spec: true, log: true, model: true, notes: true }) {
  pendingReload = { ...pendingReload, ...what };
  if (reloadTimer) clearTimeout(reloadTimer);
  reloadTimer = setTimeout(() => {
    reloadTimer = null;
    const w = pendingReload;
    pendingReload = {};
    void Promise.all([
      w.spec ? loadSpec() : null,
      w.log ? loadLog() : null,
      w.model ? loadModel() : null,
      w.notes ? loadNotes() : null,
    ]).catch((e) => fail(e));
  }, 250);
}
let pendingReload: { spec?: boolean; log?: boolean; model?: boolean; notes?: boolean } = {};

export async function openProject(id: string) {
  const projects = await api<ProjectSummary[]>('/api/projects');
  const p = projects.find((x) => x.id === id);
  if (!p) throw new Error(`No project ${id}`);
  lastOverview = null;
  cardIds.clear();
  set({
    projectName: p.name, eng: { ...eng()!, pid: id, projects, manifest: null, log: null, files: {}, tasks: {}, keyOf: {}, qidOf: {}, cardAns: {}, compare: {}, mates: [], sim: emptySim() },
    simSel: null, simPick: null, simProbe: null, simRange: null,
    iv: null, ahead: 0, agent: null, selected: null, pins: [], openPin: null, libParts: [], whatView: 'overview', typing: false,
    folders: [], floc: {}, cards: {}, ovFacts: [], ansDraft: {}, qMeta: {}, fups: {},
  });
  try { localStorage.setItem('newcad.project', id); } catch { /* private mode */ }
  await Promise.all([loadSpec(), loadLog(), loadNotes(), loadChat(), loadBotStatus()]);
  void loadModel();
  void loadStudies().catch(() => undefined);
}

export async function refreshProjects() {
  const projects = await api<ProjectSummary[]>('/api/projects');
  patchEng({ projects });
  return projects;
}

export async function createProject(name: string, goal: string) {
  const p = await api<ProjectSummary>('/api/projects', { body: { name, goal, template: 'blank' } });
  await openProject(p.id);
  return p;
}

// ---------- interview ----------

function focusKey(key: string) {
  const parts = key.split(':');
  const qi = Number(parts[1]);
  set((st) => ({ cat: parts[0], q: qi, expanded: { ...st.expanded, [parts[0]]: true }, whatView: 'cat' }));
  setTimeout(() => {
    const sfx = parts[2] ? `-${parts[2]}` : '';
    document.getElementById(`q-${parts[0]}-${qi}${sfx}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    (document.getElementById(`ans-${parts[0]}-${qi}${sfx}`) as HTMLInputElement | null)?.focus({ preventScroll: true });
  }, 140);
}

let ivBusy = false;
async function interviewStep(answered?: string) {
  if (ivBusy) return;
  ivBusy = true;
  set({ typing: true });
  try {
    const r = await api<{ question_id: string | null; message: string; done: boolean; open: number }>(P('/bot/interview'), { body: { answered: answered ?? null } });
    await loadSpec();
    set({ typing: false });
    if (!get().iv) return; // paused meanwhile
    const key = r.question_id ? eng()?.keyOf[r.question_id] : undefined;
    if (r.done || !key) {
      set({ iv: null });
      return;
    }
    set((st) => ({ iv: st.iv ? { ...st.iv, keys: [key], i: 0 } : null }));
    focusKey(key);
  } catch (e) {
    set({ iv: null });
    botProblem(e);
  } finally {
    ivBusy = false;
  }
}

async function postAnswer(key: string, text: string, assumption = false) {
  const qid = eng()?.qidOf[key];
  if (!qid) throw new Error('This question is not in the project spec');
  await api(P('/spec/answer'), { body: { question_id: qid, text, assumption } });
}

// ---------- actions that replace the mock ones ----------

function optimisticCard(key: string, text: string, by: Card['by']) {
  const card: Card = { id: nextCard++, type: 'text', text, label: '', by };
  set((s) => {
    const d = { ...s.ansDraft };
    delete d[key];
    return { cards: { ...s.cards, [key]: [...(s.cards[key] ?? []), card] }, ansDraft: d };
  });
}

const editTimers = new Map<number, ReturnType<typeof setTimeout>>();

function engineActions(mock: AppActions): Partial<AppActions> {
  return {
    submitAnswer: (key, raw) => {
      const text = raw.trim();
      if (!text) return;
      if (ivCurrent(get()) === key) { get().answerIv(text, 'answer'); return; }
      optimisticCard(key, text, 'you');
      postAnswer(key, text).then(() => loadSpec()).catch((e) => { fail(e); void loadSpec(); });
    },

    addCard: (key, type, text = '', by = 'you') => {
      if (type === 'text' && text.trim()) { optimisticCard(key, text, by); postAnswer(key, text, by !== 'you').then(() => loadSpec()).catch((e) => fail(e)); return; }
      mock.addCard(key, type, text, by);
    },

    updateCard: (key, id, patch) => {
      mock.updateCard(key, id, patch);
      const ref = eng()?.cardAns[id];
      if (!ref || patch.text === undefined) return;
      const text = patch.text.trim();
      clearTimeout(editTimers.get(id));
      if (!text) return; // emptying an answer removes it on blur via removeCard
      editTimers.set(id, setTimeout(() => {
        editTimers.delete(id);
        api(P('/spec/answer'), { body: { question_id: ref.qid, text: text.replace(/^assumption:\s*/i, ''), index: ref.idx } }).catch((e) => fail(e));
      }, 700));
    },

    removeCard: (key, id) => {
      const ref = eng()?.cardAns[id];
      mock.removeCard(key, id);
      if (!ref) return;
      clearTimeout(editTimers.get(id));
      api(P('/spec/answer/remove'), { body: { question_id: ref.qid, index: ref.idx } }).then(() => loadSpec()).catch((e) => fail(e));
    },

    addQuestion: (catId, raw) => {
      const text = raw.trim();
      set({ newQCat: null });
      if (!text) return;
      api(P('/spec/question'), { body: { category: catId, text } }).then(() => loadSpec()).then(() => {
        const c = get().cats.find((x) => x.id === catId);
        if (c) setTimeout(() => document.getElementById(`ans-${catId}-${c.qs.length - 1}`)?.focus(), 120);
      }).catch((e) => fail(e));
    },

    deleteQuestion: (catId, i) => {
      const qid = eng()?.qidOf[`${catId}:${i}`];
      if (!qid) { mock.deleteQuestion(catId, i); return; }
      api(P(`/spec/question/${encodeURIComponent(qid)}`), { method: 'DELETE' }).then(() => loadSpec()).catch((e) => fail(e));
    },

    startInterview: () => {
      set({ agentBarHidden: false, iv: { keys: [], i: 0, answered: 0, r1: 0, fq: 0 }, layer: 'what', lastLayer: 'what' });
      void interviewStep();
    },

    answerIv: (text, mode) => {
      const s = get();
      const key = ivCurrent(s);
      if (!key || !s.iv) return;
      const assume = s.qInfo[key]?.assume || 'Bot decides.';
      const body = mode === 'answer' ? text.trim() : assume;
      if (!body) return;
      optimisticCard(key, mode === 'answer' ? body : `Assumption: ${body}`, mode === 'answer' ? 'you' : 'agent');
      set((st) => ({ iv: st.iv ? { ...st.iv, answered: st.iv.answered + 1 } : null }));
      postAnswer(key, body, mode !== 'answer')
        .then(() => interviewStep(eng()?.qidOf[key]))
        .catch((e) => { fail(e); void loadSpec(); });
    },

    buildNow: () => {
      const s = get();
      const open = openKeys(s);
      set({ iv: null });
      get().userSays('Skip the rest, build now');
      const fill = async () => {
        for (const k of open) {
          const assume = s.qInfo[k]?.assume;
          if (assume) await postAnswer(k, assume, true);
        }
      };
      fill().then(() => loadSpec()).then(() => {
        get().say(open.length ? `Okay. ${open.length} open question${open.length > 1 ? 's became assumptions' : ' became an assumption'}, marked as mine on the sheet. Change them any time.` : 'Okay, building now.');
        get().generate();
      }).catch((e) => fail(e));
    },

    generate: () => {
      set({ iv: null, typing: true, chatOpen: get().layer !== 'what' });
      api<BotGroup>(P('/bot/generate'), { body: { count: 3 } }).then((g) => {
        pendingGroup = g.id;
        set({ typing: false });
        for (const t of g.tasks) onTask(t);
      }).catch(botProblem);
    },

    sendChat: () => {
      const s = get();
      const text = s.chatText.trim();
      if (!text) return;
      // in a thread view, a message continues that conversation (and builds on its branch)
      const thread = !['live', 'new', 'interview'].includes(s.activeChat) && !s.activeChat.startsWith('g:') ? s.activeChat : null;
      if (s.layer === 'home' || s.layer === 'team' || s.layer === 'settings') {
        set({ chatText: '' });
        const goal = text.replace(/^new project:\s*/i, '').trim();
        if (!goal) return;
        const name = nameFromGoal(goal);
        get().userSays(text);
        createProject(name, goal).then(() => {
          get().go('what');
          get().say(`I created ${name}. I'll ask a few questions for the What? sheet; you can answer or say "build now" any time.`);
          get().startInterview();
        }).catch((e) => fail(e));
        return;
      }
      if (s.layer === 'what') {
        set({ chatText: '' });
        if (s.iv) { get().answerIv(text, 'answer'); return; }
        if (/^(build now|generate|build it)\b/i.test(text)) { get().buildNow(); return; }
        const key = `${s.cat}:${s.q}`;
        const cat = s.cats.find((c) => c.id === s.cat);
        get().userSays(text);
        optimisticCard(key, text, 'you');
        postAnswer(key, text).then(() => { void loadSpec(); get().say(`Added to ${cat?.name ?? 'the spec'} · Q${s.q + 1}.`); }).catch((e) => fail(e));
        return;
      }
      const sel = (s.layer === 'how' || s.layer === 'check') && s.selected && !s.selected.startsWith('lib-') ? s.selected : null;
      set({ chatText: '', typing: true, chatOpen: true });
      api<BotTask>(P('/bot/chat'), { body: { message: text, selected: sel, thread } }).then(onTask).catch(botProblem);
    },

    checkout: (id) => {
      const ref = refFor(id);
      api<{ head: string }>(P('/checkout'), { body: { ref } })
        .then(() => Promise.all([loadLog(), loadSpec(), loadNotes()]))
        .then(() => { set({ selected: null }); return loadModel(); })
        .catch((e) => fail(e));
    },

    addCommit: (opts) => {
      // the engine makes commits; this only keeps old callers from crashing
      const h = get().commits.find((c) => c.id === get().head) ?? get().commits[get().commits.length - 1];
      return h ?? { id: '', branch: opts.branch ?? 'main', parents: [], ver: 2, msg: opts.msg, who: 'You', t: '', diff: '' };
    },

    addPin: (part, p, extra) => {
      const id = -Date.now();
      set((s) => ({ pins: [...s.pins, { id, part, p, msgs: [], draft: true, face: extra?.face ?? null, key: extra?.key ?? null }], openPin: id, tool: null }));
    },

    sendPinComment: (id, raw, queue) => {
      const text = raw.trim();
      if (!text) return;
      const pin = get().pins.find((x) => x.id === id);
      if (!pin) return;
      set((s) => ({ pins: s.pins.map((x) => (x.id === id ? { ...x, msgs: [...x.msgs, { who: 'You', text }], queued: queue || x.queued } : x)) }));
      const req = pin.draft
        ? api<EngineNote>(P('/notes'), { body: { part: pin.part, text, point: toEngine(pin.p), face: pin.face ?? null, key: pin.key ?? null, queue } })
        : api<EngineNote>(P(`/notes/${id}/reply`), { body: { text, queue } });
      req.then((n) => {
        set((s) => ({ pins: s.pins.filter((x) => x.id !== id), openPin: s.openPin === id ? n.id : s.openPin }));
        return loadNotes();
      }).catch((e) => fail(e));
    },
  };
}

function nameFromGoal(goal: string): string {
  let first = goal.split(/[.!?\n]/)[0].trim();
  first = first.replace(/^(i need|i want|we need|make|build|design|create)\s+(me\s+|us\s+)?/i, '').replace(/^(an?|the)\s+/i, '');
  // "wall bracket that holds a shelf" -> "wall bracket"
  const cut = first.split(/\s+(?:that|which|to|for|with|so)\s+/i)[0];
  const words = (cut.split(/\s+/).length >= 2 ? cut : first).split(/\s+/).slice(0, 5).join(' ');
  const name = words.length > 40 ? `${words.slice(0, 38)}…` : words;
  return name ? name[0].toUpperCase() + name.slice(1) : 'New project';
}

// ---------- events ----------

function onTask(t: BotTask) {
  const e = eng();
  if (!e) return;
  const prev = e.tasks[t.id];
  // the HTTP reply that started a task can arrive after its later socket events
  if (prev && (prev.status !== 'running' || prev.step > t.step) && t.status === 'running') return;
  patchEng({ tasks: { ...e.tasks, [t.id]: t } });
  if (t.project === e.pid && t.status !== 'running' && t.mode !== 'interview') set({ typing: false });
  updateAgent();
}

function onEvent(ev: EngineEvent) {
  const e = eng();
  if (!e) return;
  if (ev.type === 'project.changed') {
    if (ev.project !== e.pid) { void refreshProjects().catch(() => undefined); return; }
    scheduleReload();
    scheduleStudies();
    return;
  }
  if (onSimEvent(ev)) return;
  if (ev.type === 'bot.task') { onTask(ev.task as BotTask); return; }
  if (ev.type === 'bot.message') {
    if (ev.project !== e.pid) return;
    const m = ev.message as EngineChatMessage;
    if (m.who === 'system') return;
    const mm = mapMsg(m);
    // the first message of a new conversation opens that conversation
    set((s) => ({ msgs: [...s.msgs, mm], typing: m.who === 'you' ? s.typing : false,
      ...(s.activeChat === 'new' && mm.who === 'you' && mm.thread ? { activeChat: mm.thread } : {}) }));
    return;
  }
  if (ev.type === 'bot.group') {
    const g = ev.group as BotGroup;
    for (const t of g.tasks) onTask(t);
    if (g.project === e.pid && g.status !== 'running' && g.id === pendingGroup) {
      pendingGroup = null;
      scheduleReload({ log: true });
      if (g.status === 'done') set({ layer: 'how', lastLayer: 'how', review: true, selected: null, tool: null, openPin: null, menu: null });
    }
  }
}

// ---------- extra calls the screens use directly ----------

export async function applyBranch(branch: string) {
  const into = eng()?.log?.headBranch ?? 'main';
  if (branch === into) { get().showToast(`${branch} is already your version`); return; }
  try {
    await api(P('/merge'), { body: { source: branch, into } });
    get().showToast(`Applied ${branch} to ${into}`);
    scheduleReload();
  } catch (e) { fail(e, 'Could not apply: '); }
}

export async function checkoutRef(ref: string) {
  try {
    await api(P('/checkout'), { body: { ref } });
    get().showToast(`Checked out ${ref}`);
    await Promise.all([loadLog(), loadSpec(), loadNotes()]);
    await loadModel();
  } catch (e) { fail(e); }
}

export async function branchFrom(shortId: string) {
  try {
    const n = (eng()?.log?.branches.length ?? 1) + 1;
    const r = await api<{ branch: string }>(P('/branches'), { body: { name: `variant-${n}`, from_ref: fullId(shortId) } });
    get().showToast(`Created ${r.branch}`);
    await loadLog();
  } catch (e) { fail(e); }
}

export async function compareCommit(shortId: string) {
  const e = eng();
  if (!e || e.compare[shortId]) return;
  try {
    const [r] = await api<{ mass_kg: number; ok: boolean }[]>(P(`/compare?refs=${fullId(shortId)}`));
    const cur = eng();
    if (r && cur) patchEng({ compare: { ...cur.compare, [shortId]: { mass_kg: r.mass_kg, ok: r.ok } } });
  } catch { /* numbers are optional */ }
}

export async function savePart(part: string, code: string, module = false) {
  try {
    const r = await api<{ commit: { short: string } | null; branch: string }>(P(`/${module ? 'lib' : 'parts'}/${encodeURIComponent(part)}`), { method: 'PUT', body: { code } });
    get().showToast(r.commit ? `Saved as ${r.commit.short} on ${r.branch}` : 'No changes');
    await Promise.all([loadLog(), loadModel()]);
  } catch (e) { fail(e, 'Could not save: '); }
}

export async function exportModel(format: 'step' | 'stl') {
  try {
    get().showToast(`Exporting ${format.toUpperCase()}…`);
    const { blob, name } = await apiBlob(P('/export'), { format });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { fail(e, 'Export failed: '); }
}

export async function setNoteResolved(id: number, resolved: boolean) {
  try { await api(P(`/notes/${id}/state`), { body: { resolved } }); await loadNotes(); } catch (e) { fail(e); }
}

export async function stopTask(id: string) {
  try { onTask(await api<BotTask>(`/api/bot/tasks/${id}/stop`, { method: 'POST', body: {} })); } catch (e) { fail(e); }
}

export async function stopTasks() {
  const e = eng();
  if (!e) return;
  for (const t of Object.values(e.tasks)) if (t.status === 'running' && t.project === e.pid) await api(`/api/bot/tasks/${t.id}/stop`, { method: 'POST', body: {} }).catch(() => undefined);
}

export async function saveBotSettings(patch: Record<string, unknown>) {
  try { const bot = await api<BotStatus>('/api/settings', { method: 'PUT', body: patch }); patchEng({ bot }); } catch (e) { fail(e); }
}

export async function setSessionKey(provider: string, key: string) {
  try { const bot = await api<BotStatus>('/api/settings/key', { body: { provider, key } }); patchEng({ bot }); get().showToast('Key kept in memory until the engine stops'); } catch (e) { fail(e); }
}

// ---------- boot ----------

let started = false;
export async function startEngineSync() {
  if (started) return;
  started = true;
  if (!(await probe())) return; // no engine: stay on mock data
  const mock: AppActions = { ...get() };
  const state: EngineState = {
    online: true, pid: null, projects: [], manifest: null, building: false, log: null, files: {}, bot: null,
    tasks: {}, keyOf: {}, qidOf: {}, cardAns: {}, compare: {}, mates: [], sim: emptySim(),
  };
  set({ eng: state, ...engineActions(mock) } as Partial<AppState>);
  connectEvents(onEvent, (up) => patchEng({ online: up }));

  // save overview edits (debounced)
  let ovTimer: ReturnType<typeof setTimeout> | null = null;
  useApp.subscribe((s, prev) => {
    if (!s.eng?.pid || s.overview === prev.overview || s.overview === lastOverview) return;
    if (ovTimer) clearTimeout(ovTimer);
    ovTimer = setTimeout(() => {
      const text = get().overview;
      lastOverview = text;
      api(P('/spec/overview'), { method: 'PUT', body: { overview: text } }).catch((e) => fail(e));
    }, 900);
  });

  try {
    const projects = await refreshProjects();
    let want: string | null = new URLSearchParams(window.location.search).get('project');
    try { want = want ?? localStorage.getItem('newcad.project'); } catch { /* private mode */ }
    const pick = projects.find((p) => p.id === want) ?? projects.slice().sort((a, b) => b.updated - a.updated)[0];
    if (pick) await openProject(pick.id);
    else {
      set({ layer: 'home', projectName: 'New project', commits: [], msgs: [{ who: 'bot', text: 'Hi, I am Bot. Tell me in a sentence or two what you want to build, and I will set up the project.' }] });
    }
  } catch (e) {
    fail(e, 'Engine: ');
  }
}

