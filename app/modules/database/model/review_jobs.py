"""Append-only decision outcomes, user-confirmed period reviews and durable local jobs."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class DecisionReviewRecord(Base):
    __tablename__ = "decision_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_journal.id", ondelete="CASCADE"), index=True)
    actual_outcome: Mapped[str] = mapped_column(Text)
    lessons: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=utcnow)
    # Freeze the decision's original evidence, never substitute current values.
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    context_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("context_snapshots.id", ondelete="SET NULL"))


class PeriodReview(Base):
    __tablename__ = "period_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True)
    period: Mapped[str] = mapped_column(String(16))
    start_on: Mapped[date] = mapped_column(Date)
    end_on: Mapped[date] = mapped_column(Date)  # exclusive
    status: Mapped[str] = mapped_column(String(16), default="draft")
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


    @property
    def goal_ids(self):
        return self.evidence.get("linked_goal_ids", [])

    @property
    def project_ids(self):
        return self.evidence.get("linked_project_ids", [])


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class JobSchedule(Base):
    __tablename__ = "job_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    cadence: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # period_review | daily_briefing | weekly_briefing
    kind: Mapped[str] = mapped_column(String(32), default="period_review")
    local_time: Mapped[str | None] = mapped_column(String(5))  # HH:MM in PERSONAL_OS_TIMEZONE
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    # Run authority pinned when the user enabled model use; never refreshed silently.
    authorization: Mapped[dict | None] = mapped_column(JSON)
    paused_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
