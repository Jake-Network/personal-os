from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.agent import inbox_manager, reflection, settings_manager
from app.modules.crud.playbook_handler import inbox_handler
from app.modules.database import get_session
from app.modules.database.model import LLMUsageEvent, PlaybookRevision, PlaybookUsage
from app.modules.database.model.base import utcnow
from app.modules.llm.errors import AdvisorError
from app.schema.playbook_schema import (
    AgentActivity, AgentSettings, AgentSettingsView, InboxCount, InboxItemView, ReflectRequest,
)
from app.schema.review_jobs_schema import JobItem

router = APIRouter(prefix="/api", tags=["agent"])


@router.get("/inbox", response_model=list[InboxItemView])
def list_inbox_items(status: str | None = Query(None, pattern="^(unread|read|dismissed)$"),
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     session: Session = Depends(get_session)):
    return inbox_handler.listed(session, status, limit, offset)


@router.get("/inbox/count", response_model=InboxCount)
def count_unread_inbox(session: Session = Depends(get_session)):
    return InboxCount(unread=inbox_handler.unread(session))


@router.post("/inbox/read-all", response_model=InboxCount)
def read_all_inbox(session: Session = Depends(get_session)):
    inbox_manager.read_all(session)
    return InboxCount(unread=0)


@router.post("/inbox/{item_id}/read", response_model=InboxItemView)
def read_inbox_item(item_id: int, session: Session = Depends(get_session)):
    try:
        return inbox_manager.mark(session, item_id, "read")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/inbox/{item_id}/dismiss", response_model=InboxItemView)
def dismiss_inbox_item(item_id: int, session: Session = Depends(get_session)):
    try:
        return inbox_manager.mark(session, item_id, "dismissed")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/agent/settings", response_model=AgentSettingsView)
def get_agent_settings(session: Session = Depends(get_session)):
    return settings_manager.view(session)


@router.put("/agent/settings", response_model=AgentSettingsView)
def update_agent_settings(body: AgentSettings, session: Session = Depends(get_session)):
    return settings_manager.update(session, body)


@router.post("/advisor/messages/{message_id}/reflect", response_model=JobItem, status_code=202)
def reflect_on_answer(message_id: int, body: ReflectRequest, session: Session = Depends(get_session)):
    """Explicit "learn from this consultation": proposals only, reviewed in the approvals view."""
    from app.modules.database.model.advisor_runtime import AdvisorRun
    run_id = session.scalar(select(AdvisorRun.id).where(AdvisorRun.assistant_message_id == message_id))
    if run_id is None:
        raise HTTPException(404, "학습할 수 있는 상담 답변을 찾을 수 없습니다")
    try:
        job = reflection.enqueue(session, request_id=body.request_id, source="run", run_id=run_id)
        session.commit()
        return job
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except AdvisorError:
        session.rollback()
        raise
    except ValueError as exc:
        session.rollback()
        raise HTTPException(409, str(exc)) from exc


@router.get("/agent/activity", response_model=AgentActivity)
def get_agent_activity(days: int = Query(30, ge=1, le=365), session: Session = Depends(get_session)):
    since = utcnow() - timedelta(days=days)
    outcomes = dict(session.execute(select(LLMUsageEvent.outcome, func.count()).where(
        LLMUsageEvent.created_at >= since).group_by(LLMUsageEvent.outcome)).all())
    tokens = session.execute(select(func.sum(LLMUsageEvent.input_tokens), func.sum(LLMUsageEvent.output_tokens))
                             .where(LLMUsageEvent.created_at >= since)).one()
    learned = dict(session.execute(select(PlaybookRevision.status, func.count()).where(
        PlaybookRevision.source == "advisor", PlaybookRevision.created_at >= since).group_by(PlaybookRevision.status)).all())
    uses = session.scalar(select(func.count()).select_from(PlaybookUsage).where(PlaybookUsage.created_at >= since)) or 0
    total = sum(outcomes.values())
    return AgentActivity(days=days, model_calls=total, failed_calls=total - outcomes.get("completed", 0),
                         input_tokens=tokens[0], output_tokens=tokens[1], playbook_uses=uses,
                         learning_proposals=sum(learned.values()),
                         learning_approved=learned.get("active", 0) + learned.get("superseded", 0),
                         learning_rejected=learned.get("rejected", 0), by_outcome=outcomes)
