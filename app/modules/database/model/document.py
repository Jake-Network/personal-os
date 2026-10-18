"""Versioned personal documents; raw uploads are durable indexing jobs."""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Date, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    categories: Mapped[list[str]] = mapped_column(JSON)
    kind: Mapped[str] = mapped_column(String(64), default="reference")
    sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("job_applications.id", ondelete="SET NULL"))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    # Pointer deliberately has no cyclic FK: deletion cascades through versions.
    active_version_id: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    as_of: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding_dimensions: Mapped[int | None] = mapped_column()
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Claims so far; bounds crash loops and transient-error retries.
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("version_id", "ordinal", name="uq_document_chunk_ordinal"),
                      {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column()
    page: Mapped[int | None] = mapped_column()
    section: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector().with_variant(JSON(), "sqlite"))


class ContextDocumentReference(Base):
    """Indexed provenance survives document deletion; snapshots own its lifetime."""
    __tablename__ = "context_document_references"
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("context_snapshots.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[int] = mapped_column(primary_key=True, index=True)
    version_id: Mapped[int] = mapped_column(primary_key=True)
