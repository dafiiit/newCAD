"""Model adapters: Anthropic, OpenAI, OpenAI-compatible, and a scripted one for tests."""
from __future__ import annotations

import os
from typing import Any

from .base import AdapterError, Conversation, ToolCall, ToolOutput, ToolSpec, Turn

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "key_env": "ANTHROPIC_API_KEY", "default_model": "claude-opus-5-5"},
    "openai": {"label": "OpenAI", "key_env": "OPENAI_API_KEY", "default_model": "gpt-5"},
    "openai-compatible": {"label": "OpenAI-compatible (LM Studio, Ollama, MLX, vLLM)", "key_env": "NEWCAD_COMPAT_API_KEY", "default_model": ""},
    "scripted": {"label": "Scripted (testing only)", "key_env": None, "default_model": "scripted"},
}


def scripted_allowed() -> bool:
    return os.environ.get("NEWCAD_ALLOW_SCRIPTED") == "1"


def resolve(settings: dict[str, Any], session_keys: dict[str, str]) -> dict[str, Any]:
    """Work out which provider/model a task uses and whether it can run. Never returns the key itself."""
    provider = settings.get("provider") or "anthropic"
    info = PROVIDERS.get(provider)
    if info is None or (provider == "scripted" and not scripted_allowed()):
        return {"provider": provider, "ready": False, "problem": f"Unknown model provider {provider!r}"}
    model = settings.get("model") or info["default_model"]
    base_url = settings.get("base_url") or ""
    out: dict[str, Any] = {"provider": provider, "label": info["label"], "model": model, "base_url": base_url, "ready": True, "problem": ""}
    env = info["key_env"]
    if provider == "openai-compatible":
        if not base_url:
            out.update(ready=False, problem="Set the endpoint URL of your local model server (e.g. http://localhost:1234/v1)")
        if not model:
            out.update(ready=False, problem="Set the model name your local server exposes")
    elif env:
        has_key = bool(session_keys.get(provider) or os.environ.get(env) or (provider == "anthropic" and os.environ.get("ANTHROPIC_AUTH_TOKEN")))
        if not has_key:
            out.update(ready=False, problem=f"No API key: set {env} in the engine's environment", key_env=env)
    out["key_env"] = env
    return out


def make_conversation(settings: dict[str, Any], session_keys: dict[str, str], system: str, tools: list[ToolSpec],
                      extra: dict[str, Any] | None = None) -> Conversation:
    r = resolve(settings, session_keys)
    if not r["ready"]:
        raise AdapterError(r["problem"])
    opts: dict[str, Any] = {
        "base_url": r["base_url"], "effort": settings.get("effort", "high"), "vision": settings.get("vision", True),
        "auth": settings.get("auth") or "auto",
        "context_window": int(settings.get("context_window") or 0), "max_output": int(settings.get("max_output") or 0),
        **(extra or {}),
    }
    key = session_keys.get(r["provider"])
    if key:
        opts["api_key"] = key
    p = r["provider"]
    if p == "anthropic":
        from .anthropic_adapter import AnthropicConversation
        return AnthropicConversation(system, tools, r["model"], opts)
    if p in ("openai", "openai-compatible"):
        from .openai_adapter import OpenAIConversation
        if p == "openai-compatible" and not key:
            opts["api_key"] = os.environ.get("NEWCAD_COMPAT_API_KEY", "")
        return OpenAIConversation(system, tools, r["model"], opts)
    from .scripted import ScriptedConversation
    return ScriptedConversation(system, tools, r["model"], opts)


__all__ = ["AdapterError", "Conversation", "ToolCall", "ToolOutput", "ToolSpec", "Turn", "PROVIDERS", "resolve", "make_conversation"]
