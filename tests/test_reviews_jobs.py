from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.crud import review_jobs_handler as handler
from app.modules.database.model.advisor import DecisionJournalEntry
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob, PeriodReview
from app.modules.jobs import job_manager
from app.modules.reviews import review_manager
from app.schema.review_jobs_schema import OutcomeCreate, PeriodReviewCreate, ReviewJobCreate


def body(**kwargs):
    return ReviewJobCreate(request_id="test-review", period="month", start_on="2026-10-01", end_on="2026-11-01", **kwargs)


def test_outcomes_preserve_expectations_and_each_review(session):
    decision = DecisionJournalEntry(title="새 직장", choice="지원", rationale="성장", expected_outcome="면접 경험")
    session.add(decision)
    session.commit()
    first = review_manager.add_outcome(session, decision.id, OutcomeCreate(actual_outcome="서류 통과"))
    session.commit()
    decision.expected_outcome = "변경된 기대"
    review_manager.add_outcome(session, decision.id, OutcomeCreate(actual_outcome="최종 면접", lessons="연습"))
    session.commit()
    records = handler.outcomes(session, decision.id)
    assert len(records) == 2
    assert records[0].expected_outcome == "면접 경험"
    assert first.actual_outcome == "서류 통과"


def test_jobs_require_opt_in_and_request_ids_are_stable(session):
    disabled = job_manager.enqueue(session, body())
    assert not job_manager.process_one(session)
    assert job_manager.enqueue(session, body()).id == disabled.id
    with pytest.raises(ValueError):
        job_manager.enqueue(session, body(enabled=True))
    assert session.scalar(select(PeriodReview)) is None


def test_job_result_commits_once_and_confirmation_is_explicit(session):
    job = job_manager.enqueue(session, body(enabled=True))
    assert job_manager.process_one(session)
    session.refresh(job)
    assert job.status == "completed"
    assert not job_manager.process_one(session)
    records = list(session.scalars(select(PeriodReview)))
    assert len(records) == 1
    assert records[0].status == "draft"
    assert "financial_snapshot_coverage_incomplete" in records[0].evidence["data_quality_flags"]
    assert review_manager.confirm(session, records[0].id, "직접 확인한 회고").status == "confirmed"
    with pytest.raises(ValueError):
        review_manager.confirm(session, records[0].id, "덮어쓰기")


def test_claim_lease_recovery_and_exhaustion(session):
    job = job_manager.enqueue(session, body(enabled=True))
    # Exercise a known due instant rather than racing a second wall-clock sample.
    now = job.run_after + timedelta(seconds=1)
    first = handler.claim(session, "worker-one", now)
    session.commit()
    assert first is not None, (job.status, job.run_after, now, job.lease_owner)
    assert first.id == job.id
    assert handler.claim(session, "worker-two", now) is None
    recovered = handler.claim(session, "worker-two", now + timedelta(minutes=6))
    assert recovered.id == job.id
    assert recovered.attempts == 2
    session.commit()
    recovered.attempts = recovered.max_attempts
    session.commit()
    handler.expire_exhausted(session, now + timedelta(minutes=12))
    session.commit()
    session.refresh(job)
    assert job.status == "failed"
    job_manager.retry(session, job.id)
    session.refresh(job)
    assert job.status == "pending" and job.attempts == 0


def test_invalid_job_fails_with_bounded_retries_and_sanitized_error(session):
    job = job_manager.enqueue(session, body(enabled=True))
    job.kind = "external_llm"
    job.max_attempts = 1
    session.commit()
    job_manager.process_one(session)
    session.refresh(job)
    assert job.status == "failed"
    assert job.last_error == "ValueError"
    assert session.scalar(select(PeriodReview)) is None


def test_review_period_bounds_and_idempotency(session):
    review = review_manager.build_draft(session, PeriodReviewCreate.model_validate(body().model_dump()))
    session.commit()
    assert review_manager.build_draft(session, PeriodReviewCreate.model_validate(body().model_dump())).id == review.id
    changed = PeriodReviewCreate(request_id="test-review", period="year", start_on="2026-01-01", end_on="2027-01-01")
    with pytest.raises(ValueError):
        review_manager.build_draft(session, changed)


