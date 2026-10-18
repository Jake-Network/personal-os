from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ScheduleItem(ScheduleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    next_run_at: datetime
    created_at: datetime


class ScheduleActivation(BaseModel):
    enabled: bool


class QuoteRefreshConsent(BaseModel):
    enabled: bool = False
