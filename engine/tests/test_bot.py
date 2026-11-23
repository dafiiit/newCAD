"""BuilderBot: loop, guard rails and the provider adapters (no network: scripted model and fake SDK clients)."""
from types import SimpleNamespace as NS

import pytest

from newcad_engine.agent.adapters import resolve
from newcad_engine.agent.adapters.anthropic_adapter import AnthropicConversation
from newcad_engine.agent.adapters.base import ToolCall, ToolOutput, ToolSpec, Turn
from newcad_engine.agent.adapters.openai_adapter import OpenAIConversation
from newcad_engine.agent.adapters.scripted import call
from newcad_engine.project.store import StoreError

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_generate_three_concepts_on_branches_without_touching_head(engine):
    p = engine.store.create("Shelf bracket", "A wall bracket for a 5 kg shelf, printed in PETG.")
    head_before = str(p.resolve("HEAD").id)
    g = engine.bot.generate(p.id)
    assert [t["branch"] for t in g["tasks"]] == ["concept-a", "concept-b", "concept-c"]
    tasks = [await engine.bot.wait(t["id"]) for t in g["tasks"]]
    assert all(t.status == "done" and t.builds for t in tasks), [(t.status, t.problem) for t in tasks]
    masses = {t.concept: t.mass_kg for t in tasks}
    assert masses["C"] < masses["A"]  # the light concept is lighter
    assert str(p.resolve("HEAD").id) == head_before and p.head_ref() == "main"
    for t in tasks:
        assert all(c["author"] == "Bot" for c in t.commits)
        man = await engine.geometry.build(p, t.branch)
        assert man["ok"] and [x["id"] for x in man["parts"]] == ["bracket"]


async def test_question_without_changes_leaves_no_branch(engine):
    p = engine.store.create("Chat only")

    def script(text, ctx):
        yield Turn("", [call("spec_read")], "tool")
        yield Turn("Concept B is stiffer because of the ribs.", [], "end")
    engine.bot.script = script
    try:
        t = engine.bot.start_change(p.id, "Why concept B?")
        t = await engine.bot.wait(t.id)
    finally:
        engine.bot.script = None
    assert t.status == "done" and t.branch == "" and p.branches() == ["main"]
    chat = engine.bot.chat(p.id)
    assert chat[-2]["who"] == "you" and "stiffer" in chat[-1]["text"]


async def test_step_budget_stops_a_runaway_loop(engine):
    p = engine.store.create("Runaway")
    engine.settings.update({"max_steps": 5})

    def script(text, ctx):
        while True:
            yield Turn("", [call("spec_open_questions")], "tool")
    engine.bot.script = script
    try:
        t = await engine.bot.wait(engine.bot.start_change(p.id, "loop forever").id)
    finally:
        engine.bot.script = None
        engine.settings.update({"max_steps": 40})
    assert t.status == "stopped" and "step budget" in t.problem and t.step == 4


async def test_bot_cannot_escape_its_branch(engine):
    p = engine.store.create("Escape", template="demo")

    def script(text, ctx):
        out = yield Turn("", [call("geometry_patch_part", part="plate", find="Box(220", replace="Box(10", branch="main")], "tool")
        assert not out[0].is_error  # the runtime pins the branch, so this lands on the Bot's branch
        out = yield Turn("", [call("project_checkout", ref="main")], "tool")
        assert out[0].is_error and "Unknown tool" in out[0].text  # not even offered
        yield Turn("", [call("project_commit", message="edit")], "tool")
        yield Turn("ok", [], "end")
    engine.bot.script = script
    try:
        t = await engine.bot.wait(engine.bot.start_change(p.id, "smaller plate").id)
    finally:
        engine.bot.script = None
    assert t.status == "done" and t.branch.startswith("bot/")
    assert "Box(220" in p.read("parts/plate.py", "main") and "Box(10" in p.read("parts/plate.py", t.branch)


