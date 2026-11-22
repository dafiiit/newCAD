import { useState } from 'react';
import { GENERIC_SUGG, NEED_ICON, NEEDS, NEEDS_GEN } from '../../data/seed';
import type { Card, CardType } from '../../data/types';
import { infoOf, ivCurrent, openKeys, useApp } from '../../state/store';
import { ArrowRight, CloseIcon, CubeIcon, ImageIcon, PathIcon, PlusIcon, SketchIcon, VideoIcon } from '../../components/icons';
import { cx } from '../../components/ui';
import { useDraft } from './WhatScreen';

/** The scrolling spec sheet to the right of the criteria panel. */
export function Board({ left }: { left: number }) {
  const s = useApp();
  const { set } = s;
  const open = openKeys(s);
  const total = s.cats.reduce((n, c) => n + c.qs.length + c.qs.reduce((m, _, i) => m + (s.fups[`${c.id}:${i}`] ?? []).length, 0), 0);
  const answered = total - open.length;
  const ivActive = !!s.iv;
  const specDone = open.length === 0;
  // next open main question: prefer later ones in the current criterion, then the first anywhere
  const openMain = open.filter((k) => k.split(':').length === 2).map((k) => ({ cat: k.split(':')[0], i: Number(k.split(':')[1]) }));
  const inCur = s.whatView !== 'overview' ? openMain.filter((o) => o.cat === s.cat) : [];
  const next = inCur.find((o) => o.i > s.q) ?? inCur[0] ?? openMain[0] ?? null;
  const nextCat = next ? s.cats.find((c) => c.id === next.cat) : undefined;
  const genLabel = specDone ? 'Generate 3 prototypes'
    : next && next.cat === s.cat && s.whatView !== 'overview' ? 'Next open question'
      : `Go to ${nextCat?.name ?? ''} · ${openMain.filter((o) => o.cat === next?.cat).length} open`;
  const goNext = () => {
    if (specDone) { s.generate(); return; }
    if (!next) return;
    set({ whatView: 'cat', cat: next.cat, q: next.i, expanded: { ...s.expanded, [next.cat]: true } });
    setTimeout(() => document.getElementById(`q-${next.cat}-${next.i}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
  };

  return (
    <section className="board" style={{ left }} aria-label="Problem definition board">
      <div className="boardIn">
        <h1 className="sectitle" id="sec-overview">Overview</h1>
        {!s.agentBarHidden && (
          <div className="agentbar qbar">
            <span className="abtext"><b>Questionnaire</b> · {answered} of {total} answered</span>
            <span className="ahead"><span className="bar2"><span style={{ width: `${total ? Math.round((answered / total) * 100) : 0}%` }} /></span></span>
            {!ivActive && !specDone && <button className="linkbtn" onClick={s.startInterview}>Start interview</button>}
            {ivActive && <button className="linkbtn" onClick={() => set({ iv: null })}>Pause</button>}
            {ivActive && <button className="linkbtn" title="Stop the interview; open questions become Bot assumptions" onClick={s.buildNow}>Build now</button>}
            <button className="pillbtn dark" onClick={goNext}>{genLabel}</button>
            <button className="iconbtn" aria-label="Hide questionnaire bar" title="Hide" onClick={() => set({ agentBarHidden: true })}><CloseIcon size={14} color="#111" width={2.2} /></button>
          </div>
        )}

        <section className="ovcard" aria-label="Project overview">
          <div className="ovbody">
            <span className={cx('adot', s.ovBy === 'agent' && 'bot')} title={s.ovBy === 'agent' ? 'Written by Bot' : 'Written by you'} />
            <textarea className="ovtext" rows={3} aria-label="Project overview" placeholder="e.g. A mount that holds a small generator on a test rig …"
              value={s.overview} onChange={(e) => set({ overview: e.target.value, ovBy: 'you' })} />
          </div>
          {s.ovFacts.length > 0 && (
            <div className="ovfacts"><span className="ovfl">Key facts</span>{s.ovFacts.map((f) => <span key={f} className="ovfact">{f}</span>)}</div>
          )}
          <div className="ovact">
            <button className="pillbtn" onClick={() => {
              s.userSays('Tighten the overview');
              setTimeout(() => { set({ ovBy: 'agent' }); s.say('I kept your overview; it already names the load, the interfaces and the environment. Edit it any time.'); }, 700);
            }}>{s.overview.trim() ? 'Tighten with Bot' : 'Let Bot draft it'}</button>
            <button className="pillbtn" onClick={() => { set({ cat: s.cats[0].id, q: 0, whatView: 'cat' }); document.getElementById(`sec-${s.cats[0].id}`)?.scrollIntoView({ behavior: 'smooth' }); }}>
              Continue with {s.cats[0]?.name}<ArrowRight size={14} width={2.2} />
            </button>
          </div>
        </section>

        {s.cats.map((c) => <CategorySection key={c.id} catId={c.id} />)}
      </div>
    </section>
  );
}

function CategorySection({ catId }: { catId: string }) {
  const cat = useApp((s) => s.cats.find((c) => c.id === catId)!);
  const adding = useApp((s) => s.newQCat === catId);
  const { set, addQuestion } = useApp.getState();
  const [text, setText] = useState('');

  return (
    <div className="catsec" id={`sec-${cat.id}`}>
      <h2 className="sectitle sub">{cat.name}</h2>
      {cat.qs.map((qt, i) => <QuestionCard key={`${cat.id}:${i}:${qt}`} catId={cat.id} i={i} text={qt} />)}
      {adding ? (
        <div className="qsec newq">
          <input id="newq-input" className="ansnew" aria-label="Your question" placeholder="Write your own question, e.g. Must it fit in a car trunk?" autoFocus
            value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { addQuestion(cat.id, text); setText(''); } if (e.key === 'Escape') set({ newQCat: null }); }} />
          <button className="pillbtn dark" onClick={() => { addQuestion(cat.id, text); setText(''); }}>Add</button>
          <button className="linkbtn" onClick={() => set({ newQCat: null })}>Cancel</button>
        </div>
      ) : (
        <button className="addq" onClick={() => set({ newQCat: cat.id, cat: cat.id })}><PlusIcon size={16} />Add your own question</button>
      )}
    </div>
  );
}

const ADD_TOOLS: { type: CardType; label: string; Icon: typeof ImageIcon }[] = [
  { type: 'image', label: 'Image', Icon: ImageIcon },
  { type: 'video', label: 'Video', Icon: VideoIcon },
  { type: 'model', label: '3D model', Icon: CubeIcon },
  { type: 'sketch', label: 'Sketch', Icon: SketchIcon },
];

function QuestionCard({ catId, i, text }: { catId: string; i: number; text: string }) {
  const key = `${catId}:${i}`;
  const s = useApp();
  const cat = s.cats.find((c) => c.id === catId)!;
  const cards = s.cards[key] ?? [];
  const asking = ivCurrent(s) === key;
  const meta = s.qMeta[key];
  const info = infoOf(s, key);
  const sugg = (info && meta !== 'you' ? info.ex : GENERIC_SUGG).slice(0, 3);
  const o = cat.orig[i];
  const needDefs = typeof o === 'number' && o >= 0 ? ((cat.src === 'gen' ? NEEDS_GEN : NEEDS)[`${catId}:${o}`] ?? []) : [];
  const needs = needDefs.filter(([type]) => !cards.some((c) => c.type === type));
  const texts = cards.filter((c) => c.type === 'text');
  const media = cards.filter((c) => c.type !== 'text');
  const [draft, setDraft] = useDraft(key);
  const anchor = key.replace(':', '-');

  return (
    <section className={cx('qsec', asking && 'asking', cards.length > 0 && 'done')} id={`q-${anchor}`} aria-label={`Question ${i + 1}`}>
      <div className="qhead">
        <span className="qnum">{i + 1}</span>
        <span className="qtext">{text}{asking && <span className="askbadge">Bot asks</span>}</span>
        <span className="qby">{meta === 'you' ? 'Your question' : meta === 'more' ? 'More from Bot' : 'Asked by Bot'}</span>
        <button className="iconbtn qdel" aria-label="Remove this question" title="Remove question" onClick={() => s.deleteQuestion(catId, i)}><CloseIcon size={13} color="#555" /></button>
      </div>

      {needs.length > 0 && (
        <div className="needs">
          <span className="needl">Most helpful:</span>
          {needs.map(([type, label]) => (
            <button key={label} className="needchip" onClick={() => (type === 'text' ? document.getElementById(`ans-${anchor}`)?.focus() : s.addCard(key, type))}>
              <PathIcon d={NEED_ICON[type]} size={13} />{label}
            </button>
          ))}
        </div>
      )}

      {cards.length > 0 && (
        <div className="answers">
          {texts.map((c) => <TextAnswer key={c.id} k={key} card={c} />)}
          {media.length > 0 && <div className="mediarow">{media.map((c) => <MediaTile key={c.id} k={key} card={c} />)}</div>}
        </div>
      )}

      {(asking || !cards.length) && (
        <div className="sugg">
          {sugg.map((x) => <button key={x} className="schip" onClick={() => s.submitAnswer(key, x)}>{x}</button>)}
          {asking && (
            <>
              <button className="schip ghost" onClick={() => s.answerIv('', 'assume')}>You decide</button>
              <button className="schip ghost" onClick={() => s.answerIv('', 'skip')}>Skip</button>
            </>
          )}
        </div>
      )}

      <div className="ansrow">
        <input id={`ans-${anchor}`} className="ansnew" aria-label={`Answer to question ${i + 1}`} placeholder={cards.length ? 'Add another answer…' : 'Type your answer…'}
          value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); s.submitAnswer(key, draft); } }} />
        {ADD_TOOLS.map(({ type, label, Icon }) => (
          <button key={type} className="mini" aria-label={`Add ${label.toLowerCase()}`} title={label} onClick={() => s.addCard(key, type)}><Icon size={16} /></button>
        ))}
      </div>

      {(s.fups[key] ?? []).map((f, j) => <FollowUpBlock key={j} k={`${key}:f${j}`} text={f.text} ex={f.ex} />)}
    </section>
  );
}

function FollowUpBlock({ k, text, ex }: { k: string; text: string; ex: string[] }) {
  const s = useApp();
  const cards = s.cards[k] ?? [];
  const asking = ivCurrent(s) === k;
  const [draft, setDraft] = useDraft(k);
  const anchor = k.replace(/:/g, '-');
  return (
    <div className={cx('fup', asking && 'asking', cards.length > 0 && 'done')} id={`q-${anchor}`}>
      <div className="fuhead"><span className="fulabel">Follow-up from Bot</span><span className="futext">{text}</span></div>
      {cards.map((c) => <TextAnswer key={c.id} k={k} card={c} />)}
      {(asking || !cards.length) && (
        <div className="sugg">
          {ex.map((x) => <button key={x} className="schip" onClick={() => s.submitAnswer(k, x)}>{x}</button>)}
          {asking && (
            <>
              <button className="schip ghost" onClick={() => s.answerIv('', 'assume')}>You decide</button>
              <button className="schip ghost" onClick={() => s.answerIv('', 'skip')}>Skip</button>
            </>
          )}
        </div>
      )}
      <div className="ansrow">
        <input id={`ans-${anchor}`} className="ansnew" aria-label="Answer to the follow-up" placeholder={cards.length ? 'Add to your answer…' : 'Your answer…'}
          value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); s.submitAnswer(k, draft); } }} />
      </div>
    </div>
  );
}

function TextAnswer({ k, card }: { k: string; card: Card }) {
  const { updateCard, removeCard } = useApp.getState();
  return (
    <div className="ans">
      <span className={cx('adot', card.by === 'agent' && 'bot')} title={card.by === 'agent' ? 'Added by Bot' : 'Your answer'} />
      <textarea className="ansin" rows={1} aria-label="Answer" value={card.text} onChange={(e) => updateCard(k, card.id, { text: e.target.value })} />
      <button className="iconbtn ansx" aria-label="Remove answer" onClick={() => removeCard(k, card.id)}><CloseIcon size={12} color="#555" /></button>
    </div>
  );
}

const pathD = (st: [number, number][]) => `M${st.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L')}`;

function MediaTile({ k, card }: { k: string; card: Card }) {
  const { updateCard, removeCard } = useApp.getState();
  const [cur, setCur] = useState<[number, number][] | null>(null);
  const strokes = [...(card.strokes ?? []), ...(cur ? [cur] : [])];

  return (
    <figure className="mtile">
      {card.type === 'image' && <div className="mprev img"><ImageIcon size={26} color="#555" width={1.5} /></div>}
      {card.type === 'video' && (
        <div className="mprev vid">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M10 8.5v7l5.5-3.5z" fill="#fff" /></svg>
        </div>
      )}
      {card.type === 'model' && (
        <div className="mprev mdl">
          <svg width="40" height="36" viewBox="0 0 70 62" fill="none" stroke="#111" strokeWidth="2" aria-hidden="true"><path d="M35 4L62 18v26L35 58 8 44V18z" /><path d="M8 18l27 14 27-14M35 32v26" /></svg>
        </div>
      )}
      {card.type === 'sketch' && (
        <div className="sketcharea mprev" role="img" aria-label="Sketch area, draw with the mouse"
          onPointerDown={(e) => { const r = e.currentTarget.getBoundingClientRect(); e.currentTarget.setPointerCapture(e.pointerId); setCur([[e.clientX - r.left, e.clientY - r.top]]); }}
          onPointerMove={(e) => { if (!cur) return; const r = e.currentTarget.getBoundingClientRect(); setCur([...cur, [e.clientX - r.left, e.clientY - r.top]]); }}
          onPointerUp={() => { if (cur && cur.length > 1) updateCard(k, card.id, { strokes: [...(card.strokes ?? []), cur] }); setCur(null); }}>
          {card.doodle && (
            <svg className="doodle" width="150" height="88" viewBox="0 0 190 130" fill="none" stroke="#111" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 112 L21 30 L35 31 L34 97 L152 96 L151 112 Z" /><path d="M35 60 C40 32 104 30 108 58 C110 84 42 88 35 60" /><path d="M108 58 L170 57" /><path d="M168 48 L178 58 L168 67" />
            </svg>
          )}
          {!card.doodle && !strokes.length && <span className="ph">Draw here</span>}
          {strokes.map((st, i) => (
            <svg key={i} className="stroke" aria-hidden="true"><path d={pathD(st)} fill="none" stroke="#111" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
          ))}
        </div>
      )}
      <figcaption>
        <input className="cap" aria-label="Caption" value={card.label} onChange={(e) => updateCard(k, card.id, { label: e.target.value })} />
        <button className="iconbtn ansx" aria-label="Remove" onClick={() => removeCard(k, card.id)}><CloseIcon size={12} color="#555" /></button>
      </figcaption>
    </figure>
  );
}
