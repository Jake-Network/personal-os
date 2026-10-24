"""Durable HTTP commands and the real graph/worker against a migrated synthetic DB."""
import asyncio
import json
from collections import deque
from contextlib import suppress
from datetime import timedelta

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.modules.database.database import Database, get_session
from app.modules.database.migration_manager import alembic_config
from app.modules.database.model import AdvisorConversation, AdvisorMessage
from app.modules.advisor.runtime.worker import process_one
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.modules.llm.types import StreamEvent
from app.schema.advisor_runtime_schema import RunResult

PLAN = {"objective": "synthetic", "tasks": [], "scenarios": []}
REVIEW = {"valid": True, "issues": [], "retry_tasks": []}
FINAL = {"answer": "합성 상담 결과입니다.", "proposals": [], "memories": []}


class ScriptedProvider:
    name = "chatgpt_plan"

    def __init__(self):
        self.replies = deque()
        self.requests = []

    async def list_models(self, session):
        return ["fake-model"]

    async def stream(self, session, request):
        self.requests.append(request)
        assert self.replies, "Unexpected unbudgeted model call"
        value = self.replies.popleft()
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = await value()
        yield StreamEvent("delta", text=json.dumps(value, ensure_ascii=False))
        yield StreamEvent("completed", usage={"input_tokens": 10, "output_tokens": 10})


@pytest.fixture
def runtime_env(postgres_url, monkeypatch):
    from app.modules.llm import transfer_policy
    from app.router import advisor_runtime_router

    database = Database()
    url = postgres_url
    migration = alembic_config(url)
    command.upgrade(migration, "head")
    database.init(url)
    provider = ScriptedProvider()
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    monkeypatch.setattr(transfer_policy, "account_binding", lambda session, provider: "synthetic-account")
    monkeypatch.setattr(advisor_runtime_router, "db", database)
    with database.session() as session:
        session.add(AdvisorConversation(id=1, title="합성 상담"))
        session.commit()
        transfer_policy.confirm(session, "chatgpt_plan", True, True)
    app = FastAPI()
    app.include_router(advisor_runtime_router.router)

    def dependency():
        with database.session() as session:
            yield session

    app.dependency_overrides[get_session] = dependency
    try:
        with TestClient(app) as client:
            yield client, database, provider
    finally:
        database.engine.dispose()


def create(client, request_id="first"):
    response = client.post("/api/advisor/conversations/1/runs",
                           json={"request_id": request_id, "message": "현재 상담을 정리해 주세요.", "depth": "deep"})
    assert response.status_code == 201, response.text
    return response.json()


def finish(database):
    assert asyncio.run(process_one(database))


def test_running_followup_sends_saved_workout_and_respects_health_exclusion(runtime_env):
    from datetime import date
    from app.modules.database.model import WorkoutLog

    client, database, provider = runtime_env
    performed_on = date.today() - timedelta(days=2)
    with database.session() as session:
        workout = WorkoutLog(performed_on=performed_on, activity="합성 마라톤 10km",
                             duration_minutes=50, intensity="moderate")
        session.add(workout)
        session.commit()
        workout_id = workout.id

    def consult(request_id, message, **options):
        offset = len(provider.requests)
        provider.replies.append(FINAL)
        response = client.post('/api/advisor/conversations/1/runs', json={
            'request_id': request_id, 'message': message, 'depth': 'auto', **options})
        assert response.status_code == 201, response.text
        finish(database)
        completed = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
        assert completed['status'] == 'completed', completed
        assert len(provider.requests) == offset + 1
        return provider.requests[offset:]

    consult('running-goal', '하프 마라톤 1시간 35분 하는건 좀 무리일까?')
    requests = consult('running-history', '내가 토요일에 10km를 어떻게 훈련했지?')
    for request in requests:
        context = next(item for item in request.input if item['role'] == 'developer'
                       and item['content'].startswith('Context Package'))
        package = json.loads(context['content'].split('\n', 1)[1])
        recent = package['data']['get_health_summary']['recent']
        assert recent == [{'ref': f'workout_logs:{workout_id}', 'on': performed_on.isoformat(),
                           'activity': '합성 마라톤 10km', 'minutes': 50, 'intensity': 'moderate'}]

    restricted = consult('running-private', '내가 토요일에 10km를 어떻게 훈련했지?', exclude=['health'])
    for request in restricted:
        outbound = json.dumps([request.instructions, request.input], ensure_ascii=False)
        assert 'get_health_summary' not in outbound
        assert '합성 마라톤 10km' not in outbound


