from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.dashboard.dashboard_manager import dashboard_manager
from app.modules.database import get_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    return dashboard_manager.summary(session)
