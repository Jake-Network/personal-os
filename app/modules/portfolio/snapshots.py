"""Month-end snapshot rules and the net-worth history view built from stored snapshots."""
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from app.modules.portfolio.valuation import money_string


def month_end(month, today):
    if month.day != 1:
        raise ValueError("month must be the first day of a calendar month")
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if end >= today:
        raise ValueError("Only completed calendar months can be snapshotted")
    return end


def snapshot_dict(obj):
    return dict(obj.payload, id=obj.id, month=obj.month.isoformat(), revision=obj.revision,
                supersedes_id=obj.supersedes_id, created_at=obj.created_at.isoformat(), reason=obj.reason,
                import_id=obj.import_id)


def history_view(records, today, period="all"):
    """Latest revision per month with month-over-month change, plus the months that have no snapshot."""
    with localcontext() as context:
        context.prec = 100
        return _history_view(records, today, period)


def _history_view(records, today, period):
    if period not in ("all", "6m", "1y"):
        raise ValueError("Unknown history period")
    latest = {s.month: s for s in records}
    today = today.replace(day=1)
    cutoff = None
    if period != "all":
        months = 6 if period == "6m" else 12
        n = today.year * 12 + today.month - 1 - months
        cutoff = date(n // 12, n % 12 + 1, 1)
    snapshots = []
    previous = None
    for month, obj in sorted(latest.items()):
        data = snapshot_dict(obj)
        try:
            curr = Decimal(data["net_worth"]) if data.get("net_worth") is not None else None
        except InvalidOperation:
            curr = None
        prev = Decimal(previous["net_worth"]) if previous and previous.get("net_worth") is not None else None
        adjacent = previous and (month.year * 12 + month.month - (
                    previous["month_date"].year * 12 + previous["month_date"].month)) == 1
        change = curr - prev if adjacent and curr is not None and prev is not None else None
        data["change_krw"] = money_string(change)
        data["change_pct"] = money_string(change / prev * 100) if change is not None and prev > 0 else None
        previous = dict(data, month_date=month)
        if cutoff is None or month >= cutoff:
            snapshots.append(data)
    start = cutoff or min(latest, default=today)
    missing = []
    while start < today:
        if start not in latest:
            missing.append(start.isoformat())
        n = start.year * 12 + start.month
        start = date(n // 12, n % 12 + 1, 1)
    return {"snapshots": snapshots, "missing_months": missing}
