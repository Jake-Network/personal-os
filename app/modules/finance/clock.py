"""Date boundaries shared by local financial entry and reporting."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings


def local_today():
    return datetime.now(ZoneInfo(settings.timezone)).date()
