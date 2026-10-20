"""Synthetic persistence regressions: idempotency, fenced writes, resume and history."""
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from alembic import command
from sqlalchemy import create_engine, text
from app.modules.advisor.runtime.persistence import RunRepository, LeaseLost
from app.modules.database.model import AdvisorConversation, AdvisorMessage
from app.modules.database.model.base import utcnow
from app.modules.database.migration_manager import alembic_config
from app.schema.advisor_runtime_schema import RunCreate, ClarificationResponse, ScenarioCreate, ScenarioSelect

def setup_repo(session):
    conversation = AdvisorConversation(title="synthetic")
    session.add(conversation)
    session.flush()
    return RunRepository(session), conversation.id

def test_run_request_id_is_stable_and_active_conversation_exclusive(session):
    repo, cid = setup_repo(session)
    request = RunCreate(request_id="same", message="질문")
    first = repo.create(cid, request)
    assert repo.create(cid, request).id == first.id
    assert len(session.scalars(select(AdvisorMessage)).all()) == 1
    with pytest.raises(HTTPException) as error:
        repo.create(cid, RunCreate(request_id="same", message="다른 질문"))
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        repo.create(cid, RunCreate(request_id="another", message="질문"))
    assert repo.workspace(cid).active_run.id == first.id
    assert [e.seq for e in repo.events(first.id)] == [1]

def test_lease_generation_and_expiry_fence_outputs(session):
    repo, cid = setup_repo(session)
    run = repo.create(cid, RunCreate(request_id="run", message="질문"))
    claimed = repo.claim("worker")
    generation = claimed.lease_generation
    assert repo.claim("another") is None
    repo.append_event(run.id, "progress", {"label": "조회"}, "step", worker_id="worker", generation=generation)
    repo.append_event(run.id, "progress", {"label": "조회"}, "step", worker_id="worker", generation=generation)
    assert len(repo.events(run.id)) == 3
    run.lease_until = utcnow() - timedelta(seconds=1)
    session.flush()
    with pytest.raises(LeaseLost):
        repo.transition(run.id, "completed", worker_id="worker", generation=generation, result={"answer": "stale"})
    repo.recover_expired()
    assert run.status == "blocked"
    repo.retry(run.id)
    repo.claim("new")
    with pytest.raises(LeaseLost):
        repo.heartbeat(run.id, "worker", generation)
    assert run.answer_revision == 2

def test_clarification_resume_exactly_once_and_cancel_fences_worker(session):
    repo, cid = setup_repo(session)
    run = repo.create(cid, RunCreate(request_id="run", message="질문"))
    repo.claim("worker")
    repo.transition(run.id, "waiting_input", worker_id="worker", generation=run.lease_generation,
                    clarification={"id": "q1", "question": "기간은?"})
    response = ClarificationResponse(request_id="answer", question_id="q1",
                                     expected_revision=run.revision, response="3개월")
    repo.respond(run.id, response)
    repo.respond(run.id, response)
    responses = session.scalars(select(AdvisorMessage).where(AdvisorMessage.content == "3개월")).all()
    assert len(responses) == 1
    assert responses[0].status == "complete"
    assert run.status == "queued"
    assert run.checkpoint["resume"] == "3개월"
    with pytest.raises(HTTPException):
        repo.respond(run.id, response.model_copy(update={"request_id": "other"}))
    repo.claim("worker")
    generation = run.lease_generation
    repo.cancel(run.id)
    assert run.status == "cancel_requested"
    with pytest.raises(LeaseLost):
        repo.transition(run.id, "completed", worker_id="worker", generation=generation)
    repo.acknowledge_cancel(run.id)
    assert run.status == "cancelled"
    assert repo.cancel(run.id).status == "cancelled"
    assert session.get(AdvisorMessage, run.user_message_id).status == "failed"

def test_scenario_versions_preserve_original_and_selection_is_optimistic(session):
    repo, cid = setup_repo(session)
    original = repo.create_scenario(cid, ScenarioCreate(request_id="a", title="원본", assumptions={"expense": "100"}))
    child = repo.create_scenario(cid, ScenarioCreate(request_id="b", title="수정", parent_id=original.id,
        parent_revision=original.revision, assumptions={"expense": "80"}))
    assert child.revision == 2
    assert original.assumptions == {"expense": "100"}
    repo.select_scenario(cid, ScenarioSelect(scenario_id=child.id, expected_revision=1))
    assert repo.workspace(cid).selected_scenario_id == child.id
    with pytest.raises(HTTPException):
        repo.select_scenario(cid, ScenarioSelect(scenario_id=original.id, expected_revision=1))

