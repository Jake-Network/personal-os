"""Small, explicit calendar scope grammar; unsupported dates are never guessed."""

import re
from datetime import datetime, timedelta

from app.modules.context.types import CalendarScope


_RELATIVE = re.compile(
    r"day after tomorrow|\b(?:today|tomorrow|yesterday)\b|"
    r"\b(?:this|next|last)\s+(?:week|month)\b|"
    r"오늘|내일|모레|어제|(?:이번|다음|지난)\s*(?:주|달)|이번\s*월|다음\s*월|지난\s*월",
    re.IGNORECASE,
)
_ISO = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_OTHER_DATE = re.compile(
    r"\d{1,4}\s*(?:년|월|일|주|달)|다다음|내년|작년|그저께|"
    r"(?i:\b(?:in\s+\d+\s+days?|next year|last year|"
    r"January|February|April|June|July|August|September|October|November|December)\b)|"
    # "may" and "march" are also ordinary words; only a date-like use counts as a month.
    r"\b(?:May|March)\s+\d|\d\s*(?:st|nd|rd|th)?\s+(?:May|March)\b|"
    r"(?i:\b(?:in|on|of|since|until|by|next|last|this|early|late)\s+(?:may|march)\b)"
)
_UNSUPPORTED = re.compile(r"다다음|주말|분기|\d{1,4}[/]\d{1,2}|\d{4}-\d{1,2}-\d{1,2}")


def calendar_scope(query: str, now: datetime, days: int = 14) -> CalendarScope:
    """Resolve one supported day/week/month in the caller's aware timezone.

    Multiple scopes and unsupported date expressions keep the legacy default range,
    explicitly marked unresolved so the assistant cannot claim complete coverage.
    """
    fallback = (now - timedelta(hours=12), now + timedelta(days=days))
    matches = [(m.group(), m.span()) for m in _RELATIVE.finditer(query)]
    matches += [(m.group(), m.span()) for m in _ISO.finditer(query)]
    remainder = list(query)
    for _, (left, right) in matches:
        remainder[left:right] = " " * (right - left)
    remainder_text = "".join(remainder)
    unsupported = bool(_OTHER_DATE.search(remainder_text) or _UNSUPPORTED.search(remainder_text)
                       or re.search(r"다다음|주말|분기", query))
    labels = {re.sub(r"\s+", "", text.lower()) for text, _ in matches}
    if not labels and not unsupported:
        return CalendarScope(*fallback, "default", "upcoming")
    if len(labels) != 1 or unsupported:
        return CalendarScope(*fallback, "unresolved", "unsupported_or_multiple_dates")

    label = labels.pop()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_offsets = {"오늘": 0, "today": 0, "내일": 1, "tomorrow": 1,
                   "모레": 2, "dayaftertomorrow": 2, "어제": -1, "yesterday": -1}
    if label in day_offsets:
        start = midnight + timedelta(days=day_offsets[label])
        return CalendarScope(start, start + timedelta(days=1), "explicit", label)
    if _ISO.fullmatch(label):
        try:
            parsed = datetime.strptime(label, "%Y-%m-%d")
            start = midnight.replace(year=parsed.year, month=parsed.month, day=parsed.day)
            end = start + timedelta(days=1)
        except (ValueError, OverflowError):
            return CalendarScope(*fallback, "unresolved", "invalid_date")
        return CalendarScope(start, end, "explicit", label)
    offset = 1 if label.startswith(("다음", "next")) else -1 if label.startswith(("지난", "last")) else 0
    if label.endswith(("주", "week")):
        start = midnight - timedelta(days=midnight.weekday()) + timedelta(weeks=offset)
        return CalendarScope(start, start + timedelta(days=7), "explicit", label)
    month_index = now.year * 12 + now.month - 1 + offset
    year, month = divmod(month_index, 12)
    start = midnight.replace(year=year, month=month + 1, day=1)
    next_year, next_month = divmod(month_index + 1, 12)
    end = midnight.replace(year=next_year, month=next_month + 1, day=1)
    return CalendarScope(start, end, "explicit", label)
