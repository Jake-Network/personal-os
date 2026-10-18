from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.modules.advisor.errors import ProposalError
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.crud import proposed_action_handler
from app.modules.database import get_session
from app.schema.advisor_schema import ProposalItem

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


@router.get("", response_model=list[ProposalItem])
def list_proposals(status: str = "pending", session: Session = Depends(get_session)):
    return proposed_action_handler.get_by_status(session, status)


@router.post("/{proposal_id}/approve")
def approve(proposal_id: int, session: Session = Depends(get_session)):
    try:
        return {"result": proposal_manager.approve(session, proposal_id)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ProposalError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{proposal_id}/reject", status_code=204)
def reject(proposal_id: int, session: Session = Depends(get_session)):
    try:
        proposal_manager.reject(session, proposal_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ProposalError as exc:
        raise HTTPException(409, str(exc)) from exc
