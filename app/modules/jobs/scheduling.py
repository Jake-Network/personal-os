"""Calendar intervals in the configured local timezone, with half-open boundaries."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def shift_month(day: date, months: int):
    month = day.year * 12 + day.month - 1 + months
    return date(month // 12, month % 12 + 1, 1)


def completed_period(now: datetime, cadence: str, timezone: str):
    local = now.astimezone(ZoneInfo(timezone))
    month = local.month if cadence == "month" else ((local.month - 1) // 3 * 3 + 1 if cadence == "quarter" else 1)
    end = date(local.year, month, 1)
    months = {"month": 1, "quarter": 3, "year": 12}[cadence]
    start = shift_month(end, -months)
    following = datetime.combine(shift_month(end, months), time.min, ZoneInfo(timezone))
    return start, end, following
