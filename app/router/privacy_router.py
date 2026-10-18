from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.context.privacy_manager import privacy_manager
from app.modules.database import get_session
from app.schema.context_schema import PrivacySettings, RecordSharingUpdate

router = APIRouter(prefix="/api/settings/privacy", tags=["privacy"])


@router.get("", response_model=PrivacySettings)
def get_privacy(session: Session = Depends(get_session)):
    return PrivacySettings(excluded_categories=sorted(privacy_manager.get_excluded(session)))


@router.put("", response_model=PrivacySettings)
def put_privacy(body: PrivacySettings, session: Session = Depends(get_session)):
    return PrivacySettings(excluded_categories=sorted(privacy_manager.set_excluded(session, body.excluded_categories)))


@router.get("/records")
def record_sharing_settings(session: Session = Depends(get_session)):
    from app.modules.context.record_privacy import blocked
    return {"local_only_records": blocked(session), "aggregate_policy": "omit_tool_if_any_contributor_local_only"}


@router.put("/records/{table}/{record_id}")
def set_record_sharing(table: str, record_id: int, body: RecordSharingUpdate, session: Session = Depends(get_session)):
    from app.modules.context.record_privacy import set_record_policy
    from fastapi import HTTPException
    try:
        return set_record_policy(session, table, record_id, body.external_allowed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
