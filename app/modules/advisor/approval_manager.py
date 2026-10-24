"""Batch decisions over pending actions, memory candidates and playbook proposals.

Every item goes through the same manager call as its single-item endpoint, in its own
transaction, so validation, race protection and audit records are unchanged. Items are
independent: one stale or already-decided item is reported and does not undo the others.
"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.advisor.errors import ProposalError
from app.modules.advisor.memory_manager import memory_manager
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.playbooks.playbook_manager import playbook_manager
from app.schema.approval_schema import ApprovalBatch, ApprovalBatchResult, ApprovalDecision, ApprovalOutcome


def _apply(session: Session, item: ApprovalDecision) -> None:
    approve = item.decision == "approve"
    if item.kind == "action":
        proposal_manager.approve(session, item.id) if approve else proposal_manager.reject(session, item.id)
    elif item.kind == "memory":
        memory_manager.decide(session, item.id, approve)
    else:
        playbook_manager.approve(session, item.id) if approve else playbook_manager.reject(session, item.id)


def decide(session: Session, batch: ApprovalBatch) -> ApprovalBatchResult:
    results = []
    for item in batch.items:
        try:
            _apply(session, item)
            results.append(ApprovalOutcome(**item.model_dump(), ok=True))
        except LookupError:
            session.rollback()
            results.append(ApprovalOutcome(**item.model_dump(), ok=False, error="항목을 찾을 수 없습니다"))
        except IntegrityError:
            session.rollback()
            results.append(ApprovalOutcome(**item.model_dump(), ok=False, error="다른 요청이 먼저 처리했습니다"))
        except (ProposalError, ValueError) as exc:
            # Includes stale playbook bases and rules that tightened since the proposal was staged.
            session.rollback()
            results.append(ApprovalOutcome(**item.model_dump(), ok=False, error=str(exc)[:300]))
    succeeded = sum(result.ok for result in results)
    return ApprovalBatchResult(results=results, succeeded=succeeded, failed=len(results) - succeeded)
