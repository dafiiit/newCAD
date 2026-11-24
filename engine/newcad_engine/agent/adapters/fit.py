"""Keep a Chat Completions conversation inside the model's context window.

Local and self-hosted servers (LM Studio, llama.cpp, a GPU box on the LAN) often do not reject a
prompt that is too long: they try to process it and can stall or take the machine down. So before
every call the conversation is measured and, if prompt plus reply would not fit, shrunk:

1. pictures from older tool results go first (the newest set stays),
2. then older tool results and replies are cut to a short head,
3. then the oldest whole steps (assistant turn, its tool results, their pictures) are dropped.

The system prompt, the user's request and the latest step always stay. Token counts are estimated
(characters / 3, a fixed cost per image) and calibrated with the prompt_tokens the server reports.
"""
from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 3.0  # conservative: code and JSON tokenize denser than prose
IMAGE_TOKENS = 1500
SAFETY = 0.05  # keep 5 % of the window free for estimate error and chat-template overhead
KEEP_HEAD = 400  # characters left of a trimmed tool result
TRIMMED = "\n…(trimmed to fit the model's context window)"
DROPPED = "\n\n(Earlier steps of this task were removed to fit the model's context window; check the current state with the tools.)"
IMAGES_DROPPED = "(older images removed to fit the model's context window)"


def estimate(messages: list[dict[str, Any]], tools: list[dict[str, Any]], scale: float = 1.0) -> int:
    chars, images = len(json.dumps(tools)), 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if part.get("type") == "image_url":
                    images += 1
                else:
                    chars += len(part.get("text") or "")
        else:
            chars += len(c or "")
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"]))
        chars += 16  # role and template tokens
    return int((chars / CHARS_PER_TOKEN + images * IMAGE_TOKENS) * scale)


def prompt_budget(context_window: int, max_output: int) -> int:
    reply = max_output or min(8192, context_window // 4)
    return int(context_window * (1 - SAFETY)) - reply


def _steps(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """[start, end) of each step after the opening user message: an assistant message plus what
    follows it (tool results, an image message) up to the next assistant message."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    return [(s, starts[k + 1] if k + 1 < len(starts) else len(messages)) for k, s in enumerate(starts)]


def fit(messages: list[dict[str, Any]], tools: list[dict[str, Any]], budget: int, scale: float = 1.0) -> bool:
    """Shrink `messages` in place until the estimate is within `budget`. Returns False if even the
    smallest form (system, request, latest step cut down) does not fit."""
    def ok() -> bool:
        return estimate(messages, tools, scale) <= budget

    if ok():
        return True
    steps = _steps(messages)
    old = steps[:-1]  # the latest step stays whole as long as possible

    # 1. pictures, oldest first, all but the newest message that has any
    img_msgs = [i for i, m in enumerate(messages) if isinstance(m.get("content"), list)
                and any(p.get("type") == "image_url" for p in m["content"])]
    for i in img_msgs[:-1]:
        messages[i]["content"] = IMAGES_DROPPED
        if ok():
            return True

    # 2. cut older tool results and assistant text to a head, oldest first
    for s, e in old:
        for i in range(s, e):
            m = messages[i]
            c = m.get("content")
            if isinstance(c, str) and len(c) > KEEP_HEAD + len(TRIMMED) and m["role"] in ("tool", "assistant"):
                m["content"] = c[:KEEP_HEAD] + TRIMMED
        if ok():
            return True

    # 3. drop whole old steps, oldest first (an assistant turn always goes with its tool results).
    #    A note goes into the request itself, not a new message: some chat templates need roles to alternate.
    while len(_steps(messages)) > 1 and not ok():
        s, e = _steps(messages)[0]
        del messages[s:e]
        first = next((m for m in messages if m["role"] == "user" and isinstance(m.get("content"), str)), None)
        if first is not None and DROPPED not in first["content"]:
            first["content"] += DROPPED
    if ok():
        return True

    # 4. last resort: the latest step's own pictures and long results
    for i in range(len(messages)):
        m = messages[i]
        if i < 2:
            continue
        if isinstance(m.get("content"), list):
            m["content"] = IMAGES_DROPPED
        elif m["role"] == "tool" and len(m.get("content") or "") > 4 * KEEP_HEAD:
            room = max(KEEP_HEAD, int((budget - estimate(messages, tools, scale)) * CHARS_PER_TOKEN / scale) + len(m["content"]))
            m["content"] = m["content"][:max(KEEP_HEAD, room - len(TRIMMED))] + TRIMMED
        if ok():
            return True
    return ok()
