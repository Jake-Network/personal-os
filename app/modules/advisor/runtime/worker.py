"""One server-owned run at a time; subscriptions never own or cancel inference."""
import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from uuid import uuid4

from langgraph.types import Command
from langsmith import tracing_context

from app.modules.advisor.runtime import authorization
from app.modules.advisor.runtime.persistence import RunRepository, LeaseLost
from app.modules.database.model import AdvisorMessage
from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorWorkspace
from app.modules.llm.errors import AdvisorError
from app.schema.advisor_runtime_schema import RunCreate, ScenarioCreate

logger = logging.getLogger(__name__)


def _store_problem(session, conversation_id, problem):
    from sqlalchemy import update
    from app.modules.database.model import AdvisorConversation
    session.execute(update(AdvisorConversation).where(AdvisorConversation.id == conversation_id)
        .values(updated_at=AdvisorConversation.updated_at))
    workspace = session.get(AdvisorWorkspace, conversation_id, populate_existing=True)
    if workspace is None:
        workspace = AdvisorWorkspace(conversation_id=conversation_id, revision=1)
        session.add(workspace)
    workspace.problem = problem
    workspace.revision += 1


async def process_one(database):
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.graph import build_conversation_graph, initial_state, needs_analysis, scenario_followup
    from app.modules.advisor.runtime.checkpoints import run_checkpointer, CheckpointLeaseLost
    from app.modules.advisor.proposal_manager import proposal_manager
    from app.modules.crud import message_handler

    owner = str(uuid4())
    with database.session() as session:
        repo = RunRepository(session)
        repo.recover_expired()
        run = repo.claim(owner)
        session.commit()
        if run is None:
            return False
        run_id, generation = run.id, run.lease_generation
        body = RunCreate.model_validate(run.input_payload)
        auth = run.authorization
        metadata = run.runtime_metadata or {}
        conversation = advisor_manager.get_conversation(session, run.conversation_id)
        config = {'configurable': {'thread_id': run_id}, 'recursion_limit': 100}

        async def guard():
            # Use a separate short transaction; the inference session must never hold the lease lock during I/O.
            with database.session() as checking:
                repository = RunRepository(checking)
                repository.heartbeat(run_id, owner, generation)
                authorization.require(checking, auth)
                checking.commit()

        async def heartbeat():
            while True:
                await asyncio.sleep(1)
                await guard()

        async def progress(event):
            with database.session() as observing:
                repository = RunRepository(observing)
                owned = repository.fence(run_id, owner, generation)
                if event.get('stage') in {'model_started', 'web_searching'}:
                    # Keep the persisted compatibility key for all uncertain external I/O.
                    owned.runtime_metadata = {**(owned.runtime_metadata or {}), 'model_inflight': True}
                repository.append_event(run_id, 'progress', event, worker_id=owner, generation=generation)
                observing.commit()

        def command_guard():
            # The lease fence and local data changes share one short transaction.
            repo.fence(run_id, owner, generation)
            authorization.require(session, auth)

        def record_data_operations(operations, *, command_plan, command_query, source_message_ids,
                                   recording_allowed=False):
            owned = repo.fence(run_id, owner, generation)
            owned.runtime_metadata = {**(owned.runtime_metadata or {}), 'data_operations': operations,
                'data_command_plan': command_plan, 'data_command_query': command_query,
                'data_command_source_ids': source_message_ids,
                'data_command_validation_version': 2,
                'data_command_recording_allowed': recording_allowed}
            # Keep the write receipt visible even when the later answer fails.
            owned.result = {**(owned.result or {}), 'data_operations': operations}
            receipt_digest = hashlib.sha256(json.dumps(operations, sort_keys=True,
                ensure_ascii=False, default=str).encode()).hexdigest()[:20]
            repo.append_event(run_id, 'data_operations', {'data_operations': operations},
                f'data_operations:{run.user_message_id}:{receipt_digest}', worker_id=owner, generation=generation)

        pulse = asyncio.create_task(heartbeat())
        try:
            await guard()
            with run_checkpointer(database, run_id, owner, generation) as checkpointer:
                graph = build_conversation_graph(session, advisor_manager, conversation, body.options(), run.model,
                    checkpointer=checkpointer, guard=guard, current_message_id=run.user_message_id,
                    on_progress=progress, run_authorization=auth, command_guard=command_guard,
                    on_data_operations=record_data_operations,
                    recorded_operations=(run.runtime_metadata or {}).get('data_operations'),
                    recorded_command_plan=(run.runtime_metadata or {}).get('data_command_plan'),
                    recorded_command_query=(run.runtime_metadata or {}).get('data_command_query'),
                    recorded_command_source_ids=(run.runtime_metadata or {}).get('data_command_source_ids'))
                saved = await graph.aget_state(config)
                pending = {item.id for task_state in saved.tasks for item in task_state.interrupts}
                response_id = run.checkpoint.get('question_id')
                if run.checkpoint.get('resume') is not None and response_id in pending:
                    value = Command(resume={response_id: run.checkpoint['resume']})
                else:
                    selected = None
                    from app.modules.database.model.advisor_runtime import AdvisorScenario
                    workspace = session.get(AdvisorWorkspace, run.conversation_id)
                    selected_id = body.scenario_id or (
                        workspace.selected_scenario_id if workspace and scenario_followup(body.message) else None)
                    if selected_id:
                        scenario = session.get(AdvisorScenario, selected_id)
                        if scenario and scenario.conversation_id == run.conversation_id:
                            if scenario.evidence.get('source_purged'):
                                raise AdvisorError('선택한 대안의 근거가 삭제되었습니다.', provider_code='source_policy_changed')
                            from app.modules.context.source_policy import require_live_request_sources
                            from app.modules.llm.types import LLMRequest
                            source_id = scenario.evidence.get('snapshot_id')
                            if source_id:
                                require_live_request_sources(session, LLMRequest(model=run.model, instructions='', input=[],
                                    source_snapshot_id=source_id,
                                    excluded_categories=tuple(str(c) for c in advisor_manager.sharing_exclusions(session, body.options()))))
                            selected = {'title': scenario.title, 'assumptions': scenario.assumptions,
                                        'constraints': scenario.constraints, 'source_snapshot_id': source_id,
                                        'prior_results': scenario.results}
                    from sqlalchemy import select
                    previous = session.scalar(select(AdvisorRun).where(
                        AdvisorRun.conversation_id == run.conversation_id,
                        AdvisorRun.user_message_id < run.user_message_id)
                        .order_by(AdvisorRun.user_message_id.desc()).limit(1))
                    previous_analysis = False
                    if previous is not None and previous.status == 'completed':
                        # Routing inherits intent only. Historical text/amounts still pass exclusively
                        # through ContextAssembler's current sharing and source checks.
                        previous_analysis = bool((previous.runtime_metadata or {}).get('analysis_used'))
                        if not previous_analysis:
                            previous_analysis = needs_analysis(initial_state(
                                previous.input_payload.get('message', ''), previous.depth))
                    from app.modules.advisor.pending_commands import find_pending_commands
                    pending = find_pending_commands(session, conversation_id=run.conversation_id,
                        message_id=run.user_message_id, query=body.message,
                        excluded=advisor_manager.sharing_exclusions(session, body.options())) if not saved.values else None
                    value = None if saved.values else initial_state(body.message, body.depth,
                        single_response=bool(metadata.get('single_response')), selected_scenario=selected,
                        explicit_scenario=body.scenario_id is not None, previous_analysis=previous_analysis,
                        pending_data_commands=pending)
                with tracing_context(enabled=False):
                    task = asyncio.create_task(graph.ainvoke(value, config, durability='sync'))
                # A failed heartbeat (including cancel/lock) also interrupts an in-flight provider request.
                try:
                    done, _ = await asyncio.wait({task, pulse}, return_when=asyncio.FIRST_COMPLETED)
                except asyncio.CancelledError:
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task
                    raise
                if pulse in done:
                    task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await task
                    pulse.result()
                state = task.result()
            await guard()
            row = repo.fence(run_id, owner, generation)
            row.runtime_metadata = {**(row.runtime_metadata or {}), 'analysis_used': needs_analysis(state)}
            row.checkpoint = {k: v for k, v in row.checkpoint.items() if k != 'resume'}
            if state.get('__interrupt__'):
                question = dict(state['__interrupt__'][0].value)
                question['id'] = state['__interrupt__'][0].id
                question.setdefault('allow_unknown', True)
                question_snapshot_id = state.get('snapshot_id')
                message_handler.create(session, {'conversation_id': row.conversation_id, 'role': 'assistant',
                    'content': question['question'], 'context_snapshot_id': question_snapshot_id})
                row.runtime_metadata = {**(row.runtime_metadata or {}), 'question_snapshot_id': question_snapshot_id}
                _store_problem(session, row.conversation_id, state.get('problem') or {'question': body.message})
                repo.transition(run_id, 'waiting_input', worker_id=owner, generation=generation,
                                clarification=question)
                repo.append_event(run_id, 'clarification', question, f'question:{question["id"]}')
                session.commit()
                return True
            snapshot_id = state.get('snapshot_id')
            answer, proposals, memories = state.get('answer', ''), state.get('proposals', []), state.get('memories', [])
            if metadata.get('single_response') and state.get('single_response'):
                from app.modules.advisor.proposals import extract_blocks
                answer, proposals, memories = extract_blocks(answer)
            reply = message_handler.create(session, {'conversation_id': row.conversation_id,
                'role': 'assistant', 'content': answer, 'model': row.model, 'context_snapshot_id': snapshot_id})
            actions, mems = proposal_manager.record(session, row.conversation_id, reply.id, proposals, memories)
            user = session.get(AdvisorMessage, row.user_message_id)
            if user:
                user.status, user.context_snapshot_id = 'complete', snapshot_id
            row.assistant_message_id = reply.id
            evidence = {'question': body.message, 'snapshot_id': snapshot_id, 'baseline_snapshot_id': state.get('baseline_snapshot_id', snapshot_id),
                        'as_of': state.get('baseline_payload', {}).get('generated_at') or state.get('context', {}).get('generated_at')}
            scenarios = []
            scenario_views = []
            parent_id = body.scenario_id
            for index, scenario in enumerate(state.get('scenarios', [])[:3]):
                from app.modules.database.model.advisor_runtime import AdvisorScenario
                parent = session.get(AdvisorScenario, parent_id) if parent_id else None
                saved = repo.create_scenario(row.conversation_id, ScenarioCreate(
                    request_id=f'{run_id}:{row.answer_revision}:{index}', title=scenario['title'],
                    parent_id=parent_id, parent_revision=parent.revision if parent else None,
                    assumptions=scenario.get('assumptions', {}), constraints=scenario.get('constraints', {})),
                    run_id=run_id, evidence=evidence, results=scenario.get('results', {}), unknowns=scenario.get('unknowns', []))
                scenarios.append(saved.id)
                from app.schema.advisor_runtime_schema import ScenarioView
                scenario_views.append(ScenarioView.model_validate(saved).model_dump(mode='json'))
            result = {'message_id': reply.id, 'context_snapshot_id': snapshot_id, 'answer': answer,
                'data_operations': state.get('data_operations', (row.runtime_metadata or {}).get('data_operations', [])),
                'context': state.get('context', {}), 'scenarios': scenarios,
                'limitations': state.get('limitations', []), 'model_calls': state.get('model_calls', 0),
                'tool_calls': state.get('tool_calls', 0),
                'proposals': [{'id': a.id, 'action': a.action, 'payload': a.payload, 'rationale': a.rationale} for a in actions],
                'memory_proposals': [{'id': m.id, 'kind': m.kind, 'content': m.content} for m in mems]}
            result['comparison'] = {'scenarios': scenario_views, 'evidence_basis': evidence,
                                    'limitations': result['limitations']} if scenarios else None
            result['artifacts'] = ([{'kind': 'message', 'id': str(reply.id), 'revision': row.answer_revision}]
                + [{'kind': 'scenario', 'id': value, 'revision': scenario_views[index]['revision']} for index, value in enumerate(scenarios)]
                + [{'kind': 'proposal', 'id': str(action.id)} for action in actions]
                + [{'kind': 'memory_candidate', 'id': str(memory.id)} for memory in mems])
            # Selection and first workspace creation use the same conversation lock.
            # Refresh under that lock so completion cannot lose a concurrent revision.
            _store_problem(session, row.conversation_id, state.get('problem') or {'question': body.message})
            repo.append_event(run_id, 'context', state.get('context', {}), f'context:{row.answer_revision}', worker_id=owner, generation=generation)
            repo.append_event(run_id, 'delta', {'text': answer, 'answer_revision': row.answer_revision}, f'answer:{row.answer_revision}', worker_id=owner, generation=generation)
            repo.append_event(run_id, 'done', result, f'done:{row.answer_revision}', worker_id=owner, generation=generation)
            repo.transition(run_id, 'completed', worker_id=owner, generation=generation, result=result)
            session.commit()
        except (LeaseLost, CheckpointLeaseLost):
            session.rollback()
            if session.get(AdvisorRun, run_id, populate_existing=True) is not None:
                repo.acknowledge_cancel(run_id)
                session.commit()
        except asyncio.CancelledError:
            session.rollback()
            # Shutdown leaves its lease for conservative recovery; never silently replay uncertain I/O.
            raise
        except Exception as exc:
            session.rollback()
            try:
                error = exc.as_dict() if isinstance(exc, AdvisorError) else {
                    'code': 'run_failed', 'message': '분석을 완료하지 못했습니다. 연결과 근거를 확인한 뒤 재시도하세요.'}
                recovery_messages = {
                    'request_budget_exceeded': '질문과 필수 근거가 전송 예산을 초과했습니다. 질문 범위를 좁히거나 새 상담을 시작하세요.',
                    'context_budget_exceeded': '필수 근거가 컨텍스트 예산을 초과했습니다. 공유 범위와 질문을 좁힌 뒤 다시 확인하세요.',
                    'source_policy_changed': '분석 근거가 삭제되거나 공유 범위가 변경되었습니다. 근거를 확인한 뒤 새 분석을 요청하세요.',
                    'run_authorization_changed': '앱 잠금 또는 모델·연결 계정 변경으로 분석 권한이 해제되었습니다. 설정 확인 후 재시도하세요.',
                    'invalid_structured_output': '모델의 분석 결과 형식을 검증하지 못했습니다. 선택한 모델을 확인하고 재시도하세요.',
                }
                if error.get('provider_code') in recovery_messages:
                    error['message'] = recovery_messages[error['provider_code']]
                repo.append_event(run_id, 'error', error, f'error:{generation}', worker_id=owner, generation=generation)
                repo.transition(run_id, 'blocked' if isinstance(exc, AdvisorError) else 'failed',
                    worker_id=owner, generation=generation, error=error['message'])
                session.commit()
            except (LeaseLost, CheckpointLeaseLost):
                session.rollback()
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pulse
    return True


async def process_pending(database, stop):
    while not stop.is_set():
        try:
            if await process_one(database):
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Consultation worker unavailable: %s', type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except TimeoutError:
            pass