async def test_bot_branches_off_and_reports_every_branch(engine):
    p = engine.store.create("Variants", template="demo")

    def script(text, ctx):
        yield Turn("", [call("code_write_module", module="params", code="T = 10\n")], "tool")
        yield Turn("", [call("project_commit", message="params")], "tool")
        out = yield Turn("", [call("project_create_branch", name="lighter")], "tool")
        assert not out[0].is_error, out[0].text
        yield Turn("", [call("geometry_patch_part", part="plate", find="PLATE_T = 10", replace="PLATE_T = 6")], "tool")
        yield Turn("Made a lighter variant too.", [], "end")  # uncommitted work is committed for it
    engine.bot.script = script
    try:
        t = await engine.bot.wait(engine.bot.start_change(p.id, "thinner plate").id)
    finally:
        engine.bot.script = None
    assert t.status == "done", t.problem
    assert t.branch.startswith("bot/lighter") and len(t.branches) == 2
    assert "PLATE_T = 6" in p.read("parts/plate.py", t.branch)
    msgs = engine.bot.chat(p.id)
    assert msgs[0]["who"] == "you" and msgs[0]["task"] == t.id
    assert "I also tried bot/thinner-plate" in msgs[-1]["text"] and msgs[-1]["task"] == t.id


async def test_trace_shows_reasoning_text_and_tool_calls(engine):
    p = engine.store.create("Trace", template="demo")

    def script(text, ctx):
        yield Turn("Reading the plate first.", [call("code_read_file", path="parts/plate.py")], "tool", thinking="The plate is the base part.")
        yield Turn("", [call("geometry_patch_part", part="plate", find="nope", replace="x")], "tool")
        yield Turn("Nothing to change.", [], "end")
    engine.bot.script = script
    try:
        t = await engine.bot.wait(engine.bot.start_change(p.id, "look at the plate").id)
    finally:
        engine.bot.script = None
    kinds = [e["kind"] for e in t.trace]
    assert kinds == ["thinking", "text", "tool", "tool"], kinds
    assert t.trace[0]["text"] == "The plate is the base part."
    assert t.trace[2]["tool"] == "code_read_file" and t.trace[2]["status"] == "ok" and "Box(" in t.trace[2]["result"]
    assert t.trace[3]["status"] == "error"
    reply = engine.bot.chat(p.id)[-1]
    assert reply["task"] == t.id and [e["kind"] for e in reply["trace"]] == kinds and reply["status"] == "done"


async def test_stop_interrupts_a_slow_model_call(engine):
    import asyncio
    p = engine.store.create("Slow", template="demo")
    started = asyncio.Event()

    class Slow:
        async def send_user(self, text):
            return Turn("", [call("geometry_patch_part", part="plate", find="Box(220", replace="Box(200")], "tool")

        async def send_tool_results(self, outputs):
            started.set()
            await asyncio.sleep(60)  # a local model thinking for a long time
            return Turn("late", [], "end")
    engine.bot._conv_factory = lambda pid, system: (lambda specs: Slow())
    try:
        t = engine.bot.start_change(p.id, "shorter plate")
        await asyncio.wait_for(started.wait(), 10)
        engine.bot.stop(t.id)
        t = await engine.bot.wait(t.id, timeout=10)
    finally:
        del engine.bot._conv_factory
    assert t.status == "stopped" and t.problem == "Stopped by you"
    assert t.branch and "Box(200" in p.read("parts/plate.py", t.branch)  # the work so far is kept on its branch


async def test_reasoning_is_split_from_openai_compatible_replies():
    from newcad_engine.agent.adapters.openai_adapter import split_reasoning
    assert split_reasoning(NS(content="<think>plan it</think>Done.")) == ("Done.", "plan it")
    assert split_reasoning(NS(content="Done.", reasoning_content="from the field")) == ("Done.", "from the field")
    assert split_reasoning(NS(content="Plain")) == ("Plain", "")


async def test_apply_bot_branch_by_merge(engine):
    p = engine.store.create("Apply", template="demo")
    t = await engine.bot.wait(engine.bot.start_change(p.id, "make a bracket").id)
    assert t.commits
    p.merge(t.branch)
    assert "parts/bracket.py" in p.files("main")


async def test_interview_step_picks_an_open_question(engine):
    p = engine.store.create("Interview", "A hook")
    r = await engine.bot.interview_step(p.id)
    assert r["question_id"] == "function-1" and not r["done"]


