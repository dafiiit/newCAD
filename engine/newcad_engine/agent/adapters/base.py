"""Provider-neutral interface for the BuilderBot tool-calling loop.

Each adapter keeps the conversation in its provider's own format (so
provider-specific blocks such as Claude's thinking blocks go back unchanged)
and exposes the same three calls to the runtime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolOutput:
    call_id: str
    text: str
    images: list[bytes] = field(default_factory=list)  # PNG bytes
    is_error: bool = False


Stop = Literal["end", "tool", "refusal", "max_tokens", "error"]


@dataclass
class Turn:
    text: str
    calls: list[ToolCall]
    stop: Stop
    input_tokens: int = 0
    output_tokens: int = 0
    detail: str = ""  # refusal category or error text
    thinking: str = ""  # the model's reasoning, when the provider returns it (shown to the user as a trace)


class AdapterError(Exception):
    """Configuration or provider failure with a message meant for the user."""


class Conversation(ABC):
    def __init__(self, system: str, tools: list[ToolSpec], model: str, options: dict[str, Any]):
        self.system = system
        self.tools = tools
        self.model = model
        self.options = options

    @abstractmethod
    async def send_user(self, text: str) -> Turn: ...

    @abstractmethod
    async def send_tool_results(self, outputs: list[ToolOutput]) -> Turn: ...
