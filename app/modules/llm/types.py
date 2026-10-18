"""Types passed between the LLM gateway and its providers."""

from dataclasses import dataclass, field


@dataclass
class LLMRequest:
    """One provider call: model, system instructions and the input messages."""

    model: str
    instructions: str
    input: list[dict]


@dataclass
class StreamEvent:
    """One event of a streamed provider response."""

    type: str  # delta | completed
    text: str = ""
    usage: dict = field(default_factory=dict)