def test_legacy_subscriber_has_terminal_error_after_cancel(runtime_env):
    from app.router.advisor_runtime_router import subscribe
    client, _, provider = runtime_env
    run = create(client)
    assert client.post(f"/api/advisor/runs/{run['id']}/cancel").status_code == 200

    async def collect():
        return ''.join([part async for part in subscribe(run['id'], compatibility=True)])

    body = asyncio.run(collect())
    assert 'event: error' in body and 'run_cancelled' in body
    assert not provider.requests


def test_quantitative_followup_recalculates_current_cash_and_respects_exclusion(runtime_env):
    from datetime import date
    from decimal import Decimal
    from app.modules.database.model import Account

    client, database, provider = runtime_env
    with database.session() as session:
        account = Account(name='합성 생활비 계좌', kind='checking', currency='KRW',
                          balance=Decimal('24000000'), balance_as_of=date.today(), is_liquid=True)
        session.add(account)
        session.commit()
        account_id = account.id
    scenario = {'title': '생활비 가정', 'assumptions': {'financial': {
        'monthly_expense': '3000000', 'monthly_income': '0'}}}
    provider.replies.extend([{**PLAN, 'scenarios': [scenario]}, {'answer': '조건부 런웨이는 8개월입니다.'}])
    first = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'runway-first', 'message': '현재 현금으로 생활비 월 300만원이면 얼마나 버틸까?'}).json()
    finish(database)
    first = client.get(f"/api/advisor/runs/{first['id']}").json()
    assert first['status'] == 'completed', first
    assert first['request_id'] == 'runway-first'
    assert first['result']['comparison']['scenarios'][0]['results']['server_calculations']['financial']['months'] == '8.0'

    with database.session() as session:
        session.get(Account, account_id).balance = Decimal('18000000')
        session.commit()
    revised = {**scenario, 'assumptions': {'financial': {'monthly_expense': '2000000', 'monthly_income': '0'}}}
    provider.replies.extend([{**PLAN, 'scenarios': [revised]}, {'answer': '조건부 런웨이는 9개월입니다.'}])
    followup = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'runway-followup', 'message': '그럼 월 200만원이면?'}).json()
    finish(database)
    followup = client.get(f"/api/advisor/runs/{followup['id']}").json()
    assert followup['status'] == 'completed', followup
    assert followup['result']['model_calls'] == 2
    calculation = followup['result']['comparison']['scenarios'][0]['results']['server_calculations']['financial']
    assert calculation['months'] == '9.0'
    assert calculation['usable_cash'] == '18000000.00'

    offset = len(provider.requests)
    provider.replies.extend([PLAN, {'answer': '현금 공유를 제외하여 현재 조건을 계산할 수 없습니다.'}])
    restricted = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'runway-restricted', 'message': '그럼 월 100만원이면?', 'exclude': ['financial']}).json()
    finish(database)
    restricted = client.get(f"/api/advisor/runs/{restricted['id']}").json()
    assert restricted['status'] == 'completed', restricted
    assert restricted['result']['model_calls'] == 2
    for request in provider.requests[offset:]:
        outbound = json.dumps([request.instructions, request.input], ensure_ascii=False)
        for private in ['24000000', '18000000', '합성 생활비 계좌', '생활비 월 300만원']:
            assert private not in outbound


