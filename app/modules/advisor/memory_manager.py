"""Personal Memory and Decision Journal (PRD §6).

Advisor-proposed memories stay `proposed` until the user confirms them; only confirmed
memories enter the Personal Profile context.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.crud import audit_log_handler, decision_journal_handler, personal_memory_handler
from app.modules.database.model import DecisionJournalEntry, PersonalMemory, MemoryRevision
from app.schema.advisor_schema import DecisionCreate, DecisionReview, MemoryCreate


class MemoryManager:
    def list(self, session: Session, status: str) -> list[PersonalMemory]:
        return personal_memory_handler.get_by_status(session, status)

    def create(self, session: Session, body: MemoryCreate) -> PersonalMemory:
        memory = personal_memory_handler.create(session, {
            "kind": body.kind, "content": body.content, "status": "confirmed", "source": "user",
            "confirmed_at": datetime.now(UTC),
        })
        session.add(MemoryRevision(memory_id=memory.id, revision=0, kind=memory.kind, content=memory.content,
            status=memory.status, confirmed_at=memory.confirmed_at, source_references=[]))
        audit_log_handler.record(session, "user", "memory.create", f"personal_memories:{memory.id}")
        session.commit()
        return memory

    def decide(self, session: Session, memory_id: int, confirm: bool) -> PersonalMemory:
        memory = personal_memory_handler.get(session, memory_id)
        if memory is None:
            raise LookupError("memory not found")
        if memory.status != "proposed":
            raise ValueError(f"memory already {memory.status}")
        personal_memory_handler.update(session, memory, {
            "status": "confirmed" if confirm else "rejected",
            "confirmed_at": datetime.now(UTC) if confirm else None,
        })
        from app.modules.advisor.memory_history_manager import latest_revision
        from app.modules.context.record_privacy import stamp_references
        prior = latest_revision(session, memory.id)
        session.add(MemoryRevision(memory_id=memory.id, revision=prior.revision + 1 if prior else 0,
            kind=memory.kind, content=memory.content, status=memory.status, confirmed_at=memory.confirmed_at,
            source_references=stamp_references(session, [{"table": "advisor_messages", "id": memory.source_message_id}]) if memory.source_message_id else []))
        audit_log_handler.record(session, "user", "memory.confirm" if confirm else "memory.reject",
                                 f"personal_memories:{memory.id}")
        session.commit()
        return memory

    def delete(self, session: Session, memory_id: int) -> None:
        memory = personal_memory_handler.get(session, memory_id)
        if memory is None:
            raise LookupError("memory not found")
        personal_memory_handler.delete(session, memory)
        audit_log_handler.record(session, "user", "memory.delete", f"personal_memories:{memory_id}")
        session.commit()


class DecisionJournalManager:
    def list(self, session: Session) -> list[DecisionJournalEntry]:
        return decision_journal_handler.get_all(session)

    def create(self, session: Session, body: DecisionCreate) -> DecisionJournalEntry:
        from app.modules.advisor.answer_actions import final_answer_ids
        from app.modules.database.model import AdvisorMessage, ContextSnapshot, AdvisorConversation
        values = body.model_dump()
        if body.source_message_id is not None:
            message = session.get(AdvisorMessage, body.source_message_id)
            if message is None:
                raise LookupError("source message not found")
            if message.id not in final_answer_ids(session, [message]):
                raise ValueError("저장된 최종 답변만 결정으로 기록할 수 있습니다.")
            if message.context_purged or not message.context_snapshot_id:
                raise ValueError("원래 답변의 근거가 없어 결정에 연결할 수 없습니다.")
            if body.conversation_id not in (None, message.conversation_id) or body.context_snapshot_id not in (None, message.context_snapshot_id):
                raise ValueError("답변과 결정의 근거가 일치하지 않습니다.")
            values.update(conversation_id=message.conversation_id, context_snapshot_id=message.context_snapshot_id)
        if values["conversation_id"] is not None and session.get(AdvisorConversation, values["conversation_id"]) is None:
            raise LookupError("conversation not found")
        if values["context_snapshot_id"] is not None:
            snapshot = session.get(ContextSnapshot, values["context_snapshot_id"])
            if snapshot is None or snapshot.payload.get("source_purged"):
                raise ValueError("결정의 근거가 삭제되었습니다.")
            if values["conversation_id"] not in (None, snapshot.conversation_id):
                raise ValueError("대화와 결정의 근거가 일치하지 않습니다.")
            values["conversation_id"] = snapshot.conversation_id
        if body.review_on is not None:
            from zoneinfo import ZoneInfo
            from app.config import settings
            zone = ZoneInfo(settings.timezone)
            local = body.review_on.astimezone(zone) if body.review_on.tzinfo else body.review_on.replace(tzinfo=zone)
            values["review_on"] = local.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(UTC)
        entry = decision_journal_handler.create(session, values)
        audit_log_handler.record(session, "user", "decision.create", f"decision_journal:{entry.id}")
        session.commit()
        return entry

    def review(self, session: Session, entry_id: int, body: DecisionReview) -> DecisionJournalEntry:
        """Record what actually happened, next to what was expected at decision time."""
        entry = decision_journal_handler.get(session, entry_id)
        if entry is None:
            raise LookupError("decision not found")
        from app.modules.reviews.review_manager import add_outcome
        from app.schema.review_jobs_schema import OutcomeCreate

        record = add_outcome(session, entry_id, OutcomeCreate(actual_outcome=body.actual_outcome))
        from app.modules.agent.reflection import after_outcome
        after_outcome(session, entry_id, record.id)
        session.refresh(entry)
        audit_log_handler.record(session, "user", "decision.review", f"decision_journal:{entry.id}")
        session.commit()
        return entry


memory_manager = MemoryManager()
decision_journal_manager = DecisionJournalManager()
