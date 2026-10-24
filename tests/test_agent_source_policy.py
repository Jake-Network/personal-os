"""Regression checks at the final provider boundary, using synthetic records only."""
import asyncio

import pytest

from sqlalchemy import select

from test_agent_loop import env, consult, outbound, reflect, REFLECTION, FINAL, PLAN, add_playbook, package
from app.modules.agent import reflection
from app.modules.context.record_privacy import set_record_policy
from app.modules.database.model import DecisionJournalEntry
from app.modules.database.model.review_jobs import BackgroundJob


def test_local_only_decision_never_reaches_reflection_provider(env):
    client, database, provider = env
    with database.session() as session:
        decision = DecisionJournalEntry(title='합성 결정', choice='PRIVATE_CHOICE', rationale='PRIVATE_REASON', conversation_id=1)
        session.add(decision)
        session.commit()
        set_record_policy(session, 'decision_journal', decision.id, False)
        job = reflection.enqueue(session, request_id='private-decision', source='decision_outcome', decision_id=decision.id)
        job_id = job.id
        session.commit()
    provider.replies.append({'nothing_to_learn': True, 'playbooks': [], 'memories': []})
    assert asyncio.run(reflection.process_one(database))
    assert provider.requests == []
    with database.session() as session:
        assert session.get(BackgroundJob, job_id).status in {'cancelled', 'failed'}


def test_catalog_provenance_blocks_plan_after_playbook_sharing_revocation(env, monkeypatch):
    from app.modules.database.model import Playbook
    client, database, provider = env
    playbook = add_playbook(client, slug='일반-절차', triggers=['카탈로그전용'], summary='합성 절차 요약')
    original = provider.stream
    revoked = False

    async def revoke_after_first_request(session, request):
        nonlocal revoked
        async for event in original(session, request):
            yield event
        if not revoked:
            revoked = True
            with database.session() as updating:
                updating.get(Playbook, playbook['id']).external_allowed = False
                updating.commit()

    monkeypatch.setattr(provider, 'stream', revoke_after_first_request)
    run, requests = consult(client, database, provider, 'catalog-revoke', '현재 상황을 심층 분석해 줘',
        replies=({**PLAN, 'objective':'합성 절차 요약'}, {'valid':True,'issues':[],'retry_tasks':[]}, FINAL), depth='deep')
    assert len(requests) == 1, 'A derived plan must not be sent after its catalog source is revoked'
    assert run['status'] == 'blocked', run
    assert run['result'] is None


def test_large_playbook_catalog_is_bounded_and_disclosed(env):
    from app.modules.database.model import Playbook, PlaybookRevision
    client, database, provider = env
    with database.session() as session:
        for number in range(90):
            item = Playbook(slug=f'절차-{number:03d}', status='active', source='user')
            session.add(item)
            session.flush()
            session.add(PlaybookRevision(playbook_id=item.id, revision=1, status='active', source='user',
                title='합성 절차' * 20, summary='절차 요약' * 55, body='1. 근거를 확인한다.',
                triggers=[f'합성트리거{n}' * 5 for n in range(12)], categories=[]))
        session.commit()
    run, requests = consult(client, database, provider, 'catalog-budget', '현재 상황을 심층 분석해 줘',
        replies=(PLAN, {'valid':True,'issues':[],'retry_tasks':[]}, FINAL), depth='deep')
    assert run['status'] == 'completed', run
    context = package(requests[0])
    assert any(flag['code'] == 'playbook_catalog_omitted' for flag in context['data_quality_flags'])
    assert len(context['data'].get('playbook_catalog', {}).get('items', {})) < 90


def test_reflection_snapshot_preserves_decision_and_lesson_dependencies(env):
    from app.modules.database.model import ContextSnapshot, PlaybookRevision
    from app.modules.context.source_policy import source_allowed
    from app.modules.playbooks.playbook_manager import playbook_manager
    client, database, provider = env
    with database.session() as session:
        decision = DecisionJournalEntry(title='합성 결정', choice='SYNTHETIC_CHOICE', rationale='합성 이유', conversation_id=1)
        session.add(decision)
        session.commit()
        decision_id = decision.id
        job = reflection.enqueue(session, request_id='decision-snapshot', source='decision_outcome', decision_id=decision_id)
        job_id = job.id
        session.commit()
    provider.replies.append(REFLECTION)
    assert asyncio.run(reflection.process_one(database))
    snapshot_id = provider.requests[-1].source_snapshot_id
    with database.session() as session:
        snapshot = session.get(ContextSnapshot, snapshot_id)
        assert snapshot.payload['data']['decision_review']['choice'] == 'SYNTHETIC_CHOICE'
        assert any(r['table'] == 'decision_journal' and r['id'] == decision_id for r in snapshot.record_references)
        job = session.get(BackgroundJob, job_id)
        assert job.status == 'completed', job.last_error
        revision = session.get(PlaybookRevision, job.result['playbook_revision_ids'][0])
        assert any(r['table'] == 'context_snapshots' and r['id'] == snapshot_id for r in revision.source_references)
        playbook_manager.approve(session, revision.id)
        ref = [{'table':'playbook_revisions', 'id':revision.id}]
        assert source_allowed(session, ref)
        set_record_policy(session, 'decision_journal', decision_id, False)
        assert not source_allowed(session, ref)


