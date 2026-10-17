from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.modules.advisor.memory_manager import decision_journal_manager, memory_manager
from app.modules.database import get_session
from app.schema.advisor_schema import DecisionCreate, DecisionItem, DecisionReview, MemoryCreate, MemoryItem

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memories", response_model=list[MemoryItem])
def list_memories(status: str = "confirmed", session: Session = Depends(get_session)):
    return memory_manager.list(session, status)


@router.post("/memories", response_model=MemoryItem, status_code=201)
def create_memory(body: MemoryCreate, session: Session = Depends(get_session)):
    return memory_manager.create(session, body)


@router.post("/memories/{memory_id}/confirm", response_model=MemoryItem)
def confirm_memory(memory_id: int, session: Session = Depends(get_session)):
    return _decide(session, memory_id, True)


@router.post("/memories/{memory_id}/reject", response_model=MemoryItem)
def reject_memory(memory_id: int, session: Session = Depends(get_session)):
    return _decide(session, memory_id, False)


def _decide(session: Session, memory_id: int, confirm: bool):
    try:
        return memory_manager.decide(session, memory_id, confirm)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, session: Session = Depends(get_session)):
    try:
        memory_manager.delete(session, memory_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/decisions", response_model=list[DecisionItem])
def list_decisions(session: Session = Depends(get_session)):
    return decision_journal_manager.list(session)


@router.post("/decisions", response_model=DecisionItem, status_code=201)
def create_decision(body: DecisionCreate, session: Session = Depends(get_session)):
    return decision_journal_manager.create(session, body)


@router.post("/decisions/{entry_id}/review", response_model=DecisionItem)
def review_decision(entry_id: int, body: DecisionReview, session: Session = Depends(get_session)):
    try:
        return decision_journal_manager.review(session, entry_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
