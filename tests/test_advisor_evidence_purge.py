import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from langgraph.checkpoint.base import empty_checkpoint
from app.modules.advisor.runtime.checkpoints import create_checkpointer

from app.modules.advisor.runtime.persistence import RunRepository
from app.modules.crud import context_snapshot_handler, message_handler
from app.modules.database.model import AdvisorConversation, AdvisorMessage, ContextDocumentReference, ContextSnapshot
from app.modules.database.model.advisor_runtime import AdvisorRunEvent, AdvisorScenario, AdvisorWorkspace
from app.modules.documents.evidence import purge_document_evidence
from app.schema.advisor_runtime_schema import RunCreate, ScenarioCreate
from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.llm.errors import AdvisorError
from app.modules.llm.types import LLMRequest
from app.modules.advisor.history_service import history_service


def snapshot(session, conversation_id, key, payload):
    return context_snapshot_handler.create(session, dict(id=key, conversation_id=conversation_id,
        context_categories=[], excluded_categories=[], record_references=[], source_updated_at={},
        data_quality_flags=[], payload=payload, content_hash=key))


def test_purge_removes_derived_runtime_copies_and_keeps_unrelated_chat(session, checkpoint_schema):
    conversation = AdvisorConversation(title='synthetic')
    session.add(conversation)
    session.flush()
    baseline = snapshot(session, conversation.id, 'source', {
        'document_dependencies': [{'document_id': 42, 'version_id': 4}], 'raw': 'synthetic-secret'})
    derived = snapshot(session, conversation.id, 'derived', {'derived_snapshot_ids': [baseline.id]})
    assert session.scalar(select(ContextDocumentReference).where(
        ContextDocumentReference.snapshot_id == derived.id)).document_id == 42
    repo = RunRepository(session)
    run = repo.create(conversation.id, RunCreate(request_id='purge-run', message='synthetic question'))
    run.status = 'running'
    run.lease_owner = 'old-worker'
    run.result = {'context_snapshot_id': derived.id, 'raw': 'synthetic-secret'}
    run.clarification = {'question': 'synthetic-secret'}
    run.checkpoint = {'resume': 'synthetic-secret'}
    repo.append_event(run.id, 'progress', {'snapshot_id': derived.id, 'raw': 'synthetic-secret'})
    scenario = repo.create_scenario(conversation.id, ScenarioCreate(request_id='scenario', title='synthetic-secret'),
        run_id=run.id, evidence={'snapshot_id': derived.id}, results={'raw': 'synthetic-secret'})
    child = repo.create_scenario(conversation.id, ScenarioCreate(request_id='child', title='synthetic-secret child',
        parent_id=scenario.id, parent_revision=scenario.revision, assumptions={'raw': 'synthetic-secret'}))
    assert child.run_id is None and child.evidence == scenario.evidence
    session.add(AdvisorWorkspace(conversation_id=conversation.id, selected_scenario_id=child.id))
    chat = message_handler.create(session, {'conversation_id': conversation.id, 'role': 'assistant',
        'content': 'preserved local chat', 'context_snapshot_id': derived.id})
    auto_summary = history_service.record_summary(session, conversation.id, 'synthetic-secret summary',
        {'first_message_id': chat.id, 'last_message_id': chat.id, 'source_message_ids': [chat.id]})
    other_conversation = AdvisorConversation(title='unrelated')
    session.add(other_conversation)
    session.flush()
    unrelated = repo.create(other_conversation.id, RunCreate(request_id='other', message='unrelated'))
    unrelated.result = {'answer': 'unrelated result'}
    run.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    session.commit()
    config = {'configurable': {'thread_id': run.id, 'checkpoint_ns': ''}}
    checkpoint = empty_checkpoint()
    checkpoint['channel_values'] = {'synthetic': 'synthetic-secret'}
    checkpoint['channel_versions'] = {'synthetic': '1'}
    with create_checkpointer(session.bind, run.id, run.lease_owner, run.lease_generation) as saver:
        saved = saver.put(config, checkpoint, {'source': 'input', 'step': -1, 'parents': {}}, {'synthetic': '1'})
        saver.put_writes(saved, [('synthetic', 'synthetic-secret')], 'synthetic-task')
    previous_generation = run.lease_generation
    purge_document_evidence(session, 42)
    session.commit()
    session.expire_all()
    assert session.get(ContextSnapshot, derived.id) is None
    assert run.status == 'cancelled' and run.lease_generation > previous_generation
    assert run.result is None and run.checkpoint == {} and run.clarification is None
    assert run.runtime_metadata == {'evidence_purged': True}
    checkpoint_tables = ('checkpoints', 'writes') if session.bind.dialect.name == 'sqlite' else (
        'checkpoints', 'checkpoint_writes', 'checkpoint_blobs')
    for table in checkpoint_tables:
        assert not session.execute(text(f'SELECT * FROM {table} WHERE thread_id=:id'), {'id': run.id}).all()
    events = session.scalars(select(AdvisorRunEvent).where(AdvisorRunEvent.run_id == run.id)).all()
    assert len(events) == 1 and events[0].payload['evidence_purged']
    assert 'synthetic-secret' not in str(scenario.results) + str(scenario.evidence) + scenario.title
    assert child.assumptions == {} and child.evidence == {'source_purged': True}
    assert session.get(AdvisorWorkspace, conversation.id).selected_scenario_id is None
    assert session.get(AdvisorMessage, chat.id).content == 'preserved local chat'
    assert session.get(AdvisorMessage, chat.id).context_purged
    assert auto_summary.content == '' and auto_summary.status == 'source_purged'
    assert unrelated.result == {'answer': 'unrelated result'}


