from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.advisor import approval_manager
from app.modules.database import get_session
from app.schema.approval_schema import ApprovalBatch, ApprovalBatchResult

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.post("/batch", response_model=ApprovalBatchResult)
def decide_approvals(body: ApprovalBatch, session: Session = Depends(get_session)):
    """Each listed item is decided as if its own approve/reject button had been pressed."""
    return approval_manager.decide(session, body)
