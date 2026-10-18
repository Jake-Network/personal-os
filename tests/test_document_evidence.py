"""Revocation addresses indexed provenance, rather than scanning archived payloads."""
from sqlalchemy import event, select

from app.modules.crud import context_snapshot_handler, message_handler
from app.modules.database.model import AdvisorConversation, ContextDocumentReference, ContextSnapshot, AdvisorMessage
from app.modules.documents.evidence import purge_document_evidence


def test_purge_uses_indexed_dependencies_and_marks_messages_not_legacy(session):
    conversation = AdvisorConversation(title='history')
    session.add(conversation)
    session.flush()
    for i in range(150):
        context_snapshot_handler.create(session, dict(id=f'unrelated-{i}', conversation_id=conversation.id,
            context_categories=['career'], excluded_categories=[], record_references=[], source_updated_at={},
            data_quality_flags=[], payload={'unrelated': 'large archive ' * 100}, content_hash=str(i)))
    affected = context_snapshot_handler.create(session, dict(id='affected', conversation_id=conversation.id,
        context_categories=['career'], excluded_categories=[], record_references=[], source_updated_at={},
        data_quality_flags=[], payload={'document_dependencies': [{'document_id': 42, 'version_id': 4}]}, content_hash='affected'))
    message = message_handler.create(session, dict(conversation_id=conversation.id, role='assistant',
        content='derived private fact', context_snapshot_id=affected.id))
    session.commit()
    statements = []
    def observe(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    event.listen(session.get_bind(), 'before_cursor_execute', observe)
    try:
        purge_document_evidence(session, 42)
        session.commit()
    finally:
        event.remove(session.get_bind(), 'before_cursor_execute', observe)
    # Durable run provenance adds one indexed lookup; archived payloads remain unread.
    assert len(statements) <= 5
    assert not any('context_snapshots.payload' in sql for sql in statements)
    session.expire_all()
    assert session.get(ContextSnapshot, 'affected') is None
    assert session.get(AdvisorMessage, message.id).context_purged is True
    assert session.get(AdvisorMessage, message.id).context_snapshot_id is None
    assert len(list(session.scalars(select(ContextSnapshot)))) == 150
    assert not list(session.scalars(select(ContextDocumentReference)))


def test_explicit_snapshot_delete_marks_revocation(session):
    conversation = AdvisorConversation(title='history')
    session.add(conversation)
    session.flush()
    snapshot = context_snapshot_handler.create(session, dict(id='source', context_categories=[], excluded_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[], payload={}, content_hash='source'))
    message = message_handler.create(session, dict(conversation_id=conversation.id, role='user', content='x', context_snapshot_id=snapshot.id))
    context_snapshot_handler.delete(session, snapshot)
    session.commit()
    session.expire_all()
    assert message.context_snapshot_id is None and message.context_purged
