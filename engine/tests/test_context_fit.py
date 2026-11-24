"""Conversations for models with a small context window are trimmed before they are sent."""
from types import SimpleNamespace as NS

import pytest

from newcad_engine.agent.adapters import fit as F
from newcad_engine.agent.adapters.base import AdapterError, ToolOutput, ToolSpec
from newcad_engine.agent.adapters.openai_adapter import OpenAIConversation

TOOLS = [ToolSpec("read", "Read a file", {"type": "object", "properties": {}})]


class FakeClient:
    def __init__(self):
        self.sent = []
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        self.sent.append({"messages": [dict(m) for m in kw["messages"]], **{k: v for k, v in kw.items() if k != "messages"}})
        est = F.estimate(kw["messages"], kw["tools"])
        msg = NS(content="", tool_calls=[NS(id=f"c{len(self.sent)}", type="function", function=NS(name="read", arguments="{}"))], model_extra={})
        return NS(choices=[NS(message=msg, finish_reason="tool_calls")], usage=NS(prompt_tokens=est, completion_tokens=10))


async def test_long_task_stays_inside_the_window():
    client = FakeClient()
    conv = OpenAIConversation("system", TOOLS, "qwen", {"base_url": "http://nas/v1", "client": client, "context_window": 8000, "max_output": 2000})
    await conv.send_user("Build a bracket")
    budget = F.prompt_budget(8000, 2000)
    for i in range(30):
        await conv.send_tool_results([ToolOutput(f"c{i + 1}", "x" * 3000, images=[b"png"] if i % 3 == 0 else [])])
    for call in client.sent:
        assert F.estimate(call["messages"], call["tools"]) <= budget
        assert call["max_tokens"] == 2000
    last = client.sent[-1]["messages"]
    assert last[0]["role"] == "system" and last[1]["content"].startswith("Build a bracket")
    assert "removed to fit" in last[1]["content"]
    # every tool result still follows the assistant turn that asked for it
    ids = set()
    for m in last:
        if m["role"] == "assistant":
            ids = {c["id"] for c in m.get("tool_calls", [])}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in ids


async def test_no_window_means_no_trimming():
    client = FakeClient()
    conv = OpenAIConversation("s", TOOLS, "m", {"base_url": "http://x/v1", "client": client})
    await conv.send_user("hi")
    for i in range(5):
        await conv.send_tool_results([ToolOutput(f"c{i + 1}", "y" * 50_000)])
    assert all(len(m["content"]) == 50_000 for m in client.sent[-1]["messages"] if m["role"] == "tool")
    assert "max_tokens" not in client.sent[-1]


async def test_too_big_to_fit_is_a_clear_error():
    conv = OpenAIConversation("s" * 30_000, TOOLS, "m", {"base_url": "http://x/v1", "client": FakeClient(), "context_window": 4000})
    with pytest.raises(AdapterError, match="context window"):
        await conv.send_user("hi")


def test_profile_keeps_limits(tmp_path):
    from newcad_engine.config import Config
    from newcad_engine.core import Engine
    eng = Engine(Config(home=tmp_path, token="t", workers=1))
    eng.settings.upsert_profile({"name": "Strata", "provider": "openai-compatible", "base_url": "http://nas/v1", "model": "q",
                                 "context_window": 131072, "max_output": 32000, "activate": True})
    assert eng.settings.data["context_window"] == 131072 and eng.settings.data["max_output"] == 32000
    eng.settings.update({"active_profile": "default"})
    assert eng.settings.data["context_window"] == 0
