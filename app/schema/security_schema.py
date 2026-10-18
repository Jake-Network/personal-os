from typing import Literal
from pydantic import BaseModel, Field


class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class SecurityStatus(BaseModel):
    configured: bool
    authenticated: bool
    locked: bool
    csrf_token: str | None
    idle_timeout_seconds: int
    storage_encryption: Literal["unverified"] = "unverified"
    firewall: Literal["unverified"] = "unverified"
