from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.modules.career.career_manager import career_manager
from app.modules.crud.career_record_handler import career_record_handler
from app.modules.database import get_session
from app.schema.career_schema import CareerKind, CareerRecordCreate, CareerRecordItem, TimelinePage

router = APIRouter(prefix="/api", tags=["career"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/career/records", response_model=list[CareerRecordItem])
def list_career_records(kind: CareerKind | None = None, company: str | None = None,
                        project_id: int | None = Query(None, gt=0), skill: str | None = None,
                        session: Session = Depends(get_session)):
    return _call(career_manager.list, session, kind, company, project_id, skill)


@router.get("/career/records/{record_id}", response_model=CareerRecordItem)
def get_career_record(record_id: int, session: Session = Depends(get_session)):
    return _call(career_record_handler.get, session, record_id)


@router.post("/career/records", response_model=CareerRecordItem, status_code=201)
def create_career_record(body: CareerRecordCreate, session: Session = Depends(get_session)):
    return _call(career_manager.save, session, body)


@router.put("/career/records/{record_id}", response_model=CareerRecordItem)
def update_career_record(record_id: int, body: CareerRecordCreate, session: Session = Depends(get_session)):
    return _call(career_manager.save, session, body, record_id)


@router.post("/career/records/{record_id}/confirm", response_model=CareerRecordItem)
def confirm_career_record(record_id: int, session: Session = Depends(get_session)):
    return _call(career_manager.confirm, session, record_id)


@router.delete("/career/records/{record_id}", status_code=204)
def delete_career_record(record_id: int, session: Session = Depends(get_session)):
    return _call(career_manager.delete, session, record_id)


@router.get("/timeline", response_model=TimelinePage)
def get_timeline(start: date | None = None, end: date | None = None,
                 domain: Literal["career", "decisions", "goals", "finance"] | None = None,
                 company: str | None = None, project_id: int | None = Query(None, gt=0),
                 offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                 session: Session = Depends(get_session)):
    """Occurrence interval is [start, end); year/month-only facts preserve their precision."""
    if start and end and end <= start:
        raise HTTPException(422, "종료 범위는 시작 범위보다 늦어야 합니다")
    return _call(career_manager.timeline, session, start=start, end=end, domain=domain,
                 company=company, project_id=project_id, offset=offset, limit=limit)
