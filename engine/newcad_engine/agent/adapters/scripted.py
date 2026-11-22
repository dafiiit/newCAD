"""A scripted stand-in for a language model, for tests and offline UI checks.

The script is a generator: it receives the first user message, yields Turns,
and receives the tool outputs of each Turn back through `send`. No network.
It is only selectable when NEWCAD_ALLOW_SCRIPTED=1 is set.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Generator

from .base import Conversation, ToolCall, ToolOutput, ToolSpec, Turn

Script = Callable[[str, dict[str, Any]], Generator[Turn, list[ToolOutput], None]]


class ScriptedConversation(Conversation):
    def __init__(self, system: str, tools: list[ToolSpec], model: str, options: dict[str, Any]):
        super().__init__(system, tools, model or "scripted", options)
        self.script: Script = options.get("script") or demo_script
        self.gen: Generator[Turn, list[ToolOutput], None] | None = None
        self.seen: list[list[ToolOutput]] = []

    async def send_user(self, text: str) -> Turn:
        self.gen = self.script(text, {"system": self.system, "tools": [t.name for t in self.tools]})
        return self._next(None)

    async def send_tool_results(self, outputs: list[ToolOutput]) -> Turn:
        self.seen.append(outputs)
        return self._next(outputs)

    def _next(self, outputs: list[ToolOutput] | None) -> Turn:
        assert self.gen is not None
        try:
            t = next(self.gen) if outputs is None else self.gen.send(outputs)
        except StopIteration:
            return Turn("Done.", [], "end")
        t.input_tokens = t.input_tokens or 100
        t.output_tokens = t.output_tokens or 50
        return t


_n = 0


def call(tool_name: str, **args: Any) -> ToolCall:
    global _n
    _n += 1
    return ToolCall(f"call_{_n}", tool_name, args)


BRACKET = '''# {label}: L-bracket, plate {t} mm, upright {t2} mm{extra_doc}
T, T2 = {t}, {t2}

with BuildPart() as bracket:
    Box(120, 80, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((-60 + T2 / 2, 0, T)):
        Box(T2, 80, 90, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*[(x, y, T) for x in (-20, 40) for y in (-25, 25)]):
        Hole(radius=3.3)
{ribs}
result = bracket.part
'''

RIBS = '''    for y in (-30, 30):
        with BuildSketch(Plane.XZ.offset(-y - {r} / 2)):
            Polygon((-60 + T2, T), (-60 + T2 + {h}, T), (-60 + T2, T + {h}), align=None)
        extrude(amount={r})
'''


def demo_script(text: str, ctx: dict[str, Any]) -> Generator[Turn, list[ToolOutput], None]:
    """Answers like a very small BuilderBot, depending on the task mode in the prompt."""
    tools = ctx["tools"]
    if "ask_user" in tools:  # interview step
        out = yield Turn("", [call("spec_open_questions")], "tool")
        ids = re.findall(r'"id": "([^"]+)"', out[0].text)
        if not ids:
            yield Turn("", [call("ask_user", question_id="", message="That was the last open question. I have what I need to build.")], "tool")
            return
        calls = [call("ask_user", question_id=ids[0], message="Next one for you.")]
        yield Turn("", calls, "tool")
        return
    m = re.search(r"Concept ([A-C])", text)
    label = f"Concept {m.group(1)}" if m else "Draft"
    variant = {"A": (10, 10, None), "B": (8, 8, (6, 50)), "C": (5, 6, (4, 40))}.get(m.group(1) if m else "B", (8, 8, (6, 50)))
    t, t2, rib = variant
    ribs = RIBS.format(r=rib[0], h=rib[1]) if rib else ""
    code = BRACKET.format(label=label, t=t, t2=t2, ribs=ribs, extra_doc=", ribs" if rib else "")
    yield Turn("Reading the spec.", [call("spec_read")], "tool")
    out = yield Turn(f"Writing the {label.lower()}.", [call("geometry_write_part", part="bracket", code=code, name="Bracket", material="Aluminium", color="#B4C2D6")], "tool")
    out = yield Turn("", [call("geometry_rebuild")], "tool")
    ok = "FAILED" not in out[0].text
    yield Turn("", [call("project_commit", message=f"{label}: bracket {t}/{t2} mm" + (" with ribs" if rib else ""))], "tool")
    yield Turn(f"{label} is built ({'it rebuilds cleanly' if ok else 'with build errors'}).", [], "end")