def test_selected_workspace_scenario_does_not_force_unrelated_question_into_analysis(runtime_env):
    client, database, provider = runtime_env
    scenario = client.post('/api/advisor/conversations/1/scenarios', json={
        'request_id': 'old-scenario', 'title': '지난 재무 대안', 'assumptions': {'financial': {'monthly_expense': '1234567'}}}).json()
    # Selecting an old alternative requires its original, still-valid evidence.
    from app.modules.database.model import ContextSnapshot
    from app.modules.database.model.advisor_runtime import AdvisorScenario
    with database.session() as session:
        snapshot = ContextSnapshot(id='old-scenario-evidence', conversation_id=1, context_categories=[],
            record_references=[], source_updated_at={}, data_quality_flags=[], payload={}, content_hash='synthetic')
        session.add(snapshot)
        session.flush()
        session.get(AdvisorScenario, scenario['id']).evidence = {'snapshot_id': snapshot.id}
        session.commit()
    selected = client.post('/api/advisor/conversations/1/scenarios/select', json={
        'scenario_id': scenario['id'], 'expected_revision': 1})
    assert selected.status_code == 200, selected.text
    provider.replies.append(FINAL)
    run = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'unrelated', 'message': '다른 질문. 오늘 할 일 알려줘'}).json()
    finish(database)
    completed = client.get(f"/api/advisor/runs/{run['id']}").json()
    assert completed['status'] == 'completed', completed
    assert completed['result']['model_calls'] == 1
    assert '1234567' not in json.dumps([provider.requests[0].instructions, provider.requests[0].input], ensure_ascii=False)
    workspace = client.get('/api/advisor/conversations/1/workspace').json()
    cleared = client.post('/api/advisor/conversations/1/scenarios/select', json={
        'scenario_id': None, 'expected_revision': workspace['revision']})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['selected_scenario_id'] is None


def test_server_finishes_without_subscriber_and_restores_workspace_events(runtime_env):
    client, database, provider = runtime_env
    provider.replies.extend([PLAN, REVIEW, FINAL])
    run = create(client)
    assert run["status"] == "queued"
    # No event subscriber or browser stream exists during execution.
    finish(database)
    restored = client.get("/api/advisor/conversations/1/workspace").json()
    assert restored["active_run"] is None
    completed = restored["latest_run"]
    assert completed["status"] == "completed", completed
    assert completed["result"]["answer"] == FINAL["answer"]
    result = RunResult.model_validate(completed["result"])
    assert result.model_calls == 3
    assert result.artifacts[0].kind == "message"
    assert restored["last_event_seq"] == completed["last_event_seq"]
    events = client.get(f"/api/advisor/runs/{run['id']}/events").text
    ids = [int(line.split(": ")[1]) for line in events.splitlines() if line.startswith("id: ")]
    assert ids == list(range(1, completed["last_event_seq"] + 1))
    assert "event: done" in events
    replay = client.get(f"/api/advisor/runs/{run['id']}/events", params={"after_seq": ids[-2]}).text
    assert f"id: {ids[-1]}" in replay
    assert f"id: {ids[-2]}\n" not in replay
    with database.session() as session:
        messages = session.scalars(select(AdvisorMessage).order_by(AdvisorMessage.id)).all()
        assert [(m.role, m.status) for m in messages] == [("user", "complete"), ("assistant", "complete")]
    assert len(provider.requests) == 3


def test_clarification_survives_new_worker_and_duplicate_response(runtime_env):
    client, database, provider = runtime_env
    provider.replies.append({**PLAN, "clarification": {"question": "어느 기간인가요?", "reason": "비교 기간", "options": ["3개월"]}})
    run = create(client)
    finish(database)
    waiting = client.get(f"/api/advisor/runs/{run['id']}").json()
    assert waiting["status"] == "waiting_input", waiting
    assert client.get("/api/advisor/conversations/1/workspace").json()['problem']['objective'] == PLAN['objective']
    assert client.get("/api/advisor/conversations/1/workspace").json()["active_run"]["clarification"] == waiting["clarification"]
    body = {"request_id": "response", "question_id": waiting["clarification"]["id"],
            "expected_revision": waiting["revision"], "response": "3개월"}
    first = client.post(f"/api/advisor/runs/{run['id']}/responses", json=body)
    assert first.status_code == 200, first.text
    assert client.post(f"/api/advisor/runs/{run['id']}/responses", json=body).status_code == 200
    conflict = client.post(f"/api/advisor/runs/{run['id']}/responses", json={**body, "request_id": "stale"})
    assert conflict.status_code == 409
    provider.replies.extend([PLAN, REVIEW, FINAL])
    finish(database)
    completed = client.get(f"/api/advisor/runs/{run['id']}").json()
    assert completed["status"] == "completed", completed
    assert len(provider.requests) == 4
    assert any("3개월" in str(request.input) for request in provider.requests[1:])
    with database.session() as session:
        history = session.scalars(select(AdvisorMessage).order_by(AdvisorMessage.id)).all()
        assert [(m.role, m.content) for m in history] == [
            ("user", "현재 상담을 정리해 주세요."), ("assistant", "어느 기간인가요?"),
            ("user", "3개월"), ("assistant", FINAL["answer"])]
        assert history[2].context_snapshot_id == history[1].context_snapshot_id
        assert history[2].context_snapshot_id is not None


