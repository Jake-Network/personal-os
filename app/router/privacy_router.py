from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.context.privacy_manager import privacy_manager
from app.modules.database import get_session
from app.schema.context_schema import PrivacySettings

router = APIRouter(prefix="/api/settings/privacy", tags=["privacy"])


@router.get("", response_model=PrivacySettings)
def get_privacy(session: Session = Depends(get_session)):
    return PrivacySettings(excluded_categories=sorted(privacy_manager.get_excluded(session)))


@router.put("", response_model=PrivacySettings)
def put_privacy(body: PrivacySettings, session: Session = Depends(get_session)):
    return PrivacySettings(excluded_categories=sorted(privacy_manager.set_excluded(session, body.excluded_categories)))
