"""Outcome learning pins the append-only event, rather than the latest projection."""
import asyncio

from test_agent_loop import env, package
from app.modules.agent import reflection
from app.modules.crud import app_setting_handler
from app.modules.agent.settings_manager import LEARNING_KEY
from app.modules.database.model import DecisionJournalEntry
from app.modules.database.model.review_jobs import BackgroundJob, DecisionReviewRecord


def test_each_queued_outcome_reflects_its_original_event_and_expected_value(env):
    client, database, provider = env
    with database.session() as session:
        app_setting_handler.set_value(session, LEARNING_KEY, {"enabled": True})
        decision = DecisionJournalEntry(title="합성 결정", choice="A", rationale="근거", conversation_id=1,
                                        expected_outcome="CHANGED_LATEST_EXPECTATION")
        session.add(decision)
        session.flush()
        first = DecisionReviewRecord(decision_id=decision.id, actual_outcome="FIRST_OUTCOME",
                                     expected_outcome="FIRST_EXPECTATION")
        session.add(first)
        session.flush()
        first_id = first.id
        reflection.after_outcome(session, decision.id, first.id)
        second = DecisionReviewRecord(decision_id=decision.id, actual_outcome="SECOND_OUTCOME",
                                      expected_outcome="SECOND_EXPECTATION")
        session.add(second)
        session.flush()
        reflection.after_outcome(session, decision.id, second.id)
        session.commit()
    provider.replies.extend([{"nothing_to_learn": True, "playbooks": [], "memories": []}] * 2)
    assert asyncio.run(reflection.process_one(database))
    assert asyncio.run(reflection.process_one(database))
    reviews = [package(request)["data"]["decision_review"] for request in provider.requests]
    assert [item["actual_outcome"] for item in reviews] == ["FIRST_OUTCOME", "SECOND_OUTCOME"]
    assert [item["expected_outcome"] for item in reviews] == ["FIRST_EXPECTATION", "SECOND_EXPECTATION"]
    with database.session() as session:
        job = session.query(BackgroundJob).filter_by(request_id=f"reflect:decision:{first_id}").one()
        assert job.payload["outcome_id"] == first_id


def test_manual_outcome_request_keeps_enqueue_time_latest_and_same_request_identity(env):
    client, database, provider = env
    with database.session() as session:
        decision = DecisionJournalEntry(title="합성 결정", choice="A", rationale="근거", conversation_id=1)
        session.add(decision)
        session.flush()
        first = DecisionReviewRecord(decision_id=decision.id, actual_outcome="FIRST_OUTCOME")
        session.add(first)
        session.flush()
        first_id = first.id
        job = reflection.enqueue(session, request_id="manual-event", source="decision_outcome", decision_id=decision.id)
        session.add(DecisionReviewRecord(decision_id=decision.id, actual_outcome="LATER_OUTCOME"))
        session.flush()
        same_job = reflection.enqueue(session, request_id="manual-event", source="decision_outcome", decision_id=decision.id)
        assert job.id == same_job.id and same_job.payload["outcome_id"] == first_id
        session.commit()
    provider.replies.append({"nothing_to_learn": True, "playbooks": [], "memories": []})
    assert asyncio.run(reflection.process_one(database))
    assert package(provider.requests[0])["data"]["decision_review"]["actual_outcome"] == "FIRST_OUTCOME"
    from app.modules.context.source_policy import source_allowed
    from sqlalchemy import delete
    from app.modules.database.model import ContextSnapshot
    with database.session() as session:
        snapshot_id = provider.requests[0].source_snapshot_id
        snapshot = session.get(ContextSnapshot, snapshot_id)
        assert any(ref["table"] == "decision_reviews" and ref["id"] == first_id
                   for ref in snapshot.record_references)
        assert source_allowed(session, [{"table": "context_snapshots", "id": snapshot_id}])
        session.execute(delete(DecisionReviewRecord).where(DecisionReviewRecord.id == first_id))
        session.commit()
        assert not source_allowed(session, [{"table": "context_snapshots", "id": snapshot_id}])


def test_legacy_job_without_pinned_outcome_fails_closed(env):
    client, database, provider = env
    with database.session() as session:
        decision = DecisionJournalEntry(title="합성 결정", choice="A", rationale="근거", conversation_id=1)
        session.add(decision)
        session.flush()
        session.add(DecisionReviewRecord(decision_id=decision.id, actual_outcome="OUTCOME"))
        session.flush()
        job = reflection.enqueue(session, request_id="legacy-event", source="decision_outcome", decision_id=decision.id)
        job.payload = {key: value for key, value in job.payload.items() if key != "outcome_id"}
        job_id = job.id
        session.commit()
    assert asyncio.run(reflection.process_one(database))
    assert provider.requests == []
    with database.session() as session:
        job = session.get(BackgroundJob, job_id)
        assert job.status == "cancelled" and job.result == {"state": "source_unknown"}


def test_outcome_from_another_decision_is_refused(env):
    import pytest
    client, database, provider = env
    with database.session() as session:
        decisions = [DecisionJournalEntry(title=f"합성 결정 {number}", choice="A", rationale="근거", conversation_id=1)
                     for number in range(2)]
        session.add_all(decisions)
        session.flush()
        other = DecisionReviewRecord(decision_id=decisions[1].id, actual_outcome="OTHER")
        session.add(other)
        session.flush()
        with pytest.raises(ValueError, match="연결된 회고 결과"):
            reflection.enqueue(session, request_id="wrong-event", source="decision_outcome",
                               decision_id=decisions[0].id, outcome_id=other.id)
