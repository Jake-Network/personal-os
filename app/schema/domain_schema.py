"""Input/output schemas for the personal data the advisor reads."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.modules.finance.formatting import quantity_text


class _Item(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int


### Financial


class AccountCreate(BaseModel):
    name: str
    institution: str | None = None
    kind: Literal["checking", "savings", "deposit", "brokerage_cash", "cash", "pension", "other"]
    currency: str = Field("KRW", min_length=3, max_length=3)
    balance: Decimal
    balance_as_of: date
    is_liquid: bool = True


class AccountItem(_Item, AccountCreate):
    pass


class OtherAssetCreate(BaseModel):
    name: str
    kind: Literal["real_estate", "vehicle", "severance_estimate", "other"]
    currency: str = Field("KRW", min_length=3, max_length=3)
    value: Decimal
    value_as_of: date
    is_liquid: bool = False


class OtherAssetItem(_Item, OtherAssetCreate):
    pass


class LiabilityCreate(BaseModel):
    name: str
    kind: Literal["mortgage", "jeonse_loan", "credit", "card", "other"]
    currency: str = Field("KRW", min_length=3, max_length=3)
    balance: Decimal
    interest_rate: Decimal | None = None
    monthly_payment: Decimal | None = None
    balance_as_of: date


class LiabilityItem(_Item, LiabilityCreate):
    pass


class HoldingCreate(BaseModel):
    account_id: int | None = None
    symbol: str
    name: str | None = None
    market: str | None = None
    asset_class: Literal["equity", "etf", "bond", "crypto", "other"] = "equity"
    currency: str = Field("KRW", min_length=3, max_length=3)
    quantity: int = Field(ge=0, lt=10**20)
    avg_cost: Decimal | None = None
    last_price: Decimal | None = None
    price_as_of: datetime | None = None
    # Not stored on holdings (the schema stays as-is): it only dates this edit in the value history.
    trade_date: date | None = Field(None, description="Trade date of this quantity / average-cost change")


class HoldingItem(_Item, HoldingCreate):
    # Read existing fractional records without rounding or rewriting their evidence.
    quantity: Decimal

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal):
        return quantity_text(value)


class ValueChangeItem(BaseModel):
    """One append-only manual edit. Differences between rows are edits, not realized returns."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    record_id: int
    field: str
    old_value: Decimal | None
    new_value: Decimal | None
    currency: str
    as_of: date
    change_kind: str
    recorded_at: datetime


class FxRateCreate(BaseModel):
    base: str = Field(min_length=3, max_length=3)
    quote: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    as_of: datetime


class FxRateItem(_Item, FxRateCreate):
    pass


class CashflowEntryCreate(BaseModel):
    occurred_on: date
    kind: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field("KRW", min_length=3, max_length=3)
    category: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=200)


class CashflowEntryItem(_Item, CashflowEntryCreate):
    pass


class PlannedExpenseCreate(BaseModel):
    name: str
    amount: Decimal = Field(gt=0)
    currency: str = Field("KRW", min_length=3, max_length=3)
    due_on: date


class PlannedExpenseItem(_Item, PlannedExpenseCreate):
    pass


### Career


class JobApplicationCreate(BaseModel):
    company: str
    role: str
    status: Literal["interested", "applied", "screening", "interviewing", "offer", "rejected", "withdrawn"]
    applied_on: date | None = None
    jd_text: str | None = None
    compensation_note: str | None = None
    next_step: str | None = None
    notes: str | None = None


class JobApplicationItem(_Item, JobApplicationCreate):
    pass


class InterviewCreate(BaseModel):
    application_id: int
    stage: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = None
    prep_notes: str | None = None


class InterviewItem(_Item, InterviewCreate):
    pass


class CareerCriterionCreate(BaseModel):
    name: str
    weight: int = Field(1, ge=1, le=10)
    description: str | None = None


class CareerCriterionItem(_Item, CareerCriterionCreate):
    pass


### Planning / health


class CalendarEventCreate(BaseModel):
    title: str
    kind: Literal["personal", "work", "interview", "workout", "deadline"] = "personal"
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    location: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _all_day_needs_end(self):
        if self.all_day and (self.ends_at is None or self.ends_at <= self.starts_at):
            raise ValueError("종일 일정에는 시작보다 늦은 종료 시각이 필요합니다")
        return self


class CalendarEventItem(_Item, CalendarEventCreate):
    pass


class GoalCreate(BaseModel):
    title: str
    category: Literal["financial", "career", "health", "personal"]
    horizon: Literal["short", "long"] = "short"
    target_value: str | None = None
    current_value: str | None = None
    unit: str | None = None
    target_date: date | None = None
    status: Literal["active", "done", "dropped"] = "active"


class GoalItem(_Item, GoalCreate):
    pass


class TaskCreate(BaseModel):
    title: str
    status: Literal["todo", "doing", "done"] = "todo"
    priority: Literal["low", "normal", "high"] = "normal"
    due_on: date | None = None
    estimate_minutes: int | None = None
    goal_id: int | None = None


class TaskItem(_Item, TaskCreate):
    pass


class WorkoutLogCreate(BaseModel):
    performed_on: date
    activity: str
    duration_minutes: int = Field(gt=0)
    intensity: Literal["easy", "moderate", "hard"] | None = None
    notes: str | None = None


class WorkoutLogItem(_Item, WorkoutLogCreate):
    pass
