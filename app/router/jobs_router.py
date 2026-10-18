from fastapi import APIRouter, Depends, HTTPException, Query
from app.schema.review_jobs_schema import QuoteRefreshConsent
from app.modules.crud import app_setting_handler

from sqlalchemy.orm import Session
from app.modules.database.model.review_jobs import BackgroundJob, JobSchedule
from app.modules.database.model.base import utcnow
from app.schema.review_jobs_schema import ScheduleActivation, ScheduleCreate, ScheduleItem
from sqlalchemy import select, update


from app.modules.crud import review_jobs_handler as handler
from app.modules.database import get_session
from app.modules.jobs import job_manager
from app.schema.review_jobs_schema import JobItem, ReviewJobCreate

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobItem])
def list_background_jobs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: Session = Depends(get_session)):
    return handler.jobs(session, limit, offset)


@router.post("/period-review", response_model=JobItem, status_code=201)
def create_review_job(body: ReviewJobCreate, session: Session = Depends(get_session)):
    try:
        return job_manager.enqueue(session, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobItem)
def retry_background_job(job_id: int, session: Session = Depends(get_session)):
    try:
        return job_manager.retry(session, job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc




@router.get("/schedules", response_model=list[ScheduleItem])
def list_job_schedules(session: Session = Depends(get_session)):
    return list(session.scalars(select(JobSchedule).order_by(JobSchedule.id)))


@router.post("/schedules", response_model=ScheduleItem, status_code=201)
def create_job_schedule(body: ScheduleCreate, session: Session = Depends(get_session)):
    schedule = JobSchedule(**body.model_dump(), next_run_at=utcnow())
    session.add(schedule)
    session.commit()
    return schedule


@router.patch("/schedules/{schedule_id}", response_model=ScheduleItem)
def activate_job_schedule(schedule_id: int, body: ScheduleActivation, session: Session = Depends(get_session)):
    schedule = session.get(JobSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "주기 작업을 찾을 수 없습니다")
    schedule.enabled = body.enabled
    if not body.enabled:
        # Revocation also stops already-enqueued work that has not started.
        session.execute(update(BackgroundJob).where(
            BackgroundJob.request_id.like(f"schedule:{schedule.id}:%"),
            BackgroundJob.status == "pending").values(enabled=False))
    session.commit()
    return schedule




@router.get("/quote-refresh", response_model=QuoteRefreshConsent)
def get_quote_refresh_consent(session: Session = Depends(get_session)):
    return app_setting_handler.get_value(session, "jobs.quote_refresh") or {"enabled": False}


@router.put("/quote-refresh", response_model=QuoteRefreshConsent)
def set_quote_refresh_consent(body: QuoteRefreshConsent, session: Session = Depends(get_session)):
    app_setting_handler.set_value(session, "jobs.quote_refresh", body.model_dump())
    if not body.enabled:
        session.execute(update(BackgroundJob).where(BackgroundJob.kind == "market_quote_refresh",
                                                   BackgroundJob.status == "pending").values(enabled=False))
    session.commit()
    return body
