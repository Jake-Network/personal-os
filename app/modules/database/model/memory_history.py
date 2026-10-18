"""Append-only memory revisions and reproducible conversation summary drafts."""
from datetime import datetime
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.modules.database.model.base import Base, UTCDateTime, utcnow


class MemoryRevision(Base):
    __tablename__ = "memory_revisions"
    __table_args__ = (UniqueConstraint("memory_id", "revision", name="uq_memory_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("personal_memories.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_on: Mapped[datetime | None] = mapped_column(UTCDateTime())
    external_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    source_references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), index=True)
    first_message_id: Mapped[int] = mapped_column(Integer)
    last_message_id: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    source_references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(40), default="local_extract_v1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class HistorySearchIndex(Base):
    """Disposable local index: source message and hash are authoritative."""
    __tablename__ = "history_search_index"
    message_id: Mapped[int] = mapped_column(ForeignKey("advisor_messages.id", ondelete="CASCADE"), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(200))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(JSON)
    indexed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ConversationLink(Base):
    __tablename__ = "conversation_links"
    __table_args__ = (UniqueConstraint("conversation_id", "kind", "target", name="uq_conversation_link"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(200))
