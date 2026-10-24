"""Exercise the learning worker's SQL lease transitions on either supported test database."""
from datetime import timedelta

from sqlalchemy import func, select

from app.modules.agent import reflection
from app.modules.database import db
from app.modules.database.model import InboxItem
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob


def test_expired_learning_job_is_failed_and_notified_once(session):
    job = BackgroundJob(request_id='expired-learning', kind='advisor_reflection', enabled=True, status='running',
        lease_owner='old-worker', lease_until=utcnow()-timedelta(seconds=1), payload={})
    session.add(job)
    session.commit()
    assert reflection.claim(session, 'new-worker') is None
    session.commit()
    session.refresh(job)
    assert (job.status, job.last_error) == ('failed', 'interrupted')
    assert job.completed_at is not None
    assert reflection.claim(session, 'new-worker') is None
    session.commit()
    assert session.scalar(select(func.count()).select_from(InboxItem).where(InboxItem.kind=='job_failed')) == 1


def test_lease_deadline_and_owner_fence_heartbeat_and_finish(session):
    job = BackgroundJob(request_id='learning-lease', kind='advisor_reflection', enabled=True,
        run_after=utcnow(), payload={})
    session.add(job)
    session.commit()
    claimed = reflection.claim(session, 'current-worker')
    assert claimed.id == job.id
    session.commit()
    assert not reflection._heartbeat(db, job.id, 'stale-worker')
    assert not reflection._finish(session, job.id, 'stale-worker', 'completed')
    session.rollback()
    job.lease_until = utcnow()-timedelta(seconds=1)
    session.commit()
    assert not reflection._heartbeat(db, job.id, 'current-worker')
    assert not reflection._finish(session, job.id, 'current-worker', 'completed')
    session.rollback()
    session.refresh(job)
    assert job.status == 'running' and job.lease_until < utcnow()
