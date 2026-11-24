"""OpenAI and any OpenAI-compatible endpoint (LM Studio, Ollama, MLX server, vLLM) via Chat Completions."""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import openai

from . import fit as F
from .base import AdapterError, Conversation, ToolCall, ToolOutput, ToolSpec, Turn

DEFAULT_MODEL = "gpt-5"


class OpenAIConversation(Conversation):
    def __init__(self, system: str, tools: list[ToolSpec], model: str, options: dict[str, Any]):
        super().__init__(system, tools, model or DEFAULT_MODEL, options)
        kw: dict[str, Any] = {"max_retries": 3}
        if options.get("base_url"):
            kw["base_url"] = options["base_url"]
            kw["api_key"] = options.get("api_key") or "not-needed"  # local servers usually ignore the key
        elif options.get("api_key"):
            kw["api_key"] = options["api_key"]
        if options.get("auth") == "x-api-key" and options.get("api_key"):
            # some gateways want the key in x-api-key instead of Authorization: Bearer
            kw["default_headers"] = {"x-api-key": options["api_key"]}
        self.client = options.get("client") or openai.AsyncOpenAI(**kw)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in tools]
        self.context_window = int(options.get("context_window") or 0)
        self.max_output = int(options.get("max_output") or 0)
        self.scale = 1.0  # estimate -> real prompt tokens, learned from the server's usage numbers

    async def _call(self) -> Turn:
        params: dict[str, Any] = {"model": self.model, "messages": self.messages, "tools": self.api_tools}
        if self.max_output:
            # the official API wants max_completion_tokens; compatible servers know max_tokens
            params["max_tokens" if self.options.get("base_url") else "max_completion_tokens"] = self.max_output
        sent_estimate = 0
        if self.context_window:
            budget = F.prompt_budget(self.context_window, self.max_output)
            if not F.fit(self.messages, self.api_tools, budget, self.scale):
                raise AdapterError(f"This task no longer fits the model's context window ({self.context_window:,} tokens), even after trimming. "
                                   "Start a new chat or pick a model with a larger window.")
            sent_estimate = F.estimate(self.messages, self.api_tools)
        try:
            resp = await self.client.chat.completions.create(**params)
        except openai.AuthenticationError as e:
            raise AdapterError("The model provider rejected the API key.") from e
        except openai.NotFoundError as e:
            raise AdapterError(f"Unknown model {self.model} at this endpoint") from e
        except openai.RateLimitError as e:
            raise AdapterError("Rate limit reached; try again in a minute.") from e
        except openai.APIStatusError as e:
            raise AdapterError(f"Model API error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise AdapterError(f"Can't reach the model endpoint {self.options.get('base_url') or 'api.openai.com'}.") from e
        choice = resp.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        raw_calls = []
        for tc in msg.tool_calls or []:
            if getattr(tc, "type", "function") != "function":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": tc.function.arguments}
            calls.append(ToolCall(tc.id, tc.function.name, args))
            raw_calls.append({"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}})
        entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if raw_calls:
            entry["tool_calls"] = raw_calls
        self.messages.append(entry)
        u = resp.usage
        tin, tout = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        if sent_estimate and tin:
            # never trust the estimate to be high; learn when it was low
            self.scale = max(1.0, min(3.0, tin / sent_estimate))
        text, thinking = split_reasoning(msg)
        if choice.finish_reason == "content_filter":
            return Turn(text, [], "refusal", tin, tout, detail="content_filter", thinking=thinking)
        if choice.finish_reason == "length" and not calls:
            return Turn(text, [], "max_tokens", tin, tout, thinking=thinking)
        return Turn(text, calls, "tool" if calls else "end", tin, tout, thinking=thinking)

    async def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return await self._call()

    async def send_tool_results(self, outputs: list[ToolOutput]) -> Turn:
        images: list[bytes] = []
        for o in outputs:
            text = ("ERROR: " if o.is_error else "") + (o.text or "(no output)")
            if o.images:
                text += f"\n({len(o.images)} image(s) attached in the next message)"
                images.extend(o.images)
            self.messages.append({"role": "tool", "tool_call_id": o.call_id, "content": text})
        # Chat Completions tool messages can't carry images, so pictures follow as a user message
        if images and self.options.get("vision", True):
            content: list[dict[str, Any]] = [{"type": "text", "text": "Images returned by the tools above:"}]
            for img in images:
                content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()}})
            self.messages.append({"role": "user", "content": content})
        return await self._call()


_THINK = re.compile(r"<(think|thinking|thought)>(.*?)(?:</\1>|$)", re.S | re.I)


def split_reasoning(msg: Any) -> tuple[str, str]:
    """Reasoning comes back as a separate field (LM Studio, vLLM, Ollama, DeepSeek: reasoning_content or
    reasoning) or inline as <think>...</think> in the text. Returns (visible text, reasoning)."""
    content = msg.content or ""
    parts = []
    for attr in ("reasoning_content", "reasoning"):
        v = getattr(msg, attr, None)
        if v is None and getattr(msg, "model_extra", None):
            v = msg.model_extra.get(attr)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
            break
    for m in _THINK.finditer(content):
        parts.append(m.group(2).strip())
    if parts:
        content = _THINK.sub("", content).strip()
    return content, "\n\n".join(p for p in parts if p)
