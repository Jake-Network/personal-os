"""Concurrent approvals of one proposal must apply its action exactly once."""
import threading
import time
from datetime import UTC, datetime

import pytest

from app.modules.advisor import proposal_manager as pm
from app.modules.database import db
from app.modules.database.model import AdvisorConversation, AuditLog, Base, CalendarEvent, ProposedAction, Task
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
def shared_db(tmp_path):
    # Real concurrency needs separate connections: a file DB, or PostgreSQL when configured.
    url = TEST_DATABASE_URL if TEST_DATABASE_URL.startswith("postgresql") else f"sqlite:///{tmp_path / 'race.db'}"
    db.init(url)
    Base.metadata.drop_all(db.engine)
    db.create_schema()
    with db.session() as s:
        proposal = ProposedAction(action="create_task", payload={"title": "한 번만 실행"}, status="pending")
        s.add(proposal)
        s.commit()
        yield proposal.id
    db.engine.dispose()


def race(monkeypatch, proposal_id, decisions):
    original = pm.ProposalManager._apply

    def slow_apply(session, action, payload):
        ref = original(session, action, payload)
        time.sleep(0.3)  # widen the window between "read pending" and "commit"
        return ref

    monkeypatch.setattr(pm.ProposalManager, "_apply", staticmethod(slow_apply))
    barrier = threading.Barrier(len(decisions))
    results: list[str] = []

    def worker(decide):
        with db.session() as s:
            barrier.wait()
            try:
                decide(s, proposal_id)
                results.append("ok")
            except pm.ProposalError:
                results.append("conflict")

    threads = [threading.Thread(target=worker, args=(d,)) for d in decisions]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return sorted(results)


def test_concurrent_approvals_create_one_task(shared_db, monkeypatch):
    manager = pm.proposal_manager
    assert race(monkeypatch, shared_db, [manager.approve, manager.approve]) == ["conflict", "ok"]
    with db.session() as s:
        assert s.query(Task).count() == 1
        assert s.get(ProposedAction, shared_db).status == "approved"
        assert s.query(AuditLog).filter(AuditLog.action == "approve.create_task").count() == 1


def test_approve_and_reject_race_has_one_winner(shared_db, monkeypatch):
    manager = pm.proposal_manager
    assert race(monkeypatch, shared_db, [manager.approve, manager.reject]) == ["conflict", "ok"]
    with db.session() as s:
        status = s.get(ProposedAction, shared_db).status
        assert (status, s.query(Task).count()) in {("approved", 1), ("rejected", 0)}


def test_failed_apply_returns_proposal_to_pending(shared_db):
    with db.session() as s:
        s.get(ProposedAction, shared_db).payload = {"title": ""}  # invalid: title required
        s.commit()
        with pytest.raises(pm.ProposalError, match="title required"):
            pm.proposal_manager.approve(s, shared_db)
    with db.session() as s:
        assert s.get(ProposedAction, shared_db).status == "pending"
        assert s.query(Task).count() == 0


@pytest.mark.parametrize("changes", [
    {"starts_at": "2026-10-22T10:00:00+09:00"},
    {"ends_at": None},
    {"starts_at": "2026-10-22T10:00:00+09:00", "ends_at": "2026-10-22T10:00:00+09:00"},
])
def test_legacy_all_day_time_proposal_is_rejected_without_writes(session, changes):
    event = CalendarEvent(title="종일 일정", all_day=True,
                          starts_at=datetime(2026, 10, 21, 15, tzinfo=UTC),
                          ends_at=datetime(2026, 10, 22, 15, tzinfo=UTC))
    session.add(event)
    session.flush()
    proposal = ProposedAction(action="calendar_update", status="pending", payload={
        "event_id": event.id, **changes, "_precondition": pm._fingerprint(event),
    })
    session.add(proposal)
    session.commit()

    with pytest.raises(pm.ProposalError, match="all-day"):
        pm.proposal_manager.approve(session, proposal.id)

    session.refresh(event)
    assert event.all_day is True
    assert event.starts_at == datetime(2026, 10, 21, 15, tzinfo=UTC)
    assert event.ends_at == datetime(2026, 10, 22, 15, tzinfo=UTC)
    assert session.get(ProposedAction, proposal.id).status == "pending"
    assert session.query(AuditLog).filter(AuditLog.action == "approve.calendar_update").count() == 0


@pytest.mark.parametrize("changes", [
    {"starts_at": "2026-10-22T10:00:00+09:00"},
    {"ends_at": None},
])
def test_all_day_time_proposal_is_not_recorded(session, changes):
    event = CalendarEvent(title="종일 일정", all_day=True,
                          starts_at=datetime(2026, 10, 21, 15, tzinfo=UTC),
                          ends_at=datetime(2026, 10, 22, 15, tzinfo=UTC))
    conversation = AdvisorConversation(title="종일 일정 상담")
    session.add_all([event, conversation])
    session.flush()

    with pytest.raises(pm.ProposalError, match="all-day"):
        pm.proposal_manager.record(session, conversation.id, 0, [{
            "action": "calendar_update", "payload": {"event_id": event.id, **changes},
        }], [])

    assert session.query(ProposedAction).count() == 0
    assert session.query(AuditLog).count() == 0


@pytest.mark.parametrize("all_day", [False, True])
def test_calendar_title_proposal_preserves_schedule(session, all_day):
    starts_at = datetime(2026, 10, 21, 15, tzinfo=UTC)
    ends_at = datetime(2026, 10, 22, 15, tzinfo=UTC)
    event = CalendarEvent(title="기존 일정", all_day=all_day, starts_at=starts_at, ends_at=ends_at)
    conversation = AdvisorConversation(title="일정 상담")
    session.add_all([event, conversation])
    session.flush()
    proposals, _ = pm.proposal_manager.record(session, conversation.id, 0, [{
        "action": "calendar_update", "payload": {"event_id": event.id, "title": "변경한 일정"},
    }], [])
    session.commit()

    pm.proposal_manager.approve(session, proposals[0].id)

    session.refresh(event)
    assert event.title == "변경한 일정"
    assert event.all_day is all_day
    assert event.starts_at == starts_at
    assert event.ends_at == ends_at
