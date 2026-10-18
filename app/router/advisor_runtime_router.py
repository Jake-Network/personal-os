"""Durable consultation commands and replayable event subscriptions."""
import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.modules.database import get_session, db
from app.modules.advisor.runtime.persistence import RunRepository, TERMINAL
from app.modules.advisor.runtime.service import conversation_runtime
from app.schema.advisor_runtime_schema import (
    RunCreate, RunView, RunEvent, WorkspaceView, ClarificationResponse,
    ScenarioCreate, ScenarioView, ScenarioSelect,
)

router = APIRouter(prefix='/api/advisor', tags=['advisor-runtime'])


@router.get('/conversations/{conversation_id}/workspace', response_model=WorkspaceView)
def get_workspace(conversation_id: int, session: Session = Depends(get_session)):
    if session.bind.dialect.name == 'postgresql':
        session.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
    else:
        session.connection().exec_driver_sql('BEGIN')
    return RunRepository(session).workspace(conversation_id)


@router.post('/conversations/{conversation_id}/runs', response_model=RunView, status_code=201)
async def create_run(conversation_id: int, body: RunCreate, session: Session = Depends(get_session)):
    run = await conversation_runtime.create(session, conversation_id, body)
    session.commit()
    return run


@router.get('/runs/{run_id}', response_model=RunView)
def get_run(run_id: str, session: Session = Depends(get_session)):
    return RunRepository(session).view(run_id)


async def subscribe(run_id, after_seq=0, *, compatibility=False):
    cursor = after_seq
    terminal_sent = False
    while True:
        # No request-scoped transaction survives a network wait.
        with db.session() as session:
            repository = RunRepository(session)
            run = repository.view(run_id)
            events = repository.events(run_id, cursor)
        for event in events:
            cursor = event.seq
            data = event.model_dump(mode='json')
            event_type = event.type
            if compatibility:
                if event_type == 'clarification':
                    yield f'event: delta\ndata: {json.dumps({"type": "delta", "text": event.payload["question"]}, ensure_ascii=False)}\n\n'
                    yield f'event: done\ndata: {json.dumps({"type": "done", "run_id": run_id, "clarification": event.payload}, ensure_ascii=False)}\n\n'
                    return
                if event_type not in {'context', 'delta', 'done', 'error'}:
                    continue
                data = {'type': event_type, **event.payload}
                terminal_sent |= event_type in {'done', 'error'}
            yield f'id: {event.seq}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'
        if run.status in TERMINAL or run.status in {'waiting_input', 'blocked'}:
            if compatibility and not terminal_sent:
                payload = {'type': 'error', 'code': f'run_{run.status}',
                           'message': run.error or '분석이 중지되어 답변을 완료하지 않았습니다.'}
                yield f'event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
            return
        yield ': keepalive\n\n'
        await asyncio.sleep(0.5)


@router.get('/runs/{run_id}/events', response_model=RunEvent, response_class=StreamingResponse)
def run_events(run_id: str, after_seq: int = Query(0, ge=0), session: Session = Depends(get_session)):
    RunRepository(session).get(run_id)
    session.rollback()
    return StreamingResponse(subscribe(run_id, after_seq), media_type='text/event-stream',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@router.post('/runs/{run_id}/responses', response_model=RunView)
def respond_to_run(run_id: str, body: ClarificationResponse, session: Session = Depends(get_session)):
    row = RunRepository(session).respond(run_id, body)
    session.commit()
    return row


@router.post('/runs/{run_id}/cancel', response_model=RunView)
def cancel_run(run_id: str, session: Session = Depends(get_session)):
    row = RunRepository(session).cancel(run_id)
    session.commit()
    return row


@router.post('/runs/{run_id}/retry', response_model=RunView)
async def retry_run(run_id: str, session: Session = Depends(get_session)):
    from app.modules.advisor.runtime.authorization import capture
    row = RunRepository(session).retry(run_id)
    auth = capture(session)
    row.authorization = auth
    row.provider, row.account_binding = auth['provider'], auth['account_binding']
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager
    row.model = await llm_gateway_manager.resolve_model(session)
    # Explicit retry starts a fresh answer revision; uncertain model output is never appended.
    from app.modules.advisor.runtime.checkpoints import delete_run_checkpoints
    delete_run_checkpoints(session, [run_id])
    row.checkpoint = {}
    session.commit()
    return row


@router.post('/conversations/{conversation_id}/scenarios', response_model=ScenarioView, status_code=201)
def create_scenario(conversation_id: int, body: ScenarioCreate, session: Session = Depends(get_session)):
    row = RunRepository(session).create_scenario(conversation_id, body)
    session.commit()
    return row


@router.post('/conversations/{conversation_id}/scenarios/select', response_model=WorkspaceView)
def select_scenario(conversation_id: int, body: ScenarioSelect, session: Session = Depends(get_session)):
    repo = RunRepository(session)
    repo.select_scenario(conversation_id, body)
    session.commit()
    return repo.workspace(conversation_id)
