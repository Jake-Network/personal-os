"""Indexed snapshot provenance and explicit evidence revocation."""
from sqlalchemy import delete, select, update

from app.modules.database.model import AdvisorMessage, ContextDocumentReference, ContextSnapshot
from app.schema.context_schema import payload_evidence


def reference_rows(snapshot_id: str, payload: dict) -> list[dict]:
    evidence = payload_evidence(payload)
    keys = {(int(item['document_id']), int(item.get('version_id') or 0))
            for item in evidence if item.get('document_id') is not None}
    return [{'snapshot_id': snapshot_id, 'document_id': doc, 'version_id': version}
            for doc, version in sorted(keys)]


def record_references(session, snapshot):
    rows = reference_rows(snapshot.id, snapshot.payload)
    if rows:
        session.add_all([ContextDocumentReference(**row) for row in rows])
        session.flush()


def purge_document_evidence(session, document_id: int):
    """Two set operations; never fetch or decode unrelated snapshot payloads."""
    ids = select(ContextDocumentReference.snapshot_id).where(ContextDocumentReference.document_id == document_id)
    session.execute(update(AdvisorMessage).where(AdvisorMessage.context_snapshot_id.in_(ids))
                    .values(context_purged=True), execution_options={'synchronize_session': 'fetch'})
    session.execute(delete(ContextSnapshot).where(ContextSnapshot.id.in_(ids)),
                    execution_options={'synchronize_session': 'fetch'})
    session.flush()
