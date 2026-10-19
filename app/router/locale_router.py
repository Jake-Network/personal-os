from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/locale", tags=["locale"])


class LocaleSettings(BaseModel):
    timezone: str


@router.get("", response_model=LocaleSettings)
def get_locale() -> LocaleSettings:
    """The timezone that "today", calendar days and stored local dates are interpreted in."""
    return LocaleSettings(timezone=settings.timezone)
