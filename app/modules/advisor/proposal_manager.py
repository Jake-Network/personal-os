"""Approval-gated writes (PRD §5.3, §7.2, AC-18).

The advisor can only *propose*. Applying a proposal requires an explicit user approval and
writes an audit record. Financial tables are not reachable from here at all.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.advisor.errors import ProposalError
from app.modules.advisor.proposals import parse_date, parse_datetime
from app.modules.crud import (
    audit_log_handler,
    calendar_event_handler,
    goal_handler,
    personal_memory_handler,
    proposed_action_handler,
    task_handler,
)
from app.modules.database.model import CalendarEvent, Goal, PersonalMemory, ProposedAction, MemoryRevision


def _validate_payload(action: str, payload: dict) -> dict:
    """Validate model output before persisting it or applying a legacy proposal."""
    allowed = {
        "create_task": {"title", "due_on", "priority", "estimate_minutes"},
        "calendar_update": {"event_id", "title", "starts_at", "ends_at", "kind"},
        "goal_update": {"goal_id", "current_value", "target_date", "status"},
    }
    if action not in allowed:
        raise ProposalError(f"unsupported action {action}")
    if not isinstance(payload, dict) or set(payload) - allowed[action]:
        raise ProposalError("invalid payload fields")
    p = dict(payload)
    try:
        if "title" in p:
            if not isinstance(p["title"], str) or not p["title"].strip():
                raise ProposalError("title required")
            p["title"] = p["title"].strip()
            if len(p["title"]) > 200:
                raise ProposalError("title exceeds 200 characters")
        if action == "create_task" and "title" not in p:
            raise ProposalError("title required")
        if "priority" in p and p["priority"] not in ("low", "normal", "high"):
            raise ProposalError("invalid priority")
        for key in ("event_id", "goal_id", "estimate_minutes"):
            if key in p and p[key] is not None:
                if isinstance(p[key], bool) or not isinstance(p[key], int) or p[key] <= 0:
                    raise ProposalError(f"{key} must be a positive integer")
        for key in ("due_on", "target_date"):
            if key in p:
                parse_date(p[key])
        for key in ("starts_at", "ends_at"):
            if key in p:
                parse_datetime(p[key])
        if p.get("starts_at") and p.get("ends_at") and parse_datetime(p["ends_at"]) < parse_datetime(p["starts_at"]):
            raise ProposalError("calendar ends_at precedes starts_at")
        if action == "calendar_update":
            if p.get("event_id"):
                if not set(p).intersection({"title", "starts_at", "ends_at"}):
                    raise ProposalError("calendar changes required")
                if "kind" in p:
                    raise ProposalError("kind cannot be changed by this action")
            elif not p.get("title") or not p.get("starts_at"):
                raise ProposalError("title and starts_at required for a new event")
            if "starts_at" in p and not p["starts_at"]:
                raise ProposalError("starts_at required")
            if p.get("kind", "personal") not in ("personal", "work", "interview", "workout", "deadline"):
                raise ProposalError("invalid calendar kind")
        if action == "goal_update":
            if not p.get("goal_id"):
                raise ProposalError("goal_id required")
            if not set(p).intersection({"current_value", "target_date", "status"}):
                raise ProposalError("goal changes required")
            if "status" in p and p["status"] not in ("active", "done", "dropped"):
                raise ProposalError("invalid status")
            if "current_value" in p:
                value = p["current_value"]
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise ProposalError("current_value must be text or a number")
                p["current_value"] = str(value)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ProposalError(str(exc)) from exc
    return p


def _target(session: Session, action: str, payload: dict, *, lock: bool = False):
    model = CalendarEvent if action == "calendar_update" else Goal if action == "goal_update" else None
    target_id = payload.get("event_id" if action == "calendar_update" else "goal_id")
    if model is None or not target_id:
        return None
    stmt = select(model).where(model.id == target_id).execution_options(populate_existing=True)
    target = session.scalar(stmt.with_for_update() if lock else stmt)
    if target is None:
        raise ProposalError("proposal target not found")
    return target


def _fingerprint(target) -> str:
    def encode(value):
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value.normalize())
        return value
    snapshot = {column.key: encode(getattr(target, column.key)) for column in target.__table__.columns}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def _validate_target_changes(action: str, payload: dict, target) -> None:
    if (action == "calendar_update" and target is not None and target.all_day
            and {"starts_at", "ends_at"}.intersection(payload)):
        raise ProposalError("all-day event times must be changed in the calendar")


class ProposalManager:
    @staticmethod
    def record(session: Session, conversation_id: int, message_id: int, proposals: list[dict],
               memories: list[dict]) -> tuple[list[ProposedAction], list[PersonalMemory]]:
        validated = []
        for proposal in proposals:
            action = proposal.get("action")
            payload = _validate_payload(action, proposal.get("payload"))
            target = _target(session, action, payload)
            _validate_target_changes(action, payload, target)
            if target is not None:
                before = {}
                for key in payload:
                    if key not in {'event_id', 'goal_id'} and hasattr(target, key):
                        value = getattr(target, key)
                        before[key] = (value.isoformat() if isinstance(value, (date, datetime)) else
                                       str(value) if isinstance(value, Decimal) else value)
                payload['_before'] = before
                payload["_precondition"] = _fingerprint(target)
            validated.append({**proposal, "payload": payload})
        actions = [
            proposed_action_handler.create(session, {
                "action": p["action"], "payload": p["payload"], "rationale": p.get("rationale"),
                "conversation_id": conversation_id,
            })
            for p in validated
        ]
        from app.modules.context.content_safety import findings
        # Candidates are later injected into prompts; model-written instructions or secrets never become one.
        mems = [
            personal_memory_handler.create(session, {
                "kind": m["kind"], "content": m["content"].strip()[:1000], "status": "proposed",
                "source": "advisor", "source_message_id": message_id,
            })
            for m in memories if not findings(m["content"])
        ]
        from app.modules.context.record_privacy import stamp_references
        for memory in mems:
            session.add(MemoryRevision(memory_id=memory.id, revision=0, kind=memory.kind, content=memory.content,
                status="proposed", source_references=stamp_references(session, [{"table": "advisor_messages", "id": message_id}])))
        for a in actions:
            audit_log_handler.record(session, "advisor", f"propose.{a.action}", f"proposed_actions:{a.id}",
                                     {"payload": a.payload})
        return actions, mems

    def approve(self, session: Session, proposal_id: int) -> dict:
        proposal = self._claim(session, proposal_id, "approved")
        try:
            ref = self._apply(session, proposal.action, proposal.payload)
            proposed_action_handler.update(session, proposal, {"result_ref": ref})
            audit_log_handler.record(session, "user", f"approve.{proposal.action}", f"proposed_actions:{proposal.id}",
                                     {"payload": proposal.payload, "result": ref})
            session.commit()
        except ProposalError:
            session.rollback()
            raise
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            session.rollback()
            raise ProposalError(f"invalid payload: {exc}") from exc
        except Exception:
            session.rollback()
            raise
        return ref

    def reject(self, session: Session, proposal_id: int) -> None:
        proposal = self._claim(session, proposal_id, "rejected")
        audit_log_handler.record(session, "user", f"reject.{proposal.action}", f"proposed_actions:{proposal.id}")
        session.commit()

    @staticmethod
    def _claim(session: Session, proposal_id: int, status: str) -> ProposedAction:
        """Atomically move pending → `status` inside the caller's transaction.

        A conditional UPDATE (… WHERE status = 'pending') is the concurrency control: of two
        concurrent approvals exactly one matches the row, the other waits on the row/DB write lock
        and then matches nothing. A check-then-write would let both read `pending` and apply twice.
        If applying fails, the caller rolls back and the proposal is pending again.
        """
        try:
            claimed = proposed_action_handler.transition(session, proposal_id, "pending", status,
                                                         {"decided_at": datetime.now(UTC)})
        except OperationalError as exc:  # SQLite: the other approval holds the write lock past the timeout
            session.rollback()
            raise ProposalError("proposal is being decided by another request") from exc
        proposal = proposed_action_handler.get(session, proposal_id)
        if proposal is None:
            raise LookupError("proposal not found")
        if not claimed:
            session.rollback()
            raise ProposalError(f"proposal already {proposal.status}")
        return proposal

    @staticmethod
    def _apply(session: Session, action: str, p: dict) -> dict:
        if not isinstance(p, dict):
            raise ProposalError("invalid payload fields")
        precondition = p.get("_precondition")
        p = _validate_payload(action, {k: v for k, v in p.items() if k not in {"_precondition", "_before"}})
        target = _target(session, action, p, lock=True)
        if target is not None and (not precondition or precondition != _fingerprint(target)):
            raise ProposalError("proposal target changed; request a new proposal")
        _validate_target_changes(action, p, target)
        if action == "create_task":
            title = str(p.get("title", "")).strip()
            if not title:
                raise ProposalError("title required")
            task = task_handler.create(session, {
                "title": title[:200],
                "due_on": parse_date(p.get("due_on")),
                "priority": p.get("priority") if p.get("priority") in ("low", "normal", "high") else "normal",
                "estimate_minutes": int(p["estimate_minutes"]) if p.get("estimate_minutes") else None,
            })
            return {"table": "tasks", "id": task.id}

        if action == "calendar_update":
            if p.get("event_id"):
                event = target
                changes = {k: (parse_datetime(p[k]) if k != "title" else str(p[k])[:200])
                           for k in ("title", "starts_at", "ends_at") if k in p}
                starts_at = changes.get("starts_at", event.starts_at)
                ends_at = changes.get("ends_at", event.ends_at)
                if ends_at is not None and ends_at < starts_at:
                    raise ProposalError("calendar ends_at precedes starts_at")
                calendar_event_handler.update(session, event, changes)
            else:
                if not p.get("title") or not p.get("starts_at"):
                    raise ProposalError("title and starts_at required for a new event")
                if p.get("ends_at") and parse_datetime(p["ends_at"]) < parse_datetime(p["starts_at"]):
                    raise ProposalError("calendar ends_at precedes starts_at")
                event = calendar_event_handler.create(session, {
                    "title": str(p["title"])[:200], "starts_at": parse_datetime(p["starts_at"]),
                    "ends_at": parse_datetime(p.get("ends_at")), "kind": p.get("kind") or "personal",
                })
            return {"table": "calendar_events", "id": event.id}

        if action == "goal_update":
            goal = target
            changes: dict = {}
            if "current_value" in p:
                changes["current_value"] = str(p["current_value"])
            if "target_date" in p:
                changes["target_date"] = parse_date(p["target_date"])
            if "status" in p:
                if p["status"] not in ("active", "done", "dropped"):
                    raise ProposalError("invalid status")
                changes["status"] = p["status"]
            goal_handler.update(session, goal, changes)
            return {"table": "goals", "id": goal.id}

        raise ProposalError(f"unsupported action {action}")


proposal_manager = ProposalManager()
