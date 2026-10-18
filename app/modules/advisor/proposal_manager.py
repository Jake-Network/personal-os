"""Approval-gated writes (PRD §5.3, §7.2, AC-18).

The advisor can only *propose*. Applying a proposal requires an explicit user approval and
writes an audit record. Financial tables are not reachable from here at all.
"""

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.crud import (
    audit_log_handler,
    calendar_event_handler,
    goal_handler,
    personal_memory_handler,
    proposed_action_handler,
    task_handler,
)
from app.modules.database.model import PersonalMemory, ProposedAction

ALLOWED_ACTIONS = {"create_task", "calendar_update", "goal_update"}
MEMORY_KINDS = {"profile", "preference", "constraint", "priority"}
BLOCK_RE = re.compile(r"```(proposal|memory)\s*\n(.*?)\n```", re.DOTALL)


class ProposalError(ValueError):
    pass


def _date(value) -> date | None:
    return None if value in (None, "") else date.fromisoformat(str(value))


def _dt(value) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class ProposalManager:
    @staticmethod
    def extract_blocks(text: str) -> tuple[str, list[dict], list[dict]]:
        """Split model output into display text, action proposals and memory proposals."""
        proposals, memories = [], []
        for kind, raw in BLOCK_RE.findall(text):
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if kind == "proposal" and isinstance(obj, dict) and obj.get("action") in ALLOWED_ACTIONS \
                    and isinstance(obj.get("payload"), dict):
                proposals.append(obj)
            elif kind == "memory" and isinstance(obj, dict) and obj.get("kind") in MEMORY_KINDS \
                    and isinstance(obj.get("content"), str) and obj["content"].strip():
                memories.append(obj)
        return BLOCK_RE.sub("", text).rstrip(), proposals, memories

    @staticmethod
    def record(session: Session, conversation_id: int, message_id: int, proposals: list[dict],
               memories: list[dict]) -> tuple[list[ProposedAction], list[PersonalMemory]]:
        actions = [
            proposed_action_handler.create(session, {
                "action": p["action"], "payload": p["payload"], "rationale": p.get("rationale"),
                "conversation_id": conversation_id,
            })
            for p in proposals
        ]
        mems = [
            personal_memory_handler.create(session, {
                "kind": m["kind"], "content": m["content"].strip()[:1000], "status": "proposed",
                "source": "advisor", "source_message_id": message_id,
            })
            for m in memories
        ]
        for a in actions:
            audit_log_handler.record(session, "advisor", f"propose.{a.action}", f"proposed_actions:{a.id}",
                                     {"payload": a.payload})
        return actions, mems

    def approve(self, session: Session, proposal_id: int) -> dict:
        proposal = self._claim(session, proposal_id, "approved")
        try:
            ref = self._apply(session, proposal.action, proposal.payload)
        except ProposalError:
            session.rollback()
            raise
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            session.rollback()
            raise ProposalError(f"invalid payload: {exc}") from exc
        proposed_action_handler.update(session, proposal, {"result_ref": ref})
        audit_log_handler.record(session, "user", f"approve.{proposal.action}", f"proposed_actions:{proposal.id}",
                                 {"payload": proposal.payload, "result": ref})
        session.commit()
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
        if action == "create_task":
            title = str(p.get("title", "")).strip()
            if not title:
                raise ProposalError("title required")
            task = task_handler.create(session, {
                "title": title[:200],
                "due_on": _date(p.get("due_on")),
                "priority": p.get("priority") if p.get("priority") in ("low", "normal", "high") else "normal",
                "estimate_minutes": int(p["estimate_minutes"]) if p.get("estimate_minutes") else None,
            })
            return {"table": "tasks", "id": task.id}

        if action == "calendar_update":
            if p.get("event_id"):
                event = calendar_event_handler.get(session, int(p["event_id"]))
                if event is None:
                    raise ProposalError("calendar event not found")
                changes = {k: (_dt(p[k]) if k != "title" else str(p[k])[:200])
                           for k in ("title", "starts_at", "ends_at") if k in p}
                calendar_event_handler.update(session, event, changes)
            else:
                if not p.get("title") or not p.get("starts_at"):
                    raise ProposalError("title and starts_at required for a new event")
                event = calendar_event_handler.create(session, {
                    "title": str(p["title"])[:200], "starts_at": _dt(p["starts_at"]),
                    "ends_at": _dt(p.get("ends_at")), "kind": p.get("kind") or "personal",
                })
            return {"table": "calendar_events", "id": event.id}

        if action == "goal_update":
            goal = goal_handler.get(session, int(p.get("goal_id") or 0))
            if goal is None:
                raise ProposalError("goal not found")
            changes: dict = {}
            if "current_value" in p:
                changes["current_value"] = Decimal(str(p["current_value"]))
            if "target_date" in p:
                changes["target_date"] = _date(p["target_date"])
            if "status" in p:
                if p["status"] not in ("active", "done", "dropped"):
                    raise ProposalError("invalid status")
                changes["status"] = p["status"]
            goal_handler.update(session, goal, changes)
            return {"table": "goals", "id": goal.id}

        raise ProposalError(f"unsupported action {action}")


proposal_manager = ProposalManager()
