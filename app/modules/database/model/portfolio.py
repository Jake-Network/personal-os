"""Immutable Sheets imports and monthly valuation revisions.

Financial JSON uses canonical Decimal strings, avoiding floating point storage.
"""
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class PortfolioSettings(Base):
    __tablename__ = "portfolio_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    verification: Mapped[dict | None] = mapped_column(JSON)
    verified_identity: Mapped[str | None] = mapped_column(String(500))
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)


class PortfolioImport(Base):
    __tablename__ = "portfolio_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source_identity: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict] = mapped_column(JSON)


class MonthlySnapshot(Base):
    __tablename__ = "monthly_snapshots"
    __table_args__ = (UniqueConstraint("month", "revision", name="uq_snapshot_month_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    revision: Mapped[int] = mapped_column()
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("monthly_snapshots.id"))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_imports.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)


@event.listens_for(MonthlySnapshot, "before_update")
@event.listens_for(MonthlySnapshot, "before_delete")
def reject_snapshot_mutation(mapper, connection, target):
    raise ValueError("Monthly snapshots are append-only; create a correction revision")
