from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.context_category import Category


class OutcomeCreate(BaseModel):
    actual_outcome: str = Field(min_length=1, max_length=20000)
    lessons: str | None = Field(default=None, max_length=10000)
    next_action: str | None = Field(default=None, max_length=10000)


class OutcomeItem(OutcomeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    decision_id: int
    expected_outcome: str | None
    context_snapshot_id: str | None
    reviewed_at: datetime | None


class PeriodReviewCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    period: Literal["month", "quarter", "year"]
    start_on: date
    end_on: date
    goal_ids: list[int] = Field(default_factory=list, max_length=50)
    project_ids: list[int] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_range(self):
        if not 0 < (self.end_on - self.start_on).days <= 366:
            raise ValueError("기간은 시작일 포함, 종료일 제외이며 최대 366일입니다")
        return self


class PeriodReviewItem(PeriodReviewCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    content: str
    evidence: dict
    created_at: datetime
    confirmed_at: datetime | None


class ReviewConfirm(BaseModel):
    content: str = Field(min_length=1, max_length=50000)


class ReviewJobCreate(PeriodReviewCreate):
    enabled: bool = False
    run_after: datetime | None = None


class JobItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: str
    kind: str
    enabled: bool
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None
    result: dict | None
    created_at: datetime
    completed_at: datetime | None


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cadence: Literal["month", "quarter", "year"]
    enabled: bool = False


class ScheduleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str = "period_review"
    cadence: str
    enabled: bool
    local_time: str | None = None
    options: dict = Field(default_factory=dict)
    paused_reason: str | None = None
    next_run_at: datetime
    created_at: datetime
    # Whether model use is pinned to the connection that was current when it was enabled.
    model_authorized: bool = False

    @model_validator(mode="before")
    @classmethod
    def authority_flag(cls, value):
        if hasattr(value, "authorization"):
            return {**{key: getattr(value, key) for key in ("id", "name", "kind", "cadence", "enabled", "local_time",
                    "options", "paused_reason", "next_run_at", "created_at")},
                    "options": {k: v for k, v in (value.options or {}).items() if k != "model"},
                    "model_authorized": bool(value.authorization)}
        return value


class BriefingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["daily_briefing", "weekly_briefing"] = "daily_briefing"
    local_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    # Model use is explicit; without it a briefing only refreshes local inbox signals.
    llm_enabled: bool = False
    categories: list[Category] = Field(default_factory=list)
    playbook_ids: list[int] = Field(default_factory=list, max_length=2)
    enabled: bool = False

    @model_validator(mode="after")
    def weekly_day(self):
        if self.kind == "weekly_briefing" and self.weekday is None:
            raise ValueError("주간 브리핑은 요일을 선택해야 합니다")
        return self


class RunNow(BaseModel):
    request_id: str = Field(min_length=1, max_length=60)


class ScheduleActivation(BaseModel):
    enabled: bool


class QuoteRefreshConsent(BaseModel):
    enabled: bool = False
