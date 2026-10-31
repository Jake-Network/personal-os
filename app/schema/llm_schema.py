from pydantic import BaseModel


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


class ConnectionTestResult(BaseModel):
    ok: bool
    code: str
    message: str
    provider: str | None = None
    model: str | None = None
