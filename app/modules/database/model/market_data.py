"""Local position identities and append-only public market observations."""

from datetime import datetime
from sqlalchemy import ForeignKey, JSON, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column
from app.modules.database.model.base import Base, UTCDateTime, utcnow


class LocalPosition(Base):
    __tablename__ = "local_positions"
    position_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), unique=True
    )
    quote_mode: Mapped[str] = mapped_column(String(16), default="auto")
    version: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str | None] = mapped_column(String(300), unique=True)


class MarketSettings(Base):
    __tablename__ = "market_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    source_identity: Mapped[str] = mapped_column(String(500))
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)


class MarketObservation(Base):
    __tablename__ = "market_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(80), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)


@event.listens_for(MarketObservation, "before_update")
@event.listens_for(MarketObservation, "before_delete")
def immutable(mapper, connection, target):
    raise ValueError("Market observations are append-only")


class FinancialTransaction(Base):
    __tablename__ = "financial_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), unique=True)
    reverses_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_transactions.id"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(24), index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)


@event.listens_for(FinancialTransaction, "before_update")
@event.listens_for(FinancialTransaction, "before_delete")
def immutable_transaction(mapper, connection, target):
    raise ValueError("Financial transactions are append-only; append a reversal")


class FinanceImportMapping(Base):
    __tablename__ = "finance_import_mappings"
    source_ref: Mapped[str] = mapped_column(String(500), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[int] = mapped_column()
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LocalFinanceCoverage(Base):
    __tablename__ = "local_finance_coverage"
    id: Mapped[int] = mapped_column(primary_key=True)
    kinds: Mapped[list] = mapped_column(JSON)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class HoldingWriteReceipt(Base):
    __tablename__ = "holding_write_receipts"
    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
