from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class LLMRequest:
    model: str
    instructions: str
    input: list[dict]


@dataclass
class StreamEvent:
    type: str  # delta | completed
    text: str = ""
    usage: dict = field(default_factory=dict)


class ProviderSelection(BaseModel):
    provider: str
    model: str | None = None


class UsageEventItem(BaseModel):
    id: int
    provider: str
    model: str | None
    outcome: str
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: str
