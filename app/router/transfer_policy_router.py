from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.database import get_session
from app.modules.llm import transfer_policy
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.schema.transfer_policy_schema import TransferConfirmation, TransferPolicyStatus

router = APIRouter(prefix="/api/settings/transfer-policy", tags=["transfer-policy"])


@router.get("", response_model=TransferPolicyStatus)
def get_transfer_policy(session: Session = Depends(get_session)):
    return transfer_policy.status(session, llm_gateway_manager.provider_name(session))


@router.put("", response_model=TransferPolicyStatus)
def confirm_transfer_policy(body: TransferConfirmation, session: Session = Depends(get_session)):
    return transfer_policy.confirm(session, llm_gateway_manager.provider_name(session),
                                   body.training_excluded, body.retention_understood)


@router.delete("", status_code=204)
def revoke_transfer_policy(session: Session = Depends(get_session)):
    transfer_policy.invalidate(session)
    session.commit()