def test_scenario_can_be_deselected_with_optimistic_revision(session):
    repo, cid = setup_repo(session)
    scenario = repo.create_scenario(cid, ScenarioCreate(request_id="selected", title="선택"))
    repo.select_scenario(cid, ScenarioSelect(scenario_id=scenario.id, expected_revision=1))
    repo.select_scenario(cid, ScenarioSelect(scenario_id=None, expected_revision=2))
    assert repo.workspace(cid).selected_scenario_id is None
    assert repo.workspace(cid).revision == 3
    with pytest.raises(HTTPException):
        repo.select_scenario(cid, ScenarioSelect(scenario_id=None, expected_revision=2))


def test_expired_safe_checkpoint_requeues_but_uncertain_call_requires_retry(session):
    repo, cid = setup_repo(session)
    run = repo.create(cid, RunCreate(request_id="safe", message="synthetic"))
    repo.claim("old")
    run.runtime_metadata = {"model_inflight": False}
    run.lease_until = utcnow() - timedelta(seconds=1)
    session.flush()
    repo.recover_expired()
    assert run.status == "queued"
    assert session.get(AdvisorMessage, run.user_message_id).status == "pending"
    repo.claim("new")
    run.runtime_metadata = {"model_inflight": True}
    run.lease_until = utcnow() - timedelta(seconds=1)
    session.flush()
    repo.recover_expired()
    assert run.status == "blocked"
    assert session.get(AdvisorMessage, run.user_message_id).status == "failed"

def test_purged_scenario_cannot_be_selected_used_or_derived(session):
    repo, cid = setup_repo(session)
    scenario = repo.create_scenario(cid, ScenarioCreate(request_id="purged", title="삭제된 근거"),
                                    evidence={"source_purged": True})
    with pytest.raises(HTTPException) as selected:
        repo.select_scenario(cid, ScenarioSelect(scenario_id=scenario.id, expected_revision=1))
    assert selected.value.status_code == 409
    with pytest.raises(HTTPException) as used:
        repo.create(cid, RunCreate(request_id="use-purged", message="synthetic", scenario_id=scenario.id))
    assert used.value.status_code == 409
    with pytest.raises(HTTPException) as derived:
        repo.create_scenario(cid, ScenarioCreate(request_id="child", title="수정", parent_id=scenario.id,
                                                parent_revision=scenario.revision))
    assert derived.value.status_code == 409

def test_advisor_runtime_migration_preserves_existing_conversation(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = alembic_config(url)
    command.upgrade(config, "0009_merge_local_os")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO advisor_conversations (id,title,created_at,updated_at) VALUES (42,'synthetic',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO advisor_messages (id,conversation_id,role,content,status,context_purged,created_at) VALUES (77,42,'user','synthetic','complete',0,CURRENT_TIMESTAMP)"))
    command.upgrade(config, "0010_advisor_runtime")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM advisor_conversations")).scalar_one() == 42
        assert conn.execute(text("SELECT id FROM advisor_messages")).scalar_one() == 77
        assert conn.execute(text("SELECT count(*) FROM advisor_runs")).scalar_one() == 0
    engine.dispose()

def test_concurrent_duplicate_creation_and_global_worker_limit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from app.modules.database.model import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([AdvisorConversation(id=1, title="one"), AdvisorConversation(id=2, title="two")])
        session.commit()

    def submit(_):
        with Session(engine) as session:
            run = RunRepository(session).create(1, RunCreate(request_id="duplicate", message="synthetic"))
            run_id = run.id
            session.commit()
            return run_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        created = list(workers.map(submit, range(2)))
    assert created[0] == created[1]
    with Session(engine) as session:
        RunRepository(session).create(2, RunCreate(request_id="another", message="synthetic"))
        session.commit()

    def claim(worker):
        with Session(engine) as session:
            run = RunRepository(session).claim(worker)
            run_id = run.id if run else None
            session.commit()
            return run_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        claimed = list(workers.map(claim, ["first", "second"]))
    assert sum(run_id is not None for run_id in claimed) == 1
    engine.dispose()


def test_workspace_projects_original_question_for_legacy_scenario_without_mutation(session):
    repo, cid = setup_repo(session)
    original = repo.create(cid, RunCreate(request_id='original-question', message='원래 질문'))
    original.status = 'completed'
    session.flush()
    scenario = repo.create_scenario(cid, ScenarioCreate(request_id='legacy-scenario', title='대안 이름'),
        run_id=original.id, evidence={'snapshot_id': 'historical-snapshot'})
    purged = repo.create_scenario(cid, ScenarioCreate(request_id='purged-scenario', title='삭제된 대안'),
        run_id=original.id, evidence={'source_purged': True})
    repo.create(cid, RunCreate(request_id='new-question', message='최신 질문'))
    projected = {item.id: item for item in repo.workspace(cid).scenarios}
    assert projected[scenario.id].evidence['question'] == '원래 질문'
    assert 'question' not in projected[purged.id].evidence
    assert scenario.evidence == {'snapshot_id': 'historical-snapshot'}
