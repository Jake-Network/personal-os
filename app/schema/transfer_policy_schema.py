from typing import Literal

from pydantic import BaseModel


class TransferConfirmation(BaseModel):
    training_excluded: bool
    retention_understood: bool


class TransferPolicyStatus(BaseModel):
    provider: str
    account_available: bool
    confirmed: bool
    verification: Literal["user_confirmed", "unconfirmed"]
    confirmed_at: str | None
    store: bool
    retention: str
    policy_version: str
    policy_url: str
