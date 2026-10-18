"""Approval binds the exact target reviewed when the proposal was recorded."""
from datetime import UTC, datetime
import pytest

from app.modules.advisor.errors import ProposalError
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.database.model import AuditLog, CalendarEvent, AdvisorConversation, Goal, ProposedAction


def record(session, action, payload):
    conversation = AdvisorConversation(title="합성 상담")
    session.add(conversation)
    session.flush()
    actions, _ = proposal_manager.record(session, conversation.id, 0, [{"action": action, "payload": payload}], [])
    session.commit()
    return actions[0].id


@pytest.mark.parametrize("action", ["calendar_update", "goal_update"])
def test_stale_target_rejects_and_rolls_back_claim(session, action):
    if action == "calendar_update":
        target = CalendarEvent(title="기존 일정", starts_at=datetime(2026, 10, 18, tzinfo=UTC))
        payload = {"event_id": 1, "title": "제안 일정"}
    else:
        target = Goal(title="기존 목표", category="personal", current_value="1")
        payload = {"goal_id": 1, "current_value": "2"}
    session.add(target)
    session.commit()
    proposal_id = record(session, action, payload)
    target.title = "사용자가 수정한 내용"
    session.commit()
    with pytest.raises(ProposalError, match="target changed"):
        proposal_manager.approve(session, proposal_id)
    assert session.get(ProposedAction, proposal_id).status == "pending"
    assert session.get(type(target), target.id).title == "사용자가 수정한 내용"
    assert session.query(AuditLog).filter(AuditLog.action == f"approve.{action}").count() == 0


def test_unchanged_target_applies_once(session):
    goal = Goal(title="목표", category="personal", current_value="1")
    session.add(goal)
    session.commit()
    proposal_id = record(session, "goal_update", {"goal_id": goal.id, "current_value": "하프 마라톤 1시간 35분"})
    proposal_manager.approve(session, proposal_id)
    assert session.get(Goal, goal.id).current_value == "하프 마라톤 1시간 35분"
    with pytest.raises(ProposalError, match="already approved"):
        proposal_manager.approve(session, proposal_id)


def test_legacy_target_update_requires_a_new_proposal(session):
    goal = Goal(title="목표", category="personal")
    session.add(goal)
    session.flush()
    proposal = ProposedAction(action="goal_update", payload={"goal_id": goal.id, "status": "done"})
    session.add(proposal)
    session.commit()
    with pytest.raises(ProposalError, match="target changed"):
        proposal_manager.approve(session, proposal.id)
    assert session.get(Goal, goal.id).status == "active"
    assert session.get(ProposedAction, proposal.id).status == "pending"


@pytest.mark.parametrize("action,payload", [
    ("delete_goal", {"goal_id": 1}),
    ("create_task", {"title": "작업", "status": "done"}),
    ("create_task", {"title": "작업", "estimate_minutes": -1}),
    ("goal_update", {"goal_id": 1, "current_value": {"unexpected": "object"}}),
    ("calendar_update", {"event_id": 1, "title": "일정", "_precondition": "forged"}),
])
def test_invalid_model_payload_is_not_recorded(session, action, payload):
    with pytest.raises(ProposalError):
        record(session, action, payload)
    assert session.query(ProposedAction).count() == 0


def test_invalid_calendar_range_rolls_back_approval(session):
    event = CalendarEvent(title="일정", starts_at=datetime(2026, 10, 18, 10, tzinfo=UTC),
                          ends_at=datetime(2026, 10, 18, 11, tzinfo=UTC))
    session.add(event)
    session.commit()
    proposal_id = record(session, "calendar_update", {"event_id": event.id, "starts_at": "2026-10-18T12:00:00Z"})
    with pytest.raises(ProposalError, match="precedes"):
        proposal_manager.approve(session, proposal_id)
    assert session.get(ProposedAction, proposal_id).status == "pending"
    assert session.get(CalendarEvent, event.id).starts_at.hour == 10


def test_audit_failure_rolls_back_applied_change(session, monkeypatch):
    from app.modules.advisor import proposal_manager as module
    goal = Goal(title="목표", category="personal", current_value="1")
    session.add(goal)
    session.commit()
    proposal_id = record(session, "goal_update", {"goal_id": goal.id, "current_value": "2"})

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(module.audit_log_handler, "record", fail_audit)
    with pytest.raises(RuntimeError, match="audit failure"):
        proposal_manager.approve(session, proposal_id)
    assert session.get(Goal, goal.id).current_value == "1"
    assert session.get(ProposedAction, proposal_id).status == "pending"
