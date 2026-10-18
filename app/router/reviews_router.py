from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.modules.crud import review_jobs_handler as handler
from app.modules.database import get_session
from app.modules.database.model.advisor import DecisionJournalEntry
from app.modules.reviews import review_manager
from app.schema.review_jobs_schema import OutcomeCreate, OutcomeItem, PeriodReviewCreate, PeriodReviewItem, ReviewConfirm

router = APIRouter(prefix="/api", tags=["reviews"])


@router.get("/decisions/{decision_id}/reviews", response_model=list[OutcomeItem])
def list_decision_reviews(decision_id: int, session: Session = Depends(get_session)):
    if session.get(DecisionJournalEntry, decision_id) is None:
        raise HTTPException(404, "결정을 찾을 수 없습니다")
    return handler.outcomes(session, decision_id)


@router.post("/decisions/{decision_id}/reviews", response_model=OutcomeItem, status_code=201)
def create_decision_review(decision_id: int, body: OutcomeCreate, session: Session = Depends(get_session)):
    try:
        record = review_manager.add_outcome(session, decision_id, body)
        session.commit()
        return record
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/reviews", response_model=list[PeriodReviewItem])
def list_period_reviews(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: Session = Depends(get_session)):
    return handler.reviews(session, limit, offset)


@router.post("/reviews", response_model=PeriodReviewItem, status_code=201)
def create_period_review(body: PeriodReviewCreate, session: Session = Depends(get_session)):
    try:
        record = review_manager.build_draft(session, body)
        session.commit()
        return record
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/reviews/{review_id}/confirm", response_model=PeriodReviewItem)
def confirm_period_review(review_id: int, body: ReviewConfirm, session: Session = Depends(get_session)):
    try:
        return review_manager.confirm(session, review_id, body.content)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
