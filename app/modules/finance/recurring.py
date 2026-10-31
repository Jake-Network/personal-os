"""Recurring income and expenses. Nothing posts automatically: each month the user records
an occurrence explicitly, and its source identity keeps one entry per item and month."""

from calendar import monthrange
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud import audit_log_handler
from app.modules.database.model import CashflowEntry, FinanceImportMapping, RecurringCashflow
from app.modules.finance.clock import local_today
from app.schema.cashflow_import_schema import RecurringCashflowCreate

CURRENCY = "KRW"  # new ledger entries are KRW only, as in manual entry


def _month_bounds(month: str) -> tuple[date, date]:
    year, index = (int(part) for part in month.split("-"))
    return date(year, index, 1), date(year, index, monthrange(year, index)[1])


def scheduled_on(item: RecurringCashflow, month: str) -> date:
    first, last = _month_bounds(month)
    return first.replace(day=min(item.day_of_month, last.day))


def applies(item: RecurringCashflow, month: str) -> bool:
    first, last = _month_bounds(month)
    return item.active and item.start_on <= last and (item.end_on is None or item.end_on >= first)


def source_ref(item_id: int, month: str) -> str:
    return f"recurring:{item_id}:{month}"


def list_items(session: Session) -> list[RecurringCashflow]:
    return list(session.scalars(select(RecurringCashflow).order_by(RecurringCashflow.day_of_month, RecurringCashflow.id)))


def create(session: Session, body: RecurringCashflowCreate) -> RecurringCashflow:
    item = RecurringCashflow(**body.model_dump(), currency=CURRENCY)
    session.add(item)
    session.flush()
    audit_log_handler.record(session, "user", "data.create", f"recurring-cashflows:{item.id}", {"financial": True})
    session.commit()
    return item


def update(session: Session, item_id: int, body: RecurringCashflowCreate) -> RecurringCashflow:
    item = session.get(RecurringCashflow, item_id)
    if item is None:
        raise LookupError("반복 거래를 찾을 수 없습니다")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    audit_log_handler.record(session, "user", "data.update", f"recurring-cashflows:{item.id}", {"financial": True})
    session.commit()
    return item


def delete(session: Session, item_id: int) -> None:
    """Removes the schedule only; entries it recorded stay in the ledger."""
    item = session.get(RecurringCashflow, item_id)
    if item is None:
        raise LookupError("반복 거래를 찾을 수 없습니다")
    session.delete(item)
    audit_log_handler.record(session, "user", "data.delete", f"recurring-cashflows:{item_id}", {"financial": True})
    session.commit()


def due(session: Session, month: str | None = None) -> list[dict]:
    month = month or local_today().strftime("%Y-%m")
    items = [item for item in list_items(session) if applies(item, month)]
    refs = {source_ref(item.id, month): item for item in items}
    mappings = {m.source_ref: m.record_id for m in session.scalars(
        select(FinanceImportMapping).where(FinanceImportMapping.source_ref.in_(refs)))} if refs else {}
    alive = set(session.scalars(select(CashflowEntry.id).where(CashflowEntry.id.in_(mappings.values())))) if mappings else set()
    result = []
    for ref, item in refs.items():
        entry_id = mappings.get(ref) if mappings.get(ref) in alive else None
        result.append({"recurring_id": item.id, "name": item.name, "kind": item.kind, "amount": item.amount,
                       "currency": item.currency, "category": item.category, "month": month,
                       "scheduled_on": scheduled_on(item, month), "recorded": entry_id is not None, "entry_id": entry_id})
    return sorted(result, key=lambda r: (r["scheduled_on"], r["recurring_id"]))


def record(session: Session, item_id: int, month: str) -> dict:
    """Records this month's occurrence once. A deleted entry may be recorded again on request."""
    item = session.get(RecurringCashflow, item_id)
    if item is None:
        raise LookupError("반복 거래를 찾을 수 없습니다")
    if month > local_today().strftime("%Y-%m"):
        raise ValueError("다가오는 달은 미리 기록하지 않습니다")
    if not applies(item, month):
        raise ValueError("이 달에는 적용되지 않는 반복 거래입니다")
    ref = source_ref(item.id, month)
    mapping = session.get(FinanceImportMapping, ref)
    if mapping is not None and session.get(CashflowEntry, mapping.record_id) is not None:
        raise RuntimeError("이번 달은 이미 기록했습니다")
    entry = CashflowEntry(occurred_on=scheduled_on(item, month), kind=item.kind, amount=item.amount,
                          currency=item.currency, category=item.category, description=item.name)
    try:
        session.add(entry)
        session.flush()
        if mapping is None:
            session.add(FinanceImportMapping(source_ref=ref, table_name="cashflow_entries", record_id=entry.id))
        else:
            mapping.record_id = entry.id
        audit_log_handler.record(session, "user", "data.create", f"cashflow-entries:{entry.id}",
                                 {"financial": True, "recurring_id": item.id, "month": month})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise RuntimeError("이번 달은 이미 기록했습니다") from exc
    return next(row for row in due(session, month) if row["recurring_id"] == item.id)
