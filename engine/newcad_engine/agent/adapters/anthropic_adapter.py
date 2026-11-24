"""Claude via the official Anthropic Python SDK (Messages API, manual tool loop)."""
from __future__ import annotations

import base64
from typing import Any

import anthropic

from .base import AdapterError, Conversation, ToolCall, ToolOutput, ToolSpec, Turn

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicConversation(Conversation):
    def __init__(self, system: str, tools: list[ToolSpec], model: str, options: dict[str, Any]):
        super().__init__(system, tools, model or DEFAULT_MODEL, options)
        kw: dict[str, Any] = {"max_retries": 3}
        if options.get("api_key"):
            if options.get("auth") == "bearer":  # gateways that want Authorization: Bearer instead of x-api-key
                kw["auth_token"] = options["api_key"]
                kw["api_key"] = None
            else:
                kw["api_key"] = options["api_key"]
        if options.get("base_url"):
            kw["base_url"] = options["base_url"]
        self.client = options.get("client") or anthropic.AsyncAnthropic(**kw)
        self.messages: list[dict[str, Any]] = []
        # Server-side refusal fallback is on by default for the Claude API; a custom base URL
        # (proxy, gateway) may not accept the beta, so it is off there.
        self.fallbacks = options.get("fallbacks", not options.get("base_url"))
        self.api_tools = [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools]

    async def _call(self) -> Turn:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(self.options.get("max_output") or self.options.get("max_output_tokens", 16000)),
            "system": self.system,
            "tools": self.api_tools,
            "messages": self.messages,
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": self.options.get("effort", "high")},
            # readable summaries of the reasoning, shown to the user as the Bot's trace
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        try:
            if self.fallbacks:
                resp = await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                resp = await self.client.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise AdapterError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from e
        except anthropic.PermissionDeniedError as e:
            raise AdapterError(f"This API key can't use {self.model}: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise AdapterError(f"Unknown model {self.model}") from e
        except anthropic.RateLimitError as e:
            raise AdapterError("Claude rate limit reached; try again in a minute.") from e
        except anthropic.BadRequestError as e:
            raise AdapterError(f"Claude refused the request: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise AdapterError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AdapterError("Can't reach the Claude API (network).") from e

        # keep every block (thinking, fallback, tool_use) exactly as returned
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input or {})) for b in resp.content if getattr(b, "type", "") == "tool_use"]
        thinking = "\n\n".join(t for b in resp.content if getattr(b, "type", "") == "thinking" and (t := (getattr(b, "thinking", "") or "").strip()))
        u = resp.usage
        tokens_in = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            return Turn(text, [], "refusal", tokens_in, u.output_tokens, detail=str(cat or ""), thinking=thinking)
        if resp.stop_reason == "max_tokens" and not calls:
            return Turn(text, [], "max_tokens", tokens_in, u.output_tokens, thinking=thinking)
        if resp.stop_reason == "pause_turn":
            # server paused a long turn: send it back as is to continue
            return await self._call()
        return Turn(text, calls, "tool" if calls else "end", tokens_in, u.output_tokens, thinking=thinking)

    async def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return await self._call()

    async def send_tool_results(self, outputs: list[ToolOutput]) -> Turn:
        blocks = []
        for o in outputs:
            content: list[dict[str, Any]] = [{"type": "text", "text": o.text or "(no output)"}]
            if self.options.get("vision", True):
                for img in o.images:
                    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(img).decode()}})
            blocks.append({"type": "tool_result", "tool_use_id": o.call_id, "content": content, "is_error": o.is_error})
        # all results of one turn go back in a single user message
        self.messages.append({"role": "user", "content": blocks})
        return await self._call()
