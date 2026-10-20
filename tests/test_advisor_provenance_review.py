import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from app.schema.advisor_schema import DecisionCreate
from app.modules.advisor.memory_manager import decision_journal_manager
from app.modules.advisor.runtime.persistence import RunRepository
from app.modules.database.model import AdvisorConversation, AdvisorMessage, ContextSnapshot
from app.schema.advisor_runtime_schema import ScenarioCreate, ScenarioSelect, RunCreate


def evidence(session, purged=False):
    conv = AdvisorConversation(title='합성 질문')
    session.add(conv)
    session.flush()
    snap = ContextSnapshot(id='original', conversation_id=conv.id, context_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[],
        payload={'source_purged': purged}, content_hash='synthetic')
    session.add(snap)
    session.flush()
    msg = AdvisorMessage(conversation_id=conv.id, role='assistant', content='최종 답변', context_snapshot_id=snap.id)
    session.add(msg)
    session.commit()
    return conv, snap, msg


def test_decision_title_database_limit_is_validated():
    with pytest.raises(ValidationError):
        DecisionCreate(title='가' * 201, choice='선택', rationale='이유')


@pytest.mark.parametrize('source', ['message', 'snapshot'])
def test_decision_rejects_retained_but_purged_snapshot(session, source):
    conv, snap, msg = evidence(session, purged=True)
    kwargs = {'source_message_id': msg.id} if source == 'message' else {'context_snapshot_id': snap.id}
    with pytest.raises(ValueError):
        decision_journal_manager.create(session, DecisionCreate(title='결정', choice='선택', rationale='이유', **kwargs))


def test_decision_persists_source_answer_and_survives_its_deletion(session):
    from sqlalchemy import delete
    conv, snap, msg = evidence(session)
    entry = decision_journal_manager.create(session, DecisionCreate(title='결정', choice='선택', rationale='이유', source_message_id=msg.id))
    assert entry.source_message_id == msg.id
    session.execute(delete(AdvisorMessage).where(AdvisorMessage.id == msg.id))
    session.commit()
    session.refresh(entry)
    assert entry.source_message_id is None
    assert entry.context_snapshot_id == snap.id


@pytest.mark.parametrize('state', ['missing', 'deleted', 'purged'])
@pytest.mark.parametrize('operation', ['select', 'run'])
def test_scenario_evidence_is_checked_consistently(session, state, operation):
    conv, snap, msg = evidence(session, purged=state == 'purged')
    scenario_evidence = {} if state == 'missing' else {'snapshot_id': 'deleted' if state == 'deleted' else snap.id}
    repo = RunRepository(session)
    scenario = repo.create_scenario(conv.id, ScenarioCreate(request_id='scenario', title='대안'), evidence=scenario_evidence)
    with pytest.raises(HTTPException) as exc:
        if operation == 'select':
            repo.select_scenario(conv.id, ScenarioSelect(scenario_id=scenario.id, expected_revision=1))
        else:
            repo.create(conv.id, RunCreate(request_id='run', message='대안 분석', scenario_id=scenario.id))
    assert exc.value.status_code == 409
