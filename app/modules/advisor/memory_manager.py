"""Personal Memory and Decision Journal (PRD §6).

Advisor-proposed memories stay `proposed` until the user confirms them; only confirmed
memories enter the Personal Profile context.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.crud.advisor_handler import decision_journal_handler, personal_memory_handler
from app.modules.crud.audit_log_handler import audit_log_handler
from app.modules.database.model import DecisionJournalEntry, PersonalMemory
from app.schema.advisor_schema import DecisionCreate, DecisionReview, MemoryCreate


class MemoryManager:
    def list(self, session: Session, status: str) -> list[PersonalMemory]:
        return personal_memory_handler.get_by_status(session, status)

    def create(self, session: Session, body: MemoryCreate) -> PersonalMemory:
        memory = personal_memory_handler.create(session, {
            "kind": body.kind, "content": body.content, "status": "confirmed", "source": "user",
            "confirmed_at": datetime.now(UTC),
        })
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
        entry = decision_journal_handler.create(session, body.model_dump())
        audit_log_handler.record(session, "user", "decision.create", f"decision_journal:{entry.id}")
        session.commit()
        return entry

    def review(self, session: Session, entry_id: int, body: DecisionReview) -> DecisionJournalEntry:
        """Record what actually happened, next to what was expected at decision time."""
        entry = decision_journal_handler.get(session, entry_id)
        if entry is None:
            raise LookupError("decision not found")
        decision_journal_handler.update(session, entry, {
            "actual_outcome": body.actual_outcome, "reviewed_at": datetime.now(UTC),
        })
        audit_log_handler.record(session, "user", "decision.review", f"decision_journal:{entry.id}")
        session.commit()
        return entry


memory_manager = MemoryManager()
decision_journal_manager = DecisionJournalManager()