def test_decision_revoked_during_async_assembly_is_blocked_at_egress(env, monkeypatch):
    from app.modules.advisor.runtime.context import ContextAssembler
    client, database, provider = env
    with database.session() as session:
        decision = DecisionJournalEntry(title='합성 결정', choice='PRIVATE_CHOICE', rationale='합성 이유', conversation_id=1)
        session.add(decision)
        session.commit()
        decision_id = decision.id
        job = reflection.enqueue(session, request_id='decision-race', source='decision_outcome', decision_id=decision_id)
        session.commit()
    original = ContextAssembler.validate_interfaces
    async def revoke(self, *args):
        await original(self, *args)
        with database.session() as session:
            set_record_policy(session, 'decision_journal', decision_id, False)
    monkeypatch.setattr(ContextAssembler, 'validate_interfaces', revoke)
    provider.replies.append(REFLECTION)
    assert asyncio.run(reflection.process_one(database))
    assert provider.requests == []


def test_learning_an_old_answer_preserves_the_exact_target_evidence(env):
    from app.modules.database.model import AdvisorMessage
    client, database, provider = env
    from app.modules.advisor.advisor_manager import advisor_manager
    target_answer = '합성 상담 근거를 확인합니다. ' * 60 + 'TARGET_ANSWER_TAIL'
    run, _ = consult(client, database, provider, 'old-learning-source', '이직 준비를 시작할까?',
                     replies=({**FINAL, 'answer': target_answer},))
    with database.session() as session:
        for number in range(advisor_manager.history_limit + 8):
            session.add(AdvisorMessage(conversation_id=1, role='user' if number % 2 == 0 else 'assistant',
                content=f'최근의 무관한 합성 대화 {number}', status='complete',
                context_snapshot_id=run['result']['context_snapshot_id']))
        session.commit()
    provider.replies.append({'nothing_to_learn': True, 'playbooks': [], 'memories': []})
    job = reflect(client, database, run, 'old-target-reflect')
    assert job.status == 'completed', job.last_error
    source_messages = package(provider.requests[-1])['data'].get('source_messages', [])
    assert any('TARGET_ANSWER_TAIL' in item['content'] for item in source_messages), source_messages
    assert any(item['content'] == run['result']['answer'] for item in source_messages)


def test_old_reflection_worker_cannot_send_under_a_new_owners_lease(env):
    from datetime import timedelta
    from app.modules.database.model.base import utcnow
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager
    from app.modules.llm.types import LLMRequest
    from app.modules.llm.errors import AdvisorError
    client, database, provider = env
    with database.session() as session:
        job = BackgroundJob(request_id='old-owner', kind='advisor_reflection', enabled=True, status='running',
            lease_owner='current-owner', lease_until=utcnow()+timedelta(minutes=1), payload={'automatic':False})
        session.add(job)
        session.commit()
        job_id = job.id
    provider.replies.append(FINAL)
    async def send():
        with database.session() as session:
            request = LLMRequest(model='fake-model', instructions='합성', input=[],
                background_job_id=job_id, background_job_owner='stale-owner')
            async for _ in llm_gateway_manager.stream(session, request):
                pass
    with pytest.raises(AdvisorError):
        asyncio.run(send())
    assert provider.requests == []


def test_expired_reflection_lease_cannot_be_renewed_or_publish(env):
    from datetime import timedelta
    from app.modules.database.model.base import utcnow
    client, database, provider = env
    with database.session() as session:
        job = BackgroundJob(request_id='expired-owner', kind='advisor_reflection', enabled=True, status='running',
            lease_owner='expired-owner', lease_until=utcnow()-timedelta(seconds=1), payload={})
        session.add(job)
        session.commit()
        job_id = job.id
    assert not reflection._heartbeat(database, job_id, 'expired-owner')
    with database.session() as session:
        assert not reflection._finish(session, job_id, 'expired-owner', 'completed', {'synthetic':True})


def test_old_consultation_worker_cannot_send_after_generation_changes(env):
    from app.modules.advisor.runtime.persistence import RunRepository
    from app.schema.advisor_runtime_schema import RunCreate
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager
    from app.modules.llm.types import LLMRequest
    from app.modules.llm.errors import AdvisorError
    client, database, provider = env
    with database.session() as session:
        repo = RunRepository(session)
        run = repo.create(1, RunCreate(request_id='run-owner', message='합성 질문'))
        claimed = repo.claim('current-owner')
        run_id, generation = claimed.id, claimed.lease_generation
        session.commit()
    provider.replies.append(FINAL)
    async def send():
        with database.session() as session:
            request = LLMRequest(model='fake-model', instructions='합성', input=[], run_id=run_id,
                                 run_owner='current-owner', run_generation=generation-1)
            async for _ in llm_gateway_manager.stream(session, request):
                pass
    with pytest.raises(AdvisorError):
        asyncio.run(send())
    assert provider.requests == []


