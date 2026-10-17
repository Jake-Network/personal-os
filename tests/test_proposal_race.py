"""Concurrent approvals of one proposal must apply its action exactly once."""
import threading
import time

import pytest

from app.modules.advisor import proposal_manager as pm
from app.modules.database import db
from app.modules.database.model import AuditLog, Base, ProposedAction, Task
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
