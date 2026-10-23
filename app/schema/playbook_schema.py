"""Playbook, inbox and agent setting contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.context_category import Category


class PlaybookContent(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=300)
    triggers: list[str] = Field(default_factory=list, max_length=12)
    categories: list[Category] = Field(default_factory=list)
    body: str = Field(min_length=1, max_length=8000)


class PlaybookCreate(PlaybookContent):
    slug: str = Field(min_length=2, max_length=40)


class PlaybookRevise(PlaybookContent):
    # Optimistic check: an edit based on an outdated revision is refused, not merged.
    base_revision_id: int


class PlaybookSharing(BaseModel):
    external_allowed: bool


class PlaybookRevisionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    playbook_id: int
    revision: int
    title: str
    summary: str
    triggers: list[str]
    categories: list[str]
    body: str
    status: str
    base_revision_id: int | None
    source: str
    rationale: str | None
    warnings: list[str]
    source_references: list[dict]
    proposed_by_job_id: int | None
    source_purged: bool
    created_at: datetime
    decided_at: datetime | None
    # True when the revision it patches is no longer the approved one.
    stale: bool = False


class PlaybookItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    status: str
    source: str
    external_allowed: bool
    created_at: datetime
    updated_at: datetime
    active_revision: PlaybookRevisionItem | None = None
    pending_count: int = 0
    usage_count: int = 0


class PlaybookDetail(PlaybookItem):
    revisions: list[PlaybookRevisionItem] = Field(default_factory=list)


class PlaybookDiff(BaseModel):
    revision_id: int
    base_revision_id: int | None
    diff: str


class InboxItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    summary: str
    severity: str
    links: dict
    status: str
    created_at: datetime
    read_at: datetime | None


class InboxCount(BaseModel):
    unread: int


class AdvisorStyle(BaseModel):
    tone: Literal["direct", "balanced", "gentle"] = "balanced"
    answer_first: bool = True
    detail: Literal["brief", "normal", "thorough"] = "normal"
    custom: str = Field(default="", max_length=500)


class LearningSettings(BaseModel):
    # Automatic reflection after qualifying consultations and decision reviews. Manual
    # "learn from this consultation" requests work regardless; both use the model.
    enabled: bool = False


class AgentSettings(BaseModel):
    learning: LearningSettings = Field(default_factory=LearningSettings)
    style: AdvisorStyle = Field(default_factory=AdvisorStyle)


class AgentSettingsView(AgentSettings):
    style_warnings: list[str] = Field(default_factory=list)


class ReflectRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)


class AgentActivity(BaseModel):
    days: int
    model_calls: int
    failed_calls: int
    input_tokens: int | None
    output_tokens: int | None
    playbook_uses: int
    learning_proposals: int
    learning_approved: int
    learning_rejected: int
    by_outcome: dict[str, int]
