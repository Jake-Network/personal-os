import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import AwareDatetime

from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.context.context_builder_manager import context_builder_manager
from app.modules.crud import (
    audit_log_handler,
    context_snapshot_handler,
    conversation_handler,
    message_handler,
    recommendation_handler,
)
from app.modules.database import get_session
from app.schema.advisor_schema import (
    AskRequest,
    ContextPreviewRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationItem,
    MessageItem,
    RecommendationFeedback,
    SummaryCreate, SummaryItem, ConversationLinkCreate, ConversationLinkItem,
)
from app.schema.context_schema import SnapshotCompareResponse, SnapshotResponse

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


def _conversation(session: Session, conversation_id: int):
    try:
        return advisor_manager.get_conversation(session, conversation_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/conversations", response_model=list[ConversationItem])
def list_conversations(q: str | None = Query(default=None, max_length=200),
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       since: AwareDatetime | None = None, until: AwareDatetime | None = None, domain: str | None = None,
                       company: str | None = None, project: int | None = None, decision: int | None = None,
                       session: Session = Depends(get_session)):
    return conversation_handler.get_recent(session, q, limit, offset, since, until, domain, company, project, decision)


@router.post("/conversations", response_model=ConversationItem, status_code=201)
def create_conversation(body: ConversationCreate, session: Session = Depends(get_session)):
    return advisor_manager.create_conversation(session, body.title, body.domain)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, limit: int = Query(100, ge=1, le=200),
                     before_id: int | None = None, session: Session = Depends(get_session)):
    conv = _conversation(session, conversation_id)
    return ConversationDetail(
        **ConversationItem.model_validate(conv).model_dump(),
        messages=[MessageItem.model_validate(m) for m in message_handler.page(session, conv.id, limit, before_id)],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, session: Session = Depends(get_session)):
    try:
        advisor_manager.delete_conversation(session, conversation_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/messages/search", response_model=list[MessageItem])
def search_messages(q: str = Query(min_length=1, max_length=200), limit: int = Query(50, ge=1, le=200),
                    offset: int = Query(0, ge=0), since: AwareDatetime | None = None, until: AwareDatetime | None = None,
                    conversation_id: int | None = None, session: Session = Depends(get_session)):
    return message_handler.search(session, q, limit, offset, since, until, conversation_id)


@router.post("/conversations/{conversation_id}/messages")
async def ask(conversation_id: int, body: AskRequest, session: Session = Depends(get_session)):
    """Server-sent events: context → delta* → done | error."""
    conv = _conversation(session, conversation_id)

    async def events():
        async for event in advisor_manager.ask(session, conv, body.message, body.options()):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/context/preview")
def preview_context(body: ContextPreviewRequest, session: Session = Depends(get_session)):
    """Context Inspector before sending: what would be shared, from which records, how fresh."""
    conv = _conversation(session, body.conversation_id) if body.conversation_id else None
    return advisor_manager.preview(session, body.message, conv, body.options())


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
def get_snapshot(snapshot_id: str, session: Session = Depends(get_session)):
    snap = context_snapshot_handler.get(session, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot not found")
    return SnapshotResponse(
        context_snapshot_id=snap.id, conversation_id=snap.conversation_id, generated_at=snap.generated_at,
        context_categories=snap.context_categories, excluded_categories=snap.excluded_categories,
        record_references=snap.record_references, source_updated_at=snap.source_updated_at,
        data_quality_flags=snap.data_quality_flags, payload=snap.payload,
    )


@router.get("/snapshots/{snapshot_id}/compare", response_model=SnapshotCompareResponse)
def compare_snapshot(snapshot_id: str, session: Session = Depends(get_session)):
    """Separate the data a past answer relied on from what is stored now."""
    snap = context_snapshot_handler.get(session, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot not found")
    now = datetime.now(UTC)
    changed, unchanged = context_builder_manager.compare_with_current(session, snap, now)
    return SnapshotCompareResponse(context_snapshot_id=snap.id, snapshot_generated_at=snap.generated_at,
                                   compared_at=now, changed_sections=changed, unchanged_sections=unchanged)


@router.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(snapshot_id: str, session: Session = Depends(get_session)):
    snap = context_snapshot_handler.get(session, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot not found")
    from sqlalchemy import update
    from app.modules.database.model import AdvisorMessage
    session.execute(update(AdvisorMessage).where(AdvisorMessage.context_snapshot_id == snapshot_id).values(context_purged=True))
    context_snapshot_handler.delete(session, snap)
    audit_log_handler.record(session, "user", "snapshot.delete", f"context_snapshots:{snapshot_id}")
    session.commit()


@router.post("/recommendations", status_code=201)
def rate_recommendation(body: RecommendationFeedback, session: Session = Depends(get_session)):
    if message_handler.get(session, body.message_id) is None:
        raise HTTPException(404, "message not found")
    rec = recommendation_handler.create(session, body)
    session.commit()
    return {"id": rec.id}


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageItem])
def message_page(conversation_id: int, limit: int = Query(100, ge=1, le=200),
                 before_id: int | None = None, session: Session = Depends(get_session)):
    _conversation(session, conversation_id)
    return message_handler.page(session, conversation_id, limit, before_id)


@router.get("/conversations/{conversation_id}/summaries", response_model=list[SummaryItem])
def list_summaries(conversation_id: int, session: Session = Depends(get_session)):
    from app.modules.advisor.memory_history_manager import memory_history_manager
    _conversation(session, conversation_id)
    return memory_history_manager.summaries(session, conversation_id)


@router.post("/conversations/{conversation_id}/summaries", response_model=SummaryItem, status_code=201)
def summarize_conversation(conversation_id: int, body: SummaryCreate, session: Session = Depends(get_session)):
    from app.modules.advisor.memory_history_manager import memory_history_manager
    _conversation(session, conversation_id)
    try:
        return memory_history_manager.summarize(session, conversation_id, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/history/index")
async def rebuild_history_index(after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
                                session: Session = Depends(get_session)):
    from app.modules.advisor.memory_history_manager import index_history
    try:
        return await index_history(session, after_id, limit)
    except Exception as exc:
        session.rollback()
        raise HTTPException(503, "로컬 임베딩 색인을 만들 수 없습니다. 키워드 검색은 계속 사용할 수 있습니다.") from exc


@router.get("/conversations/{conversation_id}/links", response_model=list[ConversationLinkItem])
def conversation_links(conversation_id: int, session: Session = Depends(get_session)):
    from sqlalchemy import select
    from app.modules.database.model import ConversationLink
    _conversation(session, conversation_id)
    return list(session.scalars(select(ConversationLink).where(ConversationLink.conversation_id == conversation_id)))


@router.post("/conversations/{conversation_id}/links", response_model=ConversationLinkItem, status_code=201)
def link_conversation(conversation_id: int, body: ConversationLinkCreate, session: Session = Depends(get_session)):
    from sqlalchemy import select
    from app.modules.database.model import ConversationLink, CareerRecord, DecisionJournalEntry
    _conversation(session, conversation_id)
    if body.kind in {"project", "decision"}:
        try:
            target_id = int(body.target)
        except ValueError as exc:
            raise HTTPException(422, "project and decision targets require a record ID") from exc
        target = session.get(CareerRecord if body.kind == "project" else DecisionJournalEntry, target_id)
        if target is None or body.kind == "project" and target.kind != "project":
            raise HTTPException(404, "linked record not found")
    target_value = str(target_id) if body.kind in {"project", "decision"} else body.target.strip()
    if not target_value:
        raise HTTPException(422, "company is required")
    existing = session.scalar(select(ConversationLink).where(ConversationLink.conversation_id == conversation_id,
        ConversationLink.kind == body.kind, ConversationLink.target == target_value))
    if existing:
        return existing
    link = ConversationLink(conversation_id=conversation_id, kind=body.kind, target=target_value)
    session.add(link)
    session.commit()
    return link


@router.delete("/conversations/{conversation_id}/links/{link_id}", status_code=204)
def unlink_conversation(conversation_id: int, link_id: int, session: Session = Depends(get_session)):
    from app.modules.database.model import ConversationLink
    _conversation(session, conversation_id)
    link = session.get(ConversationLink, link_id)
    if link is None or link.conversation_id != conversation_id:
        raise HTTPException(404, "link not found")
    session.delete(link)
    session.commit()
