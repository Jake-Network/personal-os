"""Durable opt-in local work with leases, bounded retries and idempotent outputs."""
import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud import review_jobs_handler as handler
from app.modules.crud import app_setting_handler
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob
from app.modules.reviews.review_manager import build_draft
from app.schema.review_jobs_schema import PeriodReviewCreate, ReviewJobCreate


def enqueue(session: Session, body: ReviewJobCreate):
    payload = PeriodReviewCreate.model_validate(body.model_dump()).model_dump(mode="json")
    existing = handler.by_request(session, BackgroundJob, body.request_id)
    if existing:
        if existing.payload != payload or existing.enabled != body.enabled:
            raise ValueError("같은 요청 ID에 다른 작업을 사용할 수 없습니다")
        return existing
    job = BackgroundJob(request_id=body.request_id, kind="period_review", payload=payload,
                        enabled=body.enabled, run_after=body.run_after or utcnow())
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return enqueue(session, body)
    session.commit()
    return job


def retry(session: Session, job_id: int):
    changed = session.execute(update(BackgroundJob).where(
        BackgroundJob.id == job_id, BackgroundJob.status == "failed").values(
            status="pending", attempts=0, run_after=utcnow(), last_error=None, lease_owner=None, lease_until=None))
    if changed.rowcount != 1:
        if session.get(BackgroundJob, job_id) is None:
            raise LookupError("작업을 찾을 수 없습니다")
        raise ValueError("실패한 작업만 재시도할 수 있습니다")
    session.commit()
    return session.get(BackgroundJob, job_id, populate_existing=True)


def process_one(session: Session, now=None) -> bool:
    now = now or utcnow()
    handler.expire_exhausted(session, now)
    owner = str(uuid4())
    job = handler.claim(session, owner, now)
    session.commit()  # Claim must survive crashes; output and completion commit together below.
    if job is None:
        return False
    job_id = job.id
    try:
        # No external LLM kind is registered. Quote refresh sends public tickers
        # only and repeats consent + current-principal checks immediately before I/O.
        if job.kind == "period_review":
            review = build_draft(session, PeriodReviewCreate.model_validate(job.payload))
            result = {"review_id": review.id}
        elif job.kind == "market_quote_refresh":
            session.expire_all()
            consent = app_setting_handler.get_value(session, "jobs.quote_refresh") or {}
            if not consent.get("enabled"):
                result = {"state": "consent_revoked"}
            else:
                from app.modules.portfolio import market_data_manager
                result = market_data_manager.refresh(session)
                if result.get("warning"):
                    raise RuntimeError("market_refresh_unavailable")
        else:
            raise ValueError("unsupported_job_kind")
        final_status = "cancelled" if result.get("state") == "consent_revoked" else "completed"
        changed = session.execute(update(BackgroundJob).where(
            BackgroundJob.id == job_id, BackgroundJob.status == "running", BackgroundJob.lease_owner == owner,
            BackgroundJob.lease_until > utcnow()).values(status=final_status, result=result,
                completed_at=utcnow(), lease_owner=None, lease_until=None, last_error=None))
        if changed.rowcount != 1:
            session.rollback()
            return True
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(BackgroundJob, job_id, populate_existing=True)
        if job and job.status == "running" and job.lease_owner == owner:
            session.execute(update(BackgroundJob).where(
                BackgroundJob.id == job_id, BackgroundJob.lease_owner == owner).values(
                    status="failed" if job.attempts >= job.max_attempts else "pending",
                    run_after=utcnow() + timedelta(seconds=30 * 2 ** (job.attempts - 1)),
                    # Never persist exception text: it may contain personal data or credentials.
                    last_error=type(exc).__name__, lease_owner=None, lease_until=None))
            session.commit()
    return True


async def process_pending(database, stop):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
            return
        except TimeoutError:
            pass
        try:
            await _run_tick(database)
        except Exception as exc:
            # A transient database outage must not silently kill the worker. Avoid
            # logging exception text, SQL parameters, or raw job payloads.
            logging.getLogger(__name__).warning("Local job worker retry: %s", type(exc).__name__)


async def _run_tick(database):
    # Cancelling to_thread does not stop its thread. Finish the owned transaction
    # before lifespan shutdown returns and another lifecycle can replace the DB.
    running = asyncio.create_task(asyncio.to_thread(_worker_tick, database))
    try:
        await asyncio.shield(running)
    except asyncio.CancelledError:
        await running
        raise


def enqueue_schedules(session: Session, now=None):
    """One atomic due-row advance and output insert; replay uses a stable request id."""
    from sqlalchemy import select
    from app.config import settings
    from app.modules.database.model.review_jobs import JobSchedule
    from app.modules.jobs.scheduling import completed_period

    now = now or utcnow()
    due = list(session.scalars(select(JobSchedule).where(
        JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now)))
    for schedule in due:
        # A delayed/restarted worker catches up one period per cycle, retaining each
        # due date instead of silently skipping months during downtime.
        start, end, following = completed_period(schedule.next_run_at, schedule.cadence, settings.timezone)
        changed = session.execute(update(JobSchedule).where(
            JobSchedule.id == schedule.id, JobSchedule.enabled.is_(True),
            JobSchedule.next_run_at == schedule.next_run_at).values(next_run_at=following))
        if changed.rowcount != 1:
            continue
        request_id = f"schedule:{schedule.id}:{start}:{end}"
        payload = PeriodReviewCreate(request_id=request_id, period=schedule.cadence, start_on=start, end_on=end).model_dump(mode="json")
        if handler.by_request(session, BackgroundJob, request_id) is None:
            session.add(BackgroundJob(request_id=request_id, kind="period_review", enabled=True, payload=payload,
                                      run_after=now))
    consent = app_setting_handler.get_value(session, "jobs.quote_refresh") or {}
    if consent.get("enabled"):
        request_id = f"quote-refresh:{int(now.timestamp()) // 300}"
        if handler.by_request(session, BackgroundJob, request_id) is None:
            session.add(BackgroundJob(request_id=request_id, kind="market_quote_refresh", enabled=True,
                                      payload={}, run_after=now))
    session.commit()


def _worker_tick(database):
    # Thread owns its own DB session; synchronous Google calls never block ASGI.
    with database.session() as session:
        enqueue_schedules(session)
        process_one(session)
