"""Unified cash flows with source identities and all-time reversal dependencies.

No pagination limit is applied before calculations. Account observations are never
changed by this read path or by household ledger edits.
"""
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.modules.crud import app_setting_handler
from app.modules.database.model import CashflowEntry, FinancialTransaction
from app.modules.finance.clock import local_today
from app.modules.finance.ledger import INCOME, OUTFLOW


def load_flows(session, since: date, until: datetime):
    zone = ZoneInfo(settings.timezone)
    end_day = until.astimezone(zone).date()
    entries = list(session.scalars(select(CashflowEntry).where(
        CashflowEntry.occurred_on >= since, CashflowEntry.occurred_on <= end_day)))
    transaction_query = select(FinancialTransaction).where(
        FinancialTransaction.occurred_at >= datetime.combine(since, time.min, zone),
        FinancialTransaction.occurred_at <= until,
        FinancialTransaction.kind.in_(INCOME | OUTFLOW))
    transactions = list(session.scalars(transaction_query))
    reversals = list(session.scalars(select(FinancialTransaction).where(
        FinancialTransaction.kind == "reversal",
        FinancialTransaction.reverses_id.in_(transaction_query.with_only_columns(FinancialTransaction.id))))) if transactions else []
    reversed_ids = {r.reverses_id for r in reversals}
    rows = [{"source": "cashflow_entries", "id": e.id, "occurred_on": e.occurred_on.isoformat(),
             "kind": e.kind, "original_kind": e.kind, "amount": str(e.amount), "currency": e.currency,
             "category": (e.category or "").strip() or "미분류", "description": e.description,
             "is_reversed": False} for e in entries]
    rows += [{"source": "financial_transactions", "id": t.id,
              "occurred_on": t.occurred_at.astimezone(zone).date().isoformat(),
              "kind": "income" if t.kind in INCOME else "expense", "original_kind": t.kind,
              "amount": str(t.payload["amount"]), "currency": t.payload["currency"],
              "category": (t.payload.get("category") or "").strip() or "미분류",
              "description": t.payload.get("description") or t.payload.get("note"),
              "is_reversed": t.id in reversed_ids} for t in transactions]
    return rows, entries, transactions, reversals


def summarize(rows, currency="KRW"):
    active = [r for r in rows if not r["is_reversed"]]
    usable = [r for r in active if r["currency"] == currency]
    amounts = {kind: [Decimal(r["amount"]) for r in usable if r["kind"] == kind]
               for kind in ("income", "expense")}
    income, expense = (sum(amounts[kind], Decimal(0)) for kind in ("income", "expense"))
    return {"income": str(income) if amounts["income"] else None,
            "expense": str(expense) if amounts["expense"] else None,
            "net": str(income - expense) if usable else None,
            "record_count": len(active), "foreign_count": len(active) - len(usable)}


def month_offset(day, offset):
    year, month = divmod(day.year * 12 + day.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def report(session, month=None, kind=None, category=None, search=None, page=1, page_size=50):
    selected = date.fromisoformat(f"{month}-01") if month else local_today().replace(day=1)
    # Leave room for the six-month window and a valid next-month boundary.
    if not 2 <= selected.year <= 9998:
        raise ValueError("Month outside supported range")
    end = month_offset(selected, 1)
    until = datetime.combine(end, time.min, ZoneInfo(settings.timezone)).astimezone(UTC)
    rows, _, _, _ = load_flows(session, month_offset(selected, -5), until)
    rows = [r for r in rows if r["occurred_on"] < end.isoformat()
            and (not kind or r["kind"] == kind)
            and (category is None or r["category"] == category)
            and (not search or search.casefold() in (r["description"] or "").casefold())]
    current = sorted([r for r in rows if r["occurred_on"] >= selected.isoformat()],
                     key=lambda r: (r["occurred_on"], r["source"], r["id"]), reverse=True)
    currency = (app_setting_handler.get_value(session, "base_currency") or {}).get("currency", "KRW")
    summary = summarize(current, currency)
    mixed_sources = len({r["source"] for r in rows if not r["is_reversed"]}) > 1
    buckets = {}
    for row in current:
        if row["kind"] == "expense" and row["currency"] == currency and not row["is_reversed"]:
            buckets[row["category"]] = buckets.get(row["category"], Decimal(0)) + Decimal(row["amount"])
    total_expense = sum(buckets.values(), Decimal(0))
    return {"month": selected.strftime("%Y-%m"), "currency": currency,
            "items": current[(page-1)*page_size:page*page_size],
            "total": len(current), "page": page, "page_size": page_size, "summary": summary,
            "categories": [{"category": key, "amount": str(amount),
                            "share": str((amount / total_expense * 100).quantize(Decimal("0.01")))}
                           for key, amount in sorted(buckets.items(), key=lambda item: (-item[1], item[0]))],
            "trend": [{"month": month_offset(selected, i).strftime("%Y-%m"),
                       **summarize([r for r in rows if r["occurred_on"][:7] == month_offset(selected, i).strftime("%Y-%m")], currency)}
                      for i in range(-5, 1)],
            "data_quality_flags": ["recorded_flows_only"] +
                (["cashflow_mixed_sources"] if mixed_sources else []) +
                (["foreign_currency_excluded"] if summary["foreign_count"] else [])}