def test_crash_after_output_creation_reuses_same_draft(session):
    job = job_manager.enqueue(session, body(enabled=True))
    now = utcnow()
    handler.claim(session, "crashed-worker", now - timedelta(minutes=6))
    # Reproduce a pre-existing output from a prior attempt; the request id binds it.
    review = review_manager.build_draft(session, PeriodReviewCreate.model_validate(job.payload))
    job.status = "running"
    job.lease_owner = "crashed-worker"
    job.lease_until = now - timedelta(seconds=1)
    session.commit()
    assert job_manager.process_one(session)
    session.refresh(job)
    assert job.status == "completed"
    assert job.result == {"review_id": review.id}
    assert len(list(session.scalars(select(PeriodReview)))) == 1


def test_api_outcomes_and_review_validation(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.modules.database import get_session
    from app.router import reviews_router, jobs_router

    app = FastAPI()
    app.include_router(reviews_router.router)
    app.include_router(jobs_router.router)
    app.dependency_overrides[get_session] = lambda: session
    decision = DecisionJournalEntry(title="합성 결정", choice="A", rationale="합성 이유")
    session.add(decision)
    session.commit()
    with TestClient(app) as client:
        path = f"/api/decisions/{decision.id}/reviews"
        assert client.post(path, json={"actual_outcome": ""}).status_code == 422
        assert client.post(path, json={"actual_outcome": "첫 결과"}).status_code == 201
        assert client.post(path, json={"actual_outcome": "후속 결과"}).status_code == 201
        assert len(client.get(path).json()) == 2
        assert client.get('/api/decisions/99999/reviews').status_code == 404
        draft_body = body().model_dump(mode="json")
        draft_body.pop('enabled')
        draft_body.pop('run_after')
        draft = client.post('/api/reviews', json=draft_body)
        assert draft.status_code == 201
        confirm_path = f"/api/reviews/{draft.json()['id']}/confirm"
        assert client.post(confirm_path, json={"content": "직접 확인"}).status_code == 200
        assert client.post(confirm_path, json={"content": "두 번째 확정"}).status_code == 409
        assert client.post('/api/jobs/period-review', json=body().model_dump(mode="json")).json()['enabled'] is False


def test_schedules_opt_in_calendar_periods_and_replay(session):
    from datetime import UTC, datetime
    from app.modules.database.model.review_jobs import JobSchedule

    due = datetime(2026, 10, 1, tzinfo=UTC)
    schedule = JobSchedule(name="월간", cadence="month", enabled=False, next_run_at=due)
    session.add(schedule)
    session.commit()
    job_manager.enqueue_schedules(session, due)
    assert session.scalar(select(BackgroundJob)) is None
    schedule.enabled = True
    session.commit()
    job_manager.enqueue_schedules(session, due)
    first = session.scalar(select(BackgroundJob))
    assert first.payload['start_on'] == '2026-09-01'
    assert first.payload['end_on'] == '2026-10-01'
    job_manager.enqueue_schedules(session, due)
    assert len(list(session.scalars(select(BackgroundJob)))) == 1
    # Missed months are recovered in order rather than silently skipped.
    job_manager.enqueue_schedules(session, datetime(2027, 1, 1, tzinfo=UTC))
    assert len(list(session.scalars(select(BackgroundJob)))) == 2


def test_review_freezes_career_and_historical_financial_evidence(session):
    from datetime import date
    from app.modules.database.model.career import CareerRecord
    from app.modules.database.model.portfolio import MonthlySnapshot
    from app.modules.database.model.domain import Goal
    project = CareerRecord(kind='project', title='합성 프로젝트', started_on='2026', status='confirmed', outcome='시험 결과')
    goal = Goal(title='합성 목표', category='career', status='active')
    session.add_all([project, goal, MonthlySnapshot(month=date(2026, 9, 1), revision=1,
        reason='합성 과거 근거', payload={'net_worth': '12345', 'data_quality_flags': []})])
    session.commit()
    request = PeriodReviewCreate(request_id='historical', period='month', start_on='2026-09-01', end_on='2026-10-01', goal_ids=[goal.id], project_ids=[project.id])
    draft = review_manager.build_draft(session, request)
    session.commit()
    assert draft.evidence['financial_snapshots'][0]['net_worth'] == '12345'
    assert draft.evidence['career_records'][0]['started_on'] == '2026'
    assert draft.goal_ids == [goal.id]
    project.outcome = '현재 바뀐 결과'
    goal.status = 'done'
    session.commit()
    assert draft.evidence['career_records'][0]['outcome'] == '시험 결과'
    assert draft.evidence['goals_at_generation'][0]['status'] == 'active'


def test_legacy_review_keeps_history_and_latest_projection(session):
    from app.modules.advisor.memory_manager import decision_journal_manager
    from app.schema.advisor_schema import DecisionReview
    decision = DecisionJournalEntry(title='synthetic', choice='A', rationale='B')
    session.add(decision)
    session.commit()
    decision_journal_manager.review(session, decision.id, DecisionReview(actual_outcome='first'))
    decision_journal_manager.review(session, decision.id, DecisionReview(actual_outcome='second'))
    assert [record.actual_outcome for record in handler.outcomes(session, decision.id)] == ['first', 'second']
    assert decision.actual_outcome == 'second'
    review_manager.add_outcome(session, decision.id, OutcomeCreate(actual_outcome='third via new API'))
    session.commit()
    session.refresh(decision)
    assert decision.actual_outcome == 'third via new API'


def test_market_refresh_requires_live_consent_and_deduplicates_bucket(session, monkeypatch):
    from app.modules.crud import app_setting_handler
    from app.modules.portfolio import market_data_manager
    calls = []
    monkeypatch.setattr(market_data_manager, 'refresh', lambda session: calls.append('public_quotes') or {'refresh_after_seconds': 300})
    now = utcnow()
    job_manager.enqueue_schedules(session, now)
    assert session.scalar(select(BackgroundJob)) is None
    app_setting_handler.set_value(session, 'jobs.quote_refresh', {'enabled': True})
    session.commit()
    job_manager.enqueue_schedules(session, now)
    job_manager.enqueue_schedules(session, now)
    assert len(list(session.scalars(select(BackgroundJob)))) == 1
    assert job_manager.process_one(session)
    assert calls == ['public_quotes']
    job_manager.enqueue_schedules(session, now + timedelta(minutes=5))
    app_setting_handler.set_value(session, 'jobs.quote_refresh', {'enabled': False})
    session.commit()
    job_manager.process_one(session, now + timedelta(minutes=5))
    assert calls == ['public_quotes']
    assert session.scalar(select(BackgroundJob).order_by(BackgroundJob.id.desc())).status == 'cancelled'


def test_review_migration_preserves_legacy_outcome_and_unknown_time(postgres_url):
    from alembic import command
    from sqlalchemy import create_engine, inspect, text
    from app.modules.database.legacy_adoption import migration_config

    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        config = migration_config(connection)
        command.upgrade(config, '0007_document_job_attempts')
        connection.execute(text("INSERT INTO decision_journal (title,decided_at,alternatives,choice,rationale,actual_outcome) VALUES ('synthetic','2026-01-01','[]','A','B','preserved')"))
        command.upgrade(config, '0008_reviews_jobs')
        assert connection.execute(text('SELECT actual_outcome, reviewed_at FROM decision_reviews')).one() == ('preserved', None)
        assert 'job_schedules' in inspect(connection).get_table_names(schema=inspect(connection).default_schema_name)
        command.downgrade(config, '0007_document_job_attempts')
        assert connection.execute(text('SELECT actual_outcome FROM decision_journal')).scalar() == 'preserved'
    engine.dispose()


def test_worker_shutdown_waits_for_owned_thread_transaction(monkeypatch):
    import asyncio
    from threading import Event

    started, release, finished = Event(), Event(), Event()

    def controlled_tick(_database):
        started.set()
        assert release.wait(5)
        finished.set()

    monkeypatch.setattr(job_manager, "_worker_tick", controlled_tick)

    async def exercise():
        running = asyncio.create_task(job_manager._run_tick(object()))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            running.cancel()
            await asyncio.sleep(0)
            assert not running.done(), "shutdown returned while DB work still ran in a thread"
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert finished.is_set()

    asyncio.run(exercise())
