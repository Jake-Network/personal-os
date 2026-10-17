from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class PendingLogin:
    verifier: str
    nonce: str
    client_id: str
    created: float


class LoginStartResponse(BaseModel):
    authorize_url: str


class AIProviderStatus(BaseModel):
    connected: bool
    status: str | None = None
    email: str | None = None
    display_name: str | None = None
    plan_usage_enabled: bool = False
    scopes: list[str] = []
    access_expires_at: str | None = None
    last_error_code: str | None = None
    provider: str
    model: str | None = None
    usage_url: str