@pytest.mark.parametrize('change', ['sharing', 'delete'])
def test_child_scenario_keeps_source_policy_at_actual_gateway(session, fake_provider, change):
    conversation = AdvisorConversation(title='synthetic')
    session.add(conversation)
    session.flush()
    source = snapshot(session, conversation.id, 'scenario-source', {})
    source.context_categories = ['financial']
    repo = RunRepository(session)
    parent = repo.create_scenario(conversation.id, ScenarioCreate(request_id='parent', title='parent'),
        evidence={'snapshot_id': source.id})
    child = repo.create_scenario(conversation.id, ScenarioCreate(request_id='child', title='child',
        parent_id=parent.id, parent_revision=parent.revision, assumptions={'private': 'synthetic-private-assumption'}))
    session.commit()
    request = LLMRequest(model='synthetic', instructions='', source_snapshot_id=child.evidence.get('snapshot_id'),
        input=[{'role': 'developer', 'content': str(child.assumptions)}])
    if change == 'sharing':
        privacy_manager.set_excluded(session, [Category.FINANCIAL])
    else:
        context_snapshot_handler.delete(session, source)
        session.commit()
    async def collect():
        return [event async for event in advisor_manager.gateway.stream(session, request)]
    with pytest.raises(AdvisorError) as failure:
        asyncio.run(collect())
    assert failure.value.provider_code == 'source_policy_changed'
    assert fake_provider.requests == []


def test_explicit_snapshot_purge_clears_transitive_runtime_and_child_copies(session):
    from app.router.advisor_router import delete_snapshot
    conversation = AdvisorConversation(title='synthetic')
    session.add(conversation)
    session.flush()
    original = snapshot(session, conversation.id, 'original', {'raw': 'synthetic-secret'})
    derived = snapshot(session, conversation.id, 'first-derived', {'derived_snapshot_ids': [original.id]})
    final = snapshot(session, conversation.id, 'final-derived', {'derived_snapshot_ids': [derived.id]})
    unrelated = snapshot(session, conversation.id, 'unrelated', {'raw': 'unrelated evidence'})
    repo = RunRepository(session)
    run = repo.create(conversation.id, RunCreate(request_id='snapshot-purge', message='synthetic question'))
    run.status = 'completed'
    run.result = {'context_snapshot_id': final.id, 'raw': 'synthetic-secret'}
    parent = repo.create_scenario(conversation.id, ScenarioCreate(request_id='parent', title='parent'),
        run_id=run.id, evidence={'snapshot_id': final.id})
    child = repo.create_scenario(conversation.id, ScenarioCreate(request_id='child', title='child',
        parent_id=parent.id, parent_revision=parent.revision, assumptions={'raw': 'synthetic-secret'}))
    message = message_handler.create(session, {'conversation_id': conversation.id, 'role': 'assistant',
        'content': 'preserved local chat', 'context_snapshot_id': final.id})
    auto_summary = history_service.record_summary(session, conversation.id, 'synthetic-secret summary',
        {'first_message_id': message.id, 'last_message_id': message.id, 'source_message_ids': [message.id]})
    session.commit()
    delete_snapshot(original.id, session)
    session.expire_all()
    assert session.get(ContextSnapshot, final.id) is None
    assert session.get(ContextSnapshot, derived.id) is None
    assert run.result is None
    assert child.assumptions == {} and child.evidence == {'source_purged': True}
    assert auto_summary.content == '' and auto_summary.status == 'source_purged'
    assert session.get(ContextSnapshot, unrelated.id).payload == {'raw': 'unrelated evidence'}
