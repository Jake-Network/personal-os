from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.context_category import Category


@dataclass
class AskOptions:
    categories: frozenset[Category] | None = None  # Context Inspector override
    exclude: frozenset[Category] = frozenset()  # per-request exclusions, on top of saved settings
    document_search: bool = True
    document_ids: tuple[int, ...] | None = None  # None inherits; empty clears pins


### Conversation


class ConversationCreate(BaseModel):
    title: str = "새 상담"
    domain: Literal["financial", "investment", "career", "calendar", "health"] | None = None


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    domain: str | None
    created_at: datetime
    updated_at: datetime


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    status: str
    context_snapshot_id: str | None
    model: str | None
    created_at: datetime


class ConversationDetail(ConversationItem):
    messages: list[MessageItem]


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Context Inspector: override auto-routing and/or block categories for this request only.
    categories: list[Category] | None = None
    exclude: list[Category] = []
    document_search: bool = True
    document_ids: list[int] | None = Field(default=None, max_length=5)

    def options(self) -> AskOptions:
        return AskOptions(
            categories=frozenset(self.categories) if self.categories is not None else None,
            exclude=frozenset(self.exclude),
            document_search=self.document_search,
            document_ids=tuple(self.document_ids) if self.document_ids is not None else None,
        )


class ContextPreviewRequest(AskRequest):
    conversation_id: int | None = None


### Proposals / memory / decisions


class ProposalItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    payload: dict
    rationale: str | None
    status: str
    conversation_id: int | None
    created_at: datetime
    result_ref: dict | None


class MemoryCreate(BaseModel):
    kind: Literal["profile", "preference", "constraint", "priority"]
    content: str = Field(min_length=1, max_length=1000)


class MemoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    content: str
    status: str
    source: str
    created_at: datetime
    confirmed_at: datetime | None


class DecisionCreate(BaseModel):
    title: str
    choice: str
    rationale: str
    alternatives: list[str] = []
    expected_outcome: str | None = None
    context_snapshot_id: str | None = None
    conversation_id: int | None = None
    review_on: datetime | None = None


class DecisionReview(BaseModel):
    actual_outcome: str


class DecisionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    decided_at: datetime
    context_snapshot_id: str | None
    conversation_id: int | None
    alternatives: list[str]
    choice: str
    rationale: str
    expected_outcome: str | None
    review_on: datetime | None
    actual_outcome: str | None
    reviewed_at: datetime | None


class RecommendationFeedback(BaseModel):
    message_id: int
    summary: str
    user_rating: Literal[-1, 0, 1] | None = None
    user_feedback: str | None = None