async def test_not_ready_without_a_key(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = resolve({"provider": "anthropic"}, {})
    assert not r["ready"] and "ANTHROPIC_API_KEY" in r["problem"] and r["model"] == "claude-opus-5-5"
    assert resolve({"provider": "anthropic"}, {"anthropic": "sk-test"})["ready"]
    assert not resolve({"provider": "openai-compatible"}, {})["ready"]
    assert resolve({"provider": "openai-compatible", "base_url": "http://localhost:1234/v1", "model": "qwen"}, {})["ready"]
    p = engine.store.create("No key")
    engine.settings.update({"provider": "anthropic"})
    try:
        with pytest.raises(StoreError, match="ANTHROPIC_API_KEY"):
            engine.bot.start_change(p.id, "hi")
    finally:
        engine.settings.update({"provider": "scripted"})


# ---------- adapters against fake SDK clients ----------

TOOLS = [ToolSpec("view_snapshot", "Render", {"type": "object", "properties": {"view": {"type": "string"}}})]


class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def a_resp(content, stop="tool_use"):
    return NS(content=content, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))


async def test_anthropic_adapter_request_shape_and_tool_round_trip():
    tool_use = NS(type="tool_use", id="tu_1", name="view_snapshot", input={"view": "iso"})
    thinking = NS(type="thinking", thinking="Check the view first.", signature="sig")
    fake = FakeAnthropic([a_resp([thinking, tool_use]), a_resp([NS(type="text", text="Looks good.")], "end_turn")])
    conv = AnthropicConversation("sys", TOOLS, "", {"client": fake, "effort": "high"})
    t = await conv.send_user("Build it")
    assert t.stop == "tool" and t.calls == [ToolCall("tu_1", "view_snapshot", {"view": "iso"})]
    assert t.thinking == "Check the view first."
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "high"}
    assert first["betas"] == ["server-side-fallback-2026-07-01"] and first["fallbacks"] == "default"
    assert first["tools"][0]["input_schema"]["properties"]["view"]["type"] == "string"
    assert first["thinking"] == {"type": "adaptive", "display": "summarized"} and "temperature" not in first
    t = await conv.send_tool_results([ToolOutput("tu_1", "iso view", [b"\x89PNG fake"])])
    assert t.stop == "end" and t.text == "Looks good."
    msgs = fake.calls[1]["messages"]
    assert msgs[1]["content"][0] is thinking  # thinking blocks go back unchanged
    result = msgs[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1"
    assert result["content"][1]["type"] == "image" and result["content"][1]["source"]["media_type"] == "image/png"


async def test_anthropic_adapter_reports_refusal():
    fake = FakeAnthropic([NS(content=[], stop_reason="refusal", stop_details=NS(category="cyber"), usage=NS(input_tokens=1, output_tokens=0))])
    conv = AnthropicConversation("sys", TOOLS, "claude-opus-5-5", {"client": fake})
    t = await conv.send_user("x")
    assert t.stop == "refusal" and t.detail == "cyber"


async def test_anthropic_adapter_without_fallbacks_on_custom_base_url():
    fake = FakeAnthropic([a_resp([NS(type="text", text="hi")], "end_turn")])
    conv = AnthropicConversation("sys", TOOLS, "", {"client": fake, "base_url": "https://gateway.example"})
    await conv.send_user("x")
    assert "fallbacks" not in fake.calls[0]


class FakeOpenAI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


def o_resp(content, tool_calls=None, finish="stop"):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls), finish_reason=finish)], usage=NS(prompt_tokens=7, completion_tokens=3))


async def test_openai_compatible_adapter_round_trip_with_images_as_user_message():
    tc = NS(id="c1", type="function", function=NS(name="view_snapshot", arguments='{"view": "top"}'))
    fake = FakeOpenAI([o_resp(None, [tc], "tool_calls"), o_resp("Done")])
    conv = OpenAIConversation("sys", TOOLS, "qwen3", {"client": fake, "base_url": "http://localhost:1234/v1"})
    t = await conv.send_user("go")
    assert t.calls == [ToolCall("c1", "view_snapshot", {"view": "top"})]
    assert fake.calls[0]["tools"][0]["function"]["name"] == "view_snapshot"
    assert fake.calls[0]["messages"][0] == {"role": "system", "content": "sys"}
    t = await conv.send_tool_results([ToolOutput("c1", "ok", [b"png"])])
    assert t.text == "Done"
    m = fake.calls[1]["messages"]
    assert m[2]["tool_calls"][0]["id"] == "c1" and m[3]["role"] == "tool" and m[3]["tool_call_id"] == "c1"
    assert m[4]["role"] == "user" and m[4]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
