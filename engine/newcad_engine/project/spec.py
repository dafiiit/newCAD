"""Helpers for spec.yaml (the What? sheet) and notes.yaml (3D comments)."""
from __future__ import annotations

import re
import time
from typing import Any

from .store import StoreError, slugify


def questions(spec: dict[str, Any]):
    for c in spec.get("categories", []):
        for q in c.get("questions", []):
            yield c, q


def find_question(spec: dict[str, Any], qid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for c, q in questions(spec):
        if q["id"] == qid:
            return c, q
    raise StoreError(f"No question {qid!r}. Use spec_open_questions or spec_read to see the ids.")


def open_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": q["id"], "category": c["name"], "text": q["text"], "parent": q.get("parent"), "examples": q.get("examples", []),
         "assume": q.get("assume", "")}
        for c, q in questions(spec) if not q.get("answers")
    ]


def answer(spec: dict[str, Any], qid: str, text: str, by: str, assumption: bool = False, replace: bool = False) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise StoreError("Answer text is empty")
    _, q = find_question(spec, qid)
    q.setdefault("answers", [])
    if replace:
        q["answers"] = [a for a in q["answers"] if a.get("by") != by]
    q["answers"].append({"text": text, "by": by, "assumption": bool(assumption)})
    return q


def add_question(spec: dict[str, Any], category: str, text: str, by: str, parent: str | None = None,
                 examples: list[str] | None = None, assume: str = "") -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise StoreError("Question text is empty")
    if not text.endswith("?"):
        text += "?"
    cats = spec.setdefault("categories", [])
    cat = next((c for c in cats if c["id"] == category or c["name"].lower() == category.lower()), None)
    if cat is None:
        cat = {"id": slugify(category, "topic"), "name": category.strip().capitalize(), "questions": []}
        cats.append(cat)
    if parent:
        find_question(spec, parent)
    n = 1 + max([int(m.group(1)) for q in cat["questions"] if (m := re.search(r"-(\d+)$", q["id"]))] or [0])
    q = {"id": f"{cat['id']}-{n}", "text": text, "examples": examples or [], "assume": assume, "by": by, "answers": []}
    if parent:
        q["parent"] = parent
        # place a follow-up right after its parent (and its earlier follow-ups)
        idx = max(i for i, x in enumerate(cat["questions"]) if x["id"] == parent or x.get("parent") == parent)
        cat["questions"].insert(idx + 1, q)
    else:
        cat["questions"].append(q)
    return q


def spec_text_summary(spec: dict[str, Any]) -> str:
    """Compact, readable form of the spec for prompts."""
    lines = [f"Goal: {spec.get('goal', '')}".strip()]
    if spec.get("overview") and spec.get("overview") != spec.get("goal"):
        lines.append(f"Overview: {spec['overview']}")
    for c, q in questions(spec):
        ans = "; ".join(f"{'(assumed) ' if a.get('assumption') else ''}{a['text']}" for a in q.get("answers", [])) or "OPEN"
        lines.append(f"- [{q['id']}] {c['name']}: {q['text']} -> {ans}")
    return "\n".join(lines)


# ---------- notes ----------

def add_note(notes: dict[str, Any], part: str, text: str, who: str, point: list[float] | None = None,
             face: str | None = None, face_sig: dict[str, Any] | None = None, queued: bool = False) -> dict[str, Any]:
    items = notes.setdefault("notes", [])
    nid = 1 + max([n["id"] for n in items] or [0])
    note = {"id": nid, "part": part, "point": point, "face": face, "face_sig": face_sig,
            "status": "queued" if queued else "open", "created": int(time.time()), "msgs": [{"who": who, "text": text}]}
    items.append(note)
    return note


def find_note(notes: dict[str, Any], nid: int) -> dict[str, Any]:
    for n in notes.get("notes", []):
        if n["id"] == nid:
            return n
    raise StoreError(f"No comment #{nid}")
