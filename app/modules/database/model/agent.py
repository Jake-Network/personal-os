"""Approved advisor procedures and local notices: guidance and pointers, never personal facts."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class Playbook(Base):
    __tablename__ = "playbooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    # proposed: no approved revision yet | active | archived | rejected
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    source: Mapped[str] = mapped_column(String(16), default="user")
    external_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PlaybookRevision(Base):
    """Content is immutable once written; only the approval status moves forward."""
    __tablename__ = "playbook_revisions"
    __table_args__ = (
        UniqueConstraint("playbook_id", "revision", name="uq_playbook_revision"),
        # At most one approved revision per playbook, even under concurrent approvals.
        Index("uq_playbook_active_revision", "playbook_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    playbook_id: Mapped[int] = mapped_column(ForeignKey("playbooks.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(String(300))
    triggers: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    # proposed | active | superseded | rejected
    status: Mapped[str] = mapped_column(String(16), index=True)
    base_revision_id: Mapped[int | None] = mapped_column(ForeignKey("playbook_revisions.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(16), default="user")
    rationale: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    proposed_by_job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id", ondelete="SET NULL"))
    source_purged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PlaybookUsage(Base):
    __tablename__ = "playbook_usages"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("playbook_revisions.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("advisor_runs.id", ondelete="SET NULL"))
    context_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("context_snapshots.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class InboxItem(Base):
    """A local notice. Summaries are displayed on this machine and never sent to a model."""
    __tablename__ = "inbox_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default="info")
    links: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="unread", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
