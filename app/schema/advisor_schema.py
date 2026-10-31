from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums.context_category import Category
from app.modules.advisor.types import AskOptions


### Conversation


class ConversationCreate(BaseModel):
    title: str = "새 상담"
    domain: Literal["financial", "investment", "career", "calendar", "health"] | None = None


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    domain: str | None
    origin: str = "user"  # user | schedule (a briefing run in its own conversation)
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
    is_final_answer: bool = False
    source_question: str | None = None
    data_operations: list[dict] = Field(default_factory=list)
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
    web_search: bool = False
    web_query: str | None = Field(default=None, min_length=1, max_length=300)
    allow_data_recording: bool = False
    playbook_ids: list[int] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def public_web_query(self):
        if self.web_search and (not self.web_query or not self.web_query.strip()):
            raise ValueError('웹 검색을 켜려면 외부에 전송할 공개 검색어를 입력하세요.')
        return self

    history_since: AwareDatetime | None = None
    history_until: AwareDatetime | None = None
    history_company: str | None = Field(default=None, max_length=200)
    history_project: int | None = None
    history_decision: int | None = None

    def options(self) -> AskOptions:
        from app.modules.playbooks.selection import explicit_slug
        slug = explicit_slug(self.message)
        return AskOptions(
            playbook_ids=tuple(self.playbook_ids), playbook_slugs=(slug,) if slug else (),
            categories=frozenset(self.categories) if self.categories is not None else None,
            exclude=frozenset(self.exclude),
            document_search=self.document_search,
            web_search=self.web_search, web_query=self.web_query,
            allow_data_recording=self.allow_data_recording,
            document_ids=tuple(self.document_ids) if self.document_ids is not None else None,
            history_since=self.history_since, history_until=self.history_until,
            history_company=self.history_company, history_project=self.history_project, history_decision=self.history_decision,
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
    source_message_id: int | None = None
    title: str = Field(max_length=200)
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

    source_message_id: int | None
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
    summary: str | None = None
    user_rating: Literal[-1, 0, 1] | None = None
    user_feedback: str | None = Field(default=None, max_length=1000)


class RecommendationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    summary: str
    user_rating: int | None
    user_feedback: str | None
    created_at: datetime


class MemoryRevisionCreate(MemoryCreate):
    # Required optimistic version protects concurrent corrections from overwriting each other.
    expected_revision: int = Field(ge=0)
    scope: str | None = Field(default=None, max_length=200)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    review_on: datetime | None = None
    external_allowed: bool = True
    source_references: list[dict] = Field(default_factory=list, max_length=30)

    @field_validator("source_references")
    @classmethod
    def validate_sources(cls, value):
        for ref in value:
            if not isinstance(ref.get("table"), str) or type(ref.get("id")) not in {int, str}:
                raise ValueError("each source requires a table and integer/string id")
            if len(ref["table"]) > 100 or isinstance(ref["id"], str) and len(ref["id"]) > 200:
                raise ValueError("invalid source identifier")
        return value


class MemoryRevisionItem(MemoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    memory_id: int
    revision: int
    status: str
    scope: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    review_on: datetime | None
    external_allowed: bool
    source_references: list[dict]
    created_at: datetime
    confirmed_at: datetime | None


class SummaryCreate(BaseModel):
    first_message_id: int | None = None
    last_message_id: int | None = None


class SummaryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    first_message_id: int
    last_message_id: int
    content: str
    status: str
    source_references: list[dict]
    generator: str
    created_at: datetime


class ConversationLinkCreate(BaseModel):
    kind: Literal["company", "project", "decision"]
    target: str = Field(min_length=1, max_length=200)


class ConversationLinkItem(ConversationLinkCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int


class DataOperationUndo(BaseModel):
    receipt_id: int
    operation: str
    resource: str
    record_id: int
