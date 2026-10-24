"""Deciding several pending items in one explicit user action."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ApprovalKind = Literal["action", "memory", "playbook"]


class ApprovalDecision(BaseModel):
    kind: ApprovalKind
    id: int = Field(gt=0)
    decision: Literal["approve", "reject"]


class ApprovalBatch(BaseModel):
    # Each item is a choice the user made on screen; nothing here selects items on their behalf.
    items: list[ApprovalDecision] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def distinct(self):
        keys = [(item.kind, item.id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("같은 항목을 한 번에 두 번 처리할 수 없습니다")
        return self


class ApprovalOutcome(BaseModel):
    kind: ApprovalKind
    id: int
    decision: Literal["approve", "reject"]
    ok: bool
    error: str | None = None


class ApprovalBatchResult(BaseModel):
    results: list[ApprovalOutcome]
    succeeded: int
    failed: int
