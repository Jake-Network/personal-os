"""Personal data domains the advisor reads from (v0.1 foundation, minimal subset).

Money and quantities are Decimal. Account numbers and credentials are intentionally
not modelled: nothing that must never reach an LLM is stored here in the first place.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow

Money = Numeric(20, 4)
Qty = Numeric(24, 8)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # checking | savings | deposit | brokerage_cash | cash | pension | other
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    balance: Mapped[Decimal] = mapped_column(Money)
    balance_as_of: Mapped[date] = mapped_column(Date)
    is_liquid: Mapped[bool] = mapped_column(Boolean, default=True)


class OtherAsset(TimestampMixin, Base):
    __tablename__ = "other_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # real_estate | vehicle | severance_estimate | other
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    value: Mapped[Decimal] = mapped_column(Money)
    value_as_of: Mapped[date] = mapped_column(Date)
    is_liquid: Mapped[bool] = mapped_column(Boolean, default=False)


class Liability(TimestampMixin, Base):
    __tablename__ = "liabilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # mortgage | jeonse_loan | credit | card | other
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    balance: Mapped[Decimal] = mapped_column(Money)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    monthly_payment: Mapped[Decimal | None] = mapped_column(Money)
    balance_as_of: Mapped[date] = mapped_column(Date)


class Holding(TimestampMixin, Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    symbol: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(120))
    market: Mapped[str | None] = mapped_column(String(16))
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")  # equity | etf | bond | crypto | other
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    quantity: Mapped[Decimal] = mapped_column(Qty)
    avg_cost: Mapped[Decimal | None] = mapped_column(Money)
    last_price: Mapped[Decimal | None] = mapped_column(Money)
    price_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime())


class FxRate(Base):
    __tablename__ = "fx_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    base: Mapped[str] = mapped_column(String(3))  # 1 base = rate quote
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    as_of: Mapped[datetime] = mapped_column(UTCDateTime())


class CashflowEntry(TimestampMixin, Base):
    __tablename__ = "cashflow_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))  # income | expense
    amount: Mapped[Decimal] = mapped_column(Money)  # always positive; kind decides direction
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    category: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(200))


class PlannedExpense(TimestampMixin, Base):
    __tablename__ = "planned_expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    due_on: Mapped[date] = mapped_column(Date)


class JobApplication(TimestampMixin, Base):
    __tablename__ = "job_applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32))  # interested | applied | screening | interviewing | offer | rejected | withdrawn
    applied_on: Mapped[date | None] = mapped_column(Date)
    jd_text: Mapped[str | None] = mapped_column(Text)
    compensation_note: Mapped[str | None] = mapped_column(String(200))
    next_step: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class Interview(TimestampMixin, Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("job_applications.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    location: Mapped[str | None] = mapped_column(String(200))
    prep_notes: Mapped[str | None] = mapped_column(Text)


class CareerCriterion(TimestampMixin, Base):
    """User-defined evaluation criteria for comparing opportunities (PRD 5.2)."""

    __tablename__ = "career_criteria"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(String(300))


class CalendarEvent(TimestampMixin, Base):
    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="personal")  # personal | work | interview | workout | deadline
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32))  # financial | career | health | personal
    horizon: Mapped[str] = mapped_column(String(16), default="short")  # short | long
    target_value: Mapped[Decimal | None] = mapped_column(Money)
    current_value: Mapped[Decimal | None] = mapped_column(Money)
    unit: Mapped[str | None] = mapped_column(String(32))
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | done | dropped


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo | doing | done
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # low | normal | high
    due_on: Mapped[date | None] = mapped_column(Date)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))


class WorkoutLog(TimestampMixin, Base):
    __tablename__ = "workout_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    performed_on: Mapped[date] = mapped_column(Date)
    activity: Mapped[str] = mapped_column(String(80))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    intensity: Mapped[str | None] = mapped_column(String(16))  # easy | moderate | hard
    notes: Mapped[str | None] = mapped_column(String(300))