def test_stopping_learning_worker_cancels_its_inflight_provider_task(env, monkeypatch):
    from contextlib import suppress
    client, database, provider = env
    run, _ = consult(client, database, provider, 'cancel-learning-source', '이직할까?')
    from test_agent_loop import reflect_request
    assert reflect_request(client, run, 'cancel-learning').status_code == 202
    async def check():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def blocked_stream(session, request):
            started.set()
            try:
                await asyncio.Event().wait()
                yield
            finally:
                stopped.set()
        monkeypatch.setattr(provider, 'stream', blocked_stream)
        task = asyncio.create_task(reflection.process_one(database))
        ready = asyncio.create_task(started.wait())
        try:
            done, _ = await asyncio.wait({task, ready}, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            with database.session() as session:
                job = session.scalar(select(BackgroundJob).where(BackgroundJob.request_id == 'cancel-learning'))
                assert ready in done, (job.status, job.last_error, job.result)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert stopped.is_set(), 'The worker must await cancellation of its provider task'
        finally:
            for pending in (task, ready):
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
    asyncio.run(check())


@pytest.mark.parametrize("with_overflow", [False, True])
def test_optional_catalog_yields_to_the_full_request_budget(env, monkeypatch, with_overflow):
    import json
    from dataclasses import replace
    from app.config import settings
    from app.modules.advisor import requests as request_module
    from app import config
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.context import ContextAssembler
    from app.modules.advisor.types import AskOptions
    from app.modules.database.model import AdvisorConversation, ContextSnapshot
    from app.modules.playbooks.selection import catalog_context
    client, database, provider = env
    for number in range(4):
        add_playbook(client, slug=f'예산-{number}', title='합성 절차', summary='합성 절차의 요약입니다. ' * 18,
                     triggers=['무관한트리거'])
    instruction = '합성 검증 지시입니다. ' * 20
    if with_overflow:
        from app.modules.database.model import AdvisorMessage
        with database.session() as session:
            session.add_all([AdvisorMessage(conversation_id=1, role='user' if number % 2 else 'assistant',
                content=f'합성 이전 대화 {number}', status='complete') for number in range(advisor_manager.history_limit + 4)])
            session.commit()
    with database.session() as session:
        assembler = ContextAssembler(session, advisor_manager, session.get(AdvisorConversation, 1), AskOptions(), 'fake-model')
        request, _ = asyncio.run(assembler.assemble('합성 질문', instruction=instruction))
        size = len(json.dumps({'instructions':request.instructions,'input':request.input},ensure_ascii=False))
        limit = size + 900
        constrained = replace(settings, request_char_limit=limit)
        monkeypatch.setattr(config, 'settings', constrained)
        monkeypatch.setattr(request_module, 'settings', constrained)
        catalog, flags = catalog_context(session, frozenset(), '합성 질문')
        request, evidence = asyncio.run(assembler.assemble('합성 질문', instruction=instruction,
            context_data={'playbook_catalog':catalog}, context_flags=flags))
        assert len(json.dumps({'instructions':request.instructions,'input':request.input},ensure_ascii=False)) <= limit
        assert any(flag['code']=='playbook_catalog_omitted' for flag in evidence.data_quality_flags)
        snapshot = session.get(ContextSnapshot, evidence.snapshot_id)
        sent_refs = set(evidence.payload['data']['playbook_catalog']['items'])
        assert sent_refs, 'Some catalog entries must still fit for this check to mean anything'
        # Offered entries are transport-checked payload, never evidence the answer depends on.
        catalog_refs = [r for r in snapshot.record_references if r['table'] == 'playbook_revisions']
        assert {f"playbook_revisions:{r['id']}" for r in catalog_refs} == sent_refs
        assert all(r['role'] == 'catalog' for r in catalog_refs)
        assert 'catalog_references' not in json.dumps(request.input, ensure_ascii=False)


def test_learning_an_old_answer_uses_the_current_explicit_model(env):
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager
    client, database, provider = env
    run, _ = consult(client, database, provider, 'old-model-answer', '이직할까?')
    assert provider.requests[0].model == 'fake-model'
    with database.session() as session:
        llm_gateway_manager.select(session, 'chatgpt_plan', 'synthetic-new-model')
    provider.replies.append({'nothing_to_learn': True, 'playbooks': [], 'memories': []})
    job = reflect(client, database, run, 'new-model-learning')
    assert job.status == 'completed', job.last_error
    assert provider.requests[-1].model == 'synthetic-new-model'
