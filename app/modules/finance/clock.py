"""Date boundaries shared by local financial entry and reporting."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings

# Account freshness used by both the read API and consultation context.
# Current portfolio valuation keeps its separate, stricter policy.
STALE_BALANCE_DAYS = 45


def local_today():
    return datetime.now(ZoneInfo(settings.timezone)).date()
