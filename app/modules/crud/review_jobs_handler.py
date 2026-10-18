"""Persistence for reviews and job claims; transaction ownership stays with callers."""
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob, DecisionReviewRecord, PeriodReview


def outcomes(session: Session, decision_id: int):
    return list(session.scalars(select(DecisionReviewRecord).where(
        DecisionReviewRecord.decision_id == decision_id).order_by(DecisionReviewRecord.reviewed_at, DecisionReviewRecord.id)))


def reviews(session: Session, limit: int = 50, offset: int = 0):
    return list(session.scalars(select(PeriodReview).order_by(PeriodReview.created_at.desc(), PeriodReview.id.desc()).limit(limit).offset(offset)))


def jobs(session: Session, limit: int = 50, offset: int = 0):
    return list(session.scalars(select(BackgroundJob).order_by(BackgroundJob.id.desc()).limit(limit).offset(offset)))


def by_request(session: Session, model, request_id: str):
    return session.scalar(select(model).where(model.request_id == request_id))


def claim(session: Session, owner: str, now=None):
    now = now or utcnow()
    eligible = and_(BackgroundJob.enabled.is_(True), BackgroundJob.attempts < BackgroundJob.max_attempts,
                    BackgroundJob.run_after <= now,
                    or_(BackgroundJob.status == "pending", and_(BackgroundJob.status == "running", BackgroundJob.lease_until <= now)))
    job_id = session.scalar(select(BackgroundJob.id).where(eligible).order_by(BackgroundJob.run_after, BackgroundJob.id).limit(1))
    if job_id is None:
        return None
    changed = session.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, eligible).values(
        status="running", lease_owner=owner, lease_until=now + timedelta(minutes=5), attempts=BackgroundJob.attempts + 1))
    if changed.rowcount != 1:
        return None
    session.flush()
    return session.get(BackgroundJob, job_id, populate_existing=True)


def expire_exhausted(session: Session, now):
    session.execute(update(BackgroundJob).where(
        BackgroundJob.status == "running", BackgroundJob.lease_until <= now,
        BackgroundJob.attempts >= BackgroundJob.max_attempts).values(
            status="failed", lease_owner=None, lease_until=None, last_error="attempts_exhausted"))
