"""Indexed snapshot provenance and explicit evidence revocation."""
from sqlalchemy import delete, select, update, or_, func, cast, Integer, exists

from app.modules.database.model import AdvisorMessage, ContextDocumentReference, ContextSnapshot
from app.modules.context.types import payload_evidence
from app.modules.documents.types import DocumentReferenceRow


def reference_rows(snapshot_id: str, payload: dict) -> list[DocumentReferenceRow]:
    evidence = payload_evidence(payload)
    keys = {(int(item['document_id']), int(item.get('version_id') or 0))
            for item in evidence if item.get('document_id') is not None}
    return [{'snapshot_id': snapshot_id, 'document_id': doc, 'version_id': version}
            for doc, version in sorted(keys)]


def record_references(session, snapshot):
    rows = reference_rows(snapshot.id, snapshot.payload)
    # Derived plans can contain document information even when the current
    # package has no direct citation. Propagate the indexed dependency only;
    # never decode unrelated archived snapshot payloads during revocation.
    sources = snapshot.payload.get('derived_snapshot_ids', [])
    if sources:
        inherited = session.execute(select(ContextDocumentReference.document_id,
            ContextDocumentReference.version_id).where(ContextDocumentReference.snapshot_id.in_(sources)))
        existing = {(row['document_id'], row['version_id']) for row in rows}
        for document_id, version_id in inherited:
            if (document_id, version_id) not in existing:
                rows.append({'snapshot_id': snapshot.id, 'document_id': document_id, 'version_id': version_id})
                existing.add((document_id, version_id))
    if rows:
        session.add_all([ContextDocumentReference(**row) for row in rows])
        session.flush()


def purge_document_evidence(session, document_id: int):
    """Revoke indexed evidence and its durable runtime copies in one transaction.

    Chat text retains the established explicit-purge contract: mark it as
    context-purged, rather than treating evidence deletion as message deletion.
    """
    ids = select(ContextDocumentReference.snapshot_id).where(ContextDocumentReference.document_id == document_id)
    _purge_runtime_copies(session, ids)
    session.execute(update(AdvisorMessage).where(AdvisorMessage.context_snapshot_id.in_(ids))
                    .values(context_purged=True), execution_options={'synchronize_session': 'fetch'})
    session.execute(delete(ContextSnapshot).where(ContextSnapshot.id.in_(ids)),
                    execution_options={'synchronize_session': 'fetch'})
    session.flush()


def dependent_snapshot_ids(session, snapshot_id):
    """Return an explicit snapshot and its derived clones without fetching raw evidence."""
    rows = session.execute(select(ContextSnapshot.id, ContextSnapshot.payload['derived_snapshot_ids']))
    dependencies = {key: set(sources or []) for key, sources in rows if sources}
    affected = {snapshot_id}
    while True:
        more = {key for key, sources in dependencies.items() if sources & affected} - affected
        if not more:
            return affected
        affected |= more


def _purge_runtime_copies(session, snapshot_ids):
    from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorRunEvent, AdvisorScenario, AdvisorWorkspace
    from app.modules.advisor.runtime.checkpoints import delete_run_checkpoints
    from app.modules.database.model import ConversationSummary

    if session.bind.dialect.name == 'sqlite':
        refs = func.json_each(ConversationSummary.source_references).table_valued('value').alias('summary_source')
        table = func.json_extract(refs.c.value, '$.table')
        key = func.json_extract(refs.c.value, '$.id')
    else:
        refs = func.json_array_elements(ConversationSummary.source_references).table_valued('value').alias('summary_source')
        table = refs.c.value.op('->>')('table')
        key = refs.c.value.op('->>')('id')
    source_match = exists(select(1).select_from(refs).join(AdvisorMessage,
        AdvisorMessage.id == cast(key, Integer)).where(table == 'advisor_messages',
            AdvisorMessage.context_snapshot_id.in_(snapshot_ids)))
    session.execute(update(ConversationSummary).where(
        ConversationSummary.generator.in_(['graph_summary_v1', 'runtime_extract_v1']), source_match)
        .values(content='', status='source_purged'), execution_options={'synchronize_session': 'fetch'})

    event_run_ids = select(AdvisorRunEvent.run_id).where(
        AdvisorRunEvent.payload['snapshot_id'].as_string().in_(snapshot_ids))
    affected = session.scalars(select(AdvisorRun).where(or_(
        AdvisorRun.result['context_snapshot_id'].as_string().in_(snapshot_ids),
        AdvisorRun.runtime_metadata['question_snapshot_id'].as_string().in_(snapshot_ids),
        AdvisorRun.id.in_(event_run_ids)))).all()
    if not affected:
        return
    run_ids = [row.id for row in affected]
    # An in-flight saver uses this same run row as its transaction fence.
    affected = session.scalars(update(AdvisorRun).where(AdvisorRun.id.in_(run_ids)).values(
        lease_generation=AdvisorRun.lease_generation + 1,
        lease_owner=None, lease_until=None).returning(AdvisorRun),
        execution_options={'populate_existing': True}).all()
    for row in affected:
        if row.status not in {'completed', 'cancelled', 'failed'}:
            row.status = 'cancelled'
        row.result, row.checkpoint, row.clarification = None, {}, None
        row.runtime_metadata = {'evidence_purged': True}
        row.error = '문서 근거가 삭제되어 실행의 분석 근거를 제거했습니다.'
        row.revision += 1
    session.execute(delete(AdvisorRunEvent).where(AdvisorRunEvent.run_id.in_(run_ids)))
    scenario_match = or_(AdvisorScenario.run_id.in_(run_ids),
        AdvisorScenario.evidence['snapshot_id'].as_string().in_(snapshot_ids))
    scenario_ids = select(AdvisorScenario.id).where(scenario_match)
    session.execute(update(AdvisorWorkspace).where(AdvisorWorkspace.selected_scenario_id.in_(scenario_ids))
        .values(selected_scenario_id=None, revision=AdvisorWorkspace.revision + 1))
    session.execute(update(AdvisorScenario).where(scenario_match).values(
        title='문서 근거가 삭제된 대안', assumptions={}, constraints={}, results={}, unknowns=[],
        evidence={'source_purged': True}))
    session.flush()
    delete_run_checkpoints(session, run_ids)
    # Preserve monotonic event cursors so an existing subscriber observes purge.
    from app.modules.advisor.runtime.persistence import RunRepository
    repository = RunRepository(session)
    for row in affected:
        repository.append_event(row.id, 'status', {'status': row.status, 'evidence_purged': True},
            f'evidence-purged:{row.revision}')
