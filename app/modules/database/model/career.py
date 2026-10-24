"""Career facts keep occurrence precision separate from recording time."""
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class CareerRecord(Base):
    __tablename__ = "career_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("career_records.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(120))
    organization: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(160))
    started_on: Mapped[str | None] = mapped_column(String(10))
    ended_on: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)
    approach: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    lessons: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(2000))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    progress: Mapped[str] = mapped_column(String(16), default="active")
    source: Mapped[str] = mapped_column(String(16), default="user")
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_messages.id", ondelete="SET NULL"))
    source_references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"))
    share_with_advisor: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
