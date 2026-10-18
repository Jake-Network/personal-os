import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CareerKind = Literal["employment", "role", "project", "contribution", "achievement", "feedback", "evidence"]


def period_bounds(value: str) -> tuple[date, date]:
    """Inclusive bounds without inventing a precise occurrence date."""
    from calendar import monthrange
    if not re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", value):
        raise ValueError("날짜는 YYYY, YYYY-MM 또는 YYYY-MM-DD로 입력하세요")
    parts = value.split("-")
    if len(parts) == 1 and len(parts[0]) == 4:
        year = int(parts[0])
        return date(year, 1, 1), date(year, 12, 31)
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
        year, month = map(int, parts)
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    if len(value) == 10:
        parsed = date.fromisoformat(value)
        return parsed, parsed
    raise ValueError("날짜는 YYYY, YYYY-MM 또는 YYYY-MM-DD로 입력하세요")


class CareerRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: CareerKind
    parent_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=120)
    organization: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=160)
    started_on: str | None = None
    ended_on: str | None = None
    description: str | None = Field(default=None, max_length=20000)
    approach: str | None = Field(default=None, max_length=20000)
    outcome: str | None = Field(default=None, max_length=20000)
    lessons: str | None = Field(default=None, max_length=20000)
    evidence_url: str | None = Field(default=None, max_length=2000)
    skills: list[str] = Field(default_factory=list, max_length=100)
    progress: Literal["planned", "active", "completed", "paused", "cancelled"] = "active"
    source: Literal["user", "document", "advisor"] = "user"
    source_message_id: int | None = Field(default=None, gt=0)
    source_document_version_id: int | None = Field(default=None, gt=0)
    share_with_advisor: bool = False

    @field_validator("started_on", "ended_on")
    @classmethod
    def valid_period(cls, value):
        if value is not None:
            period_bounds(value)
        return value

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        if not value.strip():
            raise ValueError("제목을 입력하세요")
        return value.strip()

    @field_validator("skills")
    @classmethod
    def valid_skills(cls, values):
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("역량 이름은 1~100자로 입력하세요")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("evidence_url")
    @classmethod
    def valid_url(cls, value):
        if value is not None and (urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc):
            raise ValueError("근거 URL은 http 또는 https 주소여야 합니다")
        return value

    @model_validator(mode="after")
    def valid_range(self):
        if self.started_on and self.ended_on and period_bounds(self.started_on)[0] > period_bounds(self.ended_on)[1]:
            raise ValueError("종료 시점이 시작 시점보다 빠릅니다")
        return self


class CareerRecordItem(CareerRecordCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: Literal["draft", "confirmed"]
    source_references: list[dict]
    recorded_at: datetime
    updated_at: datetime


class TimelineItem(BaseModel):
    source_kind: str
    source_id: int
    title: str
    occurred_on: str | None
    ended_on: str | None = None
    recorded_at: datetime
    company: str | None = None
    parent_id: int | None = None
    status: str | None = None
    href: str


class TimelinePage(BaseModel):
    items: list[TimelineItem]
    total: int
    offset: int
    limit: int
