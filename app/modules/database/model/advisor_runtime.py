"""Durable consultation execution records."""
from datetime import datetime
from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from app.modules.database.model.base import Base, UTCDateTime, utcnow

class AdvisorRuntimeLock(Base):
    __tablename__ = "advisor_runtime_lock"
    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)

class AdvisorRun(Base):
    __tablename__ = "advisor_runs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_advisor_run_request"),
        Index("uq_advisor_active_conversation", "conversation_id", unique=True,
              sqlite_where=text("status NOT IN ('completed','cancelled','failed')"),
              postgresql_where=text("status NOT IN ('completed','cancelled','failed')")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    depth: Mapped[str] = mapped_column(String(16), default="auto")
    input_payload: Mapped[dict] = mapped_column(JSON)
    user_message_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_messages.id", ondelete="SET NULL"))
    assistant_message_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_messages.id", ondelete="SET NULL"))
    authorization: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    clarification: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    account_binding: Mapped[str | None] = mapped_column(String(200))
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0)
    answer_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

class AdvisorRunEvent(Base):
    __tablename__ = "advisor_run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_advisor_event_seq"),
                      UniqueConstraint("run_id", "event_key", name="uq_advisor_event_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("advisor_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_key: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

class AdvisorRunResponse(Base):
    __tablename__ = "advisor_run_responses"
    __table_args__ = (UniqueConstraint("run_id", "request_id", name="uq_advisor_response_request"),
                      UniqueConstraint("run_id", "question_id", name="uq_advisor_question_response"))
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("advisor_runs.id", ondelete="CASCADE"))
    request_id: Mapped[str] = mapped_column(String(128))
    question_id: Mapped[str] = mapped_column(String(80))
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

class AdvisorScenario(Base):
    __tablename__ = "advisor_scenarios"
    __table_args__ = (UniqueConstraint("conversation_id", "request_id", name="uq_advisor_scenario_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("advisor_runs.id", ondelete="SET NULL"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("advisor_scenarios.id", ondelete="SET NULL"))
    request_id: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    unknowns: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

class AdvisorWorkspace(Base):
    __tablename__ = "advisor_workspaces"
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), primary_key=True)
    selected_scenario_id: Mapped[str | None] = mapped_column(ForeignKey("advisor_scenarios.id", ondelete="SET NULL"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    problem: Mapped[dict] = mapped_column(JSON, default=dict)
