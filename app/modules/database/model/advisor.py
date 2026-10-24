"""Advisor tables (PRD v1.1 §8) plus approval/audit and app settings."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.database.model.base import Base, UTCDateTime, utcnow


class AppSetting(Base):
    """Small key/value store: privacy exclusions, host id, default model."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="chatgpt")
    status: Mapped[str] = mapped_column(String(24))  # connected | needs_reauth | disconnected
    issuer: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200))
    client_id: Mapped[str] = mapped_column(String(200))
    ext_agent_host_id: Mapped[str] = mapped_column(String(200))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    plan_usage_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    access_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class OAuthCredential(Base):
    """Encrypted token set; referenced by oauth_connections, never serialized to the API."""

    __tablename__ = "oauth_credentials"
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("oauth_connections.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AdvisorConversation(Base):
    __tablename__ = "advisor_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(32))  # optional starting domain (financial, career ...)
    origin: Mapped[str] = mapped_column(String(16), default="user")  # user | schedule
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    messages: Mapped[list["AdvisorMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AdvisorMessage.id"
    )


class AdvisorMessage(Base):
    __tablename__ = "advisor_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="complete")  # complete | incomplete | failed
    context_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("context_snapshots.id", ondelete="SET NULL"))
    context_purged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    conversation: Mapped[AdvisorConversation] = relationship(back_populates="messages")


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # context_snapshot_id
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("advisor_conversations.id", ondelete="CASCADE")
    )
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    context_categories: Mapped[list[str]] = mapped_column(JSON)
    excluded_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    record_references: Mapped[list[dict]] = mapped_column(JSON)
    source_updated_at: Mapped[dict] = mapped_column(JSON)  # category -> latest source timestamp
    data_quality_flags: Mapped[list[dict]] = mapped_column(JSON)
    # Exact package sent to the model, so past advice stays explainable after data changes.
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)


class AdvisorRecommendation(Base):
    __tablename__ = "advisor_recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("advisor_messages.id", ondelete="CASCADE"))
    summary: Mapped[str] = mapped_column(Text)
    user_rating: Mapped[int | None] = mapped_column(Integer)  # -1 | 0 | 1
    user_feedback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DecisionJournalEntry(Base):
    __tablename__ = "decision_journal"
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_messages.id", ondelete="SET NULL"))
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    context_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("context_snapshots.id", ondelete="SET NULL"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("advisor_conversations.id", ondelete="SET NULL")
    )
    alternatives: Mapped[list[str]] = mapped_column(JSON, default=list)
    choice: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    review_on: Mapped[datetime | None] = mapped_column(UTCDateTime())
    actual_outcome: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PersonalMemory(Base):
    __tablename__ = "personal_memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # profile | preference | constraint | priority
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # proposed | confirmed | rejected
    source: Mapped[str] = mapped_column(String(16))  # user | advisor
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_messages.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class LLMUsageEvent(Base):
    __tablename__ = "llm_usage_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(80))
    conversation_id: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24))  # completed | incomplete | failed | quota_exceeded | auth_error | blocked | cancelled
    error_code: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    context_chars: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ProposedAction(Base):
    """Write proposals from the advisor; nothing is applied until the user approves."""

    __tablename__ = "proposed_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(40))  # create_task | calendar_update | goal_update
    payload: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | failed
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("advisor_conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_ref: Mapped[dict | None] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(16))  # user | advisor | system
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