def test_queued_cancel_and_explicit_retry_has_new_answer_revision(runtime_env):
    client, database, provider = runtime_env
    run = create(client)
    cancelled = client.post(f"/api/advisor/runs/{run['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert client.post(f"/api/advisor/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert not asyncio.run(process_one(database))
    provider.replies.extend([RuntimeError("synthetic provider outage")])
    failed = create(client, "failure")
    finish(database)
    failure = client.get(f"/api/advisor/runs/{failed['id']}").json()
    assert failure["status"] in {"failed", "blocked"}, failure
    retried = client.post(f"/api/advisor/runs/{failed['id']}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["answer_revision"] == 2
    provider.replies.extend([PLAN, REVIEW, FINAL])
    finish(database)
    done = client.get(f"/api/advisor/runs/{failed['id']}").json()
    assert done["status"] == "completed", done
    assert done["answer_revision"] == 2
    with database.session() as session:
        replies = session.scalars(select(AdvisorMessage).where(AdvisorMessage.role == "assistant")).all()
        assert len(replies) == 1


def test_inflight_cancel_revokes_fence_before_provider_returns(runtime_env):
    client, database, provider = runtime_env
    run = create(client)

    async def cancel_during_call():
        response = client.post(f"/api/advisor/runs/{run['id']}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancel_requested"
        return PLAN

    provider.replies.append(cancel_during_call)
    finish(database)
    cancelled = client.get(f"/api/advisor/runs/{run['id']}").json()
    assert cancelled["status"] == "cancelled", cancelled
    assert cancelled["result"] is None
    with database.session() as session:
        assert session.scalars(select(AdvisorMessage).where(AdvisorMessage.role == "assistant")).all() == []


def test_restart_after_durable_plan_does_not_repeat_completed_model_call(runtime_env):
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.graph import build_conversation_graph, initial_state
    from app.modules.advisor.runtime.checkpoints import run_checkpointer
    from app.modules.advisor.runtime.persistence import RunRepository
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow
    from app.schema.advisor_runtime_schema import RunCreate

    client, database, provider = runtime_env
    provider.replies.extend([PLAN, REVIEW, FINAL])
    created = create(client)

    async def checkpoint_plan_then_stop():
        with database.session() as session:
            repo = RunRepository(session)
            run = repo.claim("interrupted-worker")
            generation = run.lease_generation
            session.commit()
            body = RunCreate.model_validate(run.input_payload)
            conversation = advisor_manager.get_conversation(session, run.conversation_id)

            async def progress(event):
                if event.get("stage") == "model_started":
                    with database.session() as observing:
                        row = RunRepository(observing).fence(run.id, "interrupted-worker", generation)
                        row.runtime_metadata = {**row.runtime_metadata, "model_inflight": True}
                        observing.commit()

            with run_checkpointer(database, run.id, "interrupted-worker", generation) as saver:
                graph = build_conversation_graph(session, advisor_manager, conversation, body.options(), run.model,
                    checkpointer=saver, current_message_id=run.user_message_id, on_progress=progress,
                    run_authorization=run.authorization)
                config = {"configurable": {"thread_id": run.id}}
                await graph.ainvoke(initial_state(body.message, depth="deep"), config, durability="sync", interrupt_after=["plan"])
                stored = await graph.aget_state(config)
                assert stored.values["model_calls"] == 1
                assert stored.next == ("collected",)

    asyncio.run(checkpoint_plan_then_stop())
    with database.session() as session:
        run = session.get(AdvisorRun, created["id"])
        assert run.runtime_metadata["model_inflight"] is False
        run.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
    finish(database)
    restored = client.get(f"/api/advisor/runs/{created['id']}").json()
    assert restored["status"] == "completed", restored
    assert len(provider.requests) == 3
    assert RunResult.model_validate(restored["result"]).model_calls == 3


def test_restart_during_uncertain_provider_call_blocks_without_automatic_replay(runtime_env):
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow

    client, database, provider = runtime_env
    created = create(client)

    async def interrupt_provider():
        entered = asyncio.Event()

        async def never_completed():
            entered.set()
            await asyncio.Event().wait()

        provider.replies.append(never_completed)
        task = asyncio.create_task(process_one(database))
        await asyncio.wait_for(entered.wait(), timeout=10)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(interrupt_provider())
    with database.session() as session:
        run = session.get(AdvisorRun, created["id"])
        assert run.runtime_metadata["model_inflight"] is True
        run.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
    assert not asyncio.run(process_one(database))
    blocked = client.get(f"/api/advisor/runs/{created['id']}").json()
    assert blocked["status"] == "blocked", blocked
    assert blocked["result"] is None
    assert len(provider.requests) == 1


def test_subscriber_drains_completion_committed_during_event_read(runtime_env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.modules.advisor.runtime.persistence import RunRepository

    client, database, provider = runtime_env
    provider.replies.extend([PLAN, REVIEW, FINAL])
    created = create(client)
    original_events = RunRepository.events
    raced = False

    def complete_after_read(repository, run_id, after_seq=0):
        nonlocal raced
        captured = original_events(repository, run_id, after_seq)
        if not raced:
            raced = True
            # The first event batch was read before completion. A terminal state
            # observed afterward must not make the subscriber discard the next batch.
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(lambda: asyncio.run(process_one(database))).result(timeout=30)
        return captured

    monkeypatch.setattr(RunRepository, "events", complete_after_read)
    response = client.get(f"/api/advisor/runs/{created['id']}/events")
    assert response.status_code == 200
    assert raced
    assert "event: done" in response.text
    assert FINAL["answer"] in response.text


def test_restart_with_consumed_response_preserves_next_unanswered_interrupt(runtime_env):
    from langgraph.types import Command
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.graph import build_conversation_graph
    from app.modules.advisor.runtime.checkpoints import run_checkpointer
    from app.modules.advisor.runtime.persistence import RunRepository
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow
    from app.schema.advisor_runtime_schema import RunCreate

    client, database, provider = runtime_env
    provider.replies.append({**PLAN, "clarification": {"question": "기간은?"}})
    created = create(client)
    finish(database)
    first = client.get(f"/api/advisor/runs/{created['id']}").json()
    first_id = first["clarification"]["id"]
    submitted = client.post(f"/api/advisor/runs/{created['id']}/responses", json={
        "request_id": "first-answer", "question_id": first_id,
        "expected_revision": first["revision"], "response": "3개월"})
    assert submitted.status_code == 200, submitted.text
    provider.replies.append({**PLAN, "clarification": {"question": "예산은?"}})

    async def persist_next_interrupt_without_publishing_state():
        with database.session() as session:
            run = RunRepository(session).claim("crashing-resumer")
            generation = run.lease_generation
            session.commit()
            body = RunCreate.model_validate(run.input_payload)
            conversation = advisor_manager.get_conversation(session, run.conversation_id)

            async def progress(event):
                if event.get("stage") == "model_started":
                    with database.session() as observing:
                        row = RunRepository(observing).fence(run.id, "crashing-resumer", generation)
                        row.runtime_metadata = {**row.runtime_metadata, "model_inflight": True}
                        observing.commit()

            with run_checkpointer(database, run.id, "crashing-resumer", generation) as saver:
                graph = build_conversation_graph(session, advisor_manager, conversation, body.options(), run.model,
                    checkpointer=saver, current_message_id=run.user_message_id,
                    on_progress=progress, run_authorization=run.authorization)
                config = {"configurable": {"thread_id": run.id}}
                state = await graph.ainvoke(Command(resume={first_id: "3개월"}), config, durability="sync")
                second = state["__interrupt__"][0]
                assert second.id != first_id
                assert second.value["question"] == "예산은?"
                return second.id

    second_id = asyncio.run(persist_next_interrupt_without_publishing_state())
    with database.session() as session:
        run = session.get(AdvisorRun, created["id"])
        assert run.status == "running"
        assert run.checkpoint["question_id"] == first_id
        assert run.checkpoint["resume"] == "3개월"
        assert run.runtime_metadata["model_inflight"] is False
        run.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
    finish(database)
    restored = client.get(f"/api/advisor/runs/{created['id']}").json()
    assert restored["status"] == "waiting_input", restored
    assert restored["clarification"]["id"] == second_id
    assert restored["clarification"]["question"] == "예산은?"
    assert len(provider.requests) == 2  # The old period answer never answers the budget question.
    with database.session() as session:
        assert "resume" not in session.get(AdvisorRun, created["id"]).checkpoint
        answers = session.scalars(select(AdvisorMessage).where(AdvisorMessage.content == "3개월")).all()
        assert len(answers) == 1
    provider.replies.extend([PLAN, REVIEW, FINAL])
    response = client.post(f"/api/advisor/runs/{created['id']}/responses", json={
        "request_id": "second-answer", "question_id": second_id,
        "expected_revision": restored["revision"], "response": "예산은 아직 모름"})
    assert response.status_code == 200, response.text
    finish(database)
    completed = client.get(f"/api/advisor/runs/{created['id']}").json()
    assert completed["status"] == "completed", completed
    assert len(provider.requests) == 5


def test_heartbeat_continues_while_async_retrievers_yield_after_snapshot_flush(runtime_env, monkeypatch):
    from app.modules.advisor.runtime.context import ContextAssembler
    from app.modules.advisor.runtime.persistence import RunRepository

    client, database, provider = runtime_env
    provider.replies.extend([PLAN, REVIEW, FINAL])
    original = ContextAssembler.validate_interfaces
    original_heartbeat = RunRepository.heartbeat
    validated = []
    timing = {"waiting": False, "heartbeats": 0}

    def observe_heartbeat(repository, *args, **kwargs):
        row = original_heartbeat(repository, *args, **kwargs)
        if timing["waiting"]:
            timing["heartbeats"] += 1
        return row

    async def yield_past_heartbeat(assembler, query, package, options, history):
        # Snapshot DML must commit before
        # yielding here, so the worker's independent heartbeat can take its lock.
        timing["waiting"] = True
        try:
            await asyncio.sleep(1.1)
            result = await original(assembler, query, package, options, history)
        finally:
            timing["waiting"] = False
        validated.append(package.snapshot_id)
        return result

    monkeypatch.setattr(ContextAssembler, "validate_interfaces", yield_past_heartbeat)
    monkeypatch.setattr(RunRepository, "heartbeat", observe_heartbeat)
    created = create(client)
    finish(database)
    result = client.get(f"/api/advisor/runs/{created['id']}").json()
    assert result["status"] == "completed", result
    assert result["error"] is None
    assert result["result"]["answer"] == FINAL["answer"]
    assert len(provider.requests) == 3
    assert len(validated) >= 3
    assert timing["heartbeats"] >= 1


def test_auto_dialogue_completes_in_one_validated_call(runtime_env):
    client, database, provider = runtime_env
    provider.replies.append(FINAL)
    response = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "auto-direct", "message": "McKinsey 내 성장과 승진 가능성이 궁금해요", "depth": "auto"})
    assert response.status_code == 201, response.text
    run = response.json()
    finish(database)
    completed = client.get(f"/api/advisor/runs/{run['id']}").json()
    assert completed["status"] == "completed", completed
    assert completed["result"]["answer"] == FINAL["answer"]
    assert completed["result"]["model_calls"] == len(provider.requests) == 1
    assert completed["result"]["context_snapshot_id"]
    assert "```proposal" not in provider.requests[0].instructions
    assert "JSON 스키마" in provider.requests[0].instructions
    assert provider.requests[0].json_mode is True
    with database.session() as session:
        messages = session.scalars(select(AdvisorMessage).order_by(AdvisorMessage.id)).all()
        assert [(m.role, m.status) for m in messages] == [("user", "complete"), ("assistant", "complete")]
