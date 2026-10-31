from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.dashboard.dashboard_manager import dashboard_manager
from app.modules.database import get_session
from app.schema.dashboard_schema import DashboardSummary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# Unset keeps absent tool keys absent, so the typed response is the same payload the manager built.
@router.get("/summary", response_model=DashboardSummary, response_model_exclude_unset=True)
def summary(session: Session = Depends(get_session)):
    return dashboard_manager.summary(session)


from app.modules.crud import app_setting_handler
from app.schema.dashboard_schema import OnboardingState

ONBOARDING_KEY = "app.onboarding"


@router.get("/onboarding", response_model=OnboardingState)
def onboarding(session: Session = Depends(get_session)):
    return OnboardingState.model_validate(app_setting_handler.get_value(session, ONBOARDING_KEY) or {})


@router.put("/onboarding", response_model=OnboardingState)
def save_onboarding(body: OnboardingState, session: Session = Depends(get_session)):
    app_setting_handler.set_value(session, ONBOARDING_KEY, body.model_dump())
    session.commit()
    return body
