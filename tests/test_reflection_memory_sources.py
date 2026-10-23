"""A reflected memory retains every source through user confirmation."""
from sqlalchemy import select

from app.modules.advisor.memory_manager import memory_manager
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import AdvisorConversation, AdvisorMessage, ContextSnapshot, MemoryRevision


def source_message(session):
    session.add(AdvisorConversation(id=1, title="합성 상담"))
    for snapshot_id in ("answer-snapshot", "reflection-snapshot"):
        session.add(ContextSnapshot(id=snapshot_id, conversation_id=1, context_categories=[],
            record_references=[], source_updated_at={}, data_quality_flags=[],
            payload={"data": {}, "categories": []}, content_hash=snapshot_id))
    session.flush()
    message = AdvisorMessage(conversation_id=1, role="assistant", content="합성 답변",
                             context_snapshot_id="answer-snapshot")
    session.add(message)
    session.commit()
    return message


def test_reflection_sources_survive_confirmation_and_restrict_memory(session):
    message = source_message(session)
    reflection_ref = {"table": "context_snapshots", "id": "reflection-snapshot"}
    _, memories = proposal_manager.record(session, 1, message.id, [],
        [{"kind": "preference", "content": "근거를 먼저 듣고 싶어 한다"}], memory_sources=[reflection_ref])
    session.commit()
    memory = memories[0]
    proposed = session.scalar(select(MemoryRevision).where(MemoryRevision.memory_id == memory.id))
    assert {(ref["table"], ref["id"]) for ref in proposed.source_references} == {
        ("context_snapshots", "reflection-snapshot"), ("advisor_messages", message.id)}
    assert not source_allowed(session, [{"table": "personal_memories", "id": memory.id}])

    memory_manager.decide(session, memory.id, True)
    confirmed = session.scalar(select(MemoryRevision).where(MemoryRevision.memory_id == memory.id)
                               .order_by(MemoryRevision.revision.desc()))
    assert confirmed.source_references == proposed.source_references
    assert source_allowed(session, [{"table": "personal_memories", "id": memory.id}])
    snapshot = session.get(ContextSnapshot, "reflection-snapshot")
    snapshot.payload = {**snapshot.payload, "source_purged": True}
    session.commit()
    assert not source_allowed(session, [{"table": "personal_memories", "id": memory.id}])
