"""Recurring cash flows never post themselves and record at most one entry per item and month."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.agent import signals
from app.modules.database.model import CashflowEntry
from app.modules.finance import recurring
from app.schema.cashflow_import_schema import RecurringCashflowCreate


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(recurring, "local_today", lambda: date(2026, 2, 20))


def rent(session, **extra):
    return recurring.create(session, RecurringCashflowCreate(
        name="Synthetic rent", kind="expense", amount=Decimal("800000"), category="주거",
        day_of_month=31, start_on=date(2026, 1, 1), **extra))


def test_due_lists_without_posting_and_clamps_short_months(session, today):
    item = rent(session)
    [row] = recurring.due(session)
    assert (row["recurring_id"], row["month"], row["scheduled_on"], row["recorded"]) == (item.id, "2026-02", date(2026, 2, 28), False)
    assert session.scalars(select(CashflowEntry)).all() == []


def test_record_once_per_month_and_again_only_after_delete(session, today):
    item = rent(session)
    row = recurring.record(session, item.id, "2026-01")
    assert row["recorded"] is True
    entry = session.get(CashflowEntry, row["entry_id"])
    assert (entry.occurred_on, entry.kind, entry.amount, entry.currency, entry.description) == (
        date(2026, 1, 31), "expense", Decimal("800000"), "KRW", "Synthetic rent")
    with pytest.raises(RuntimeError):
        recurring.record(session, item.id, "2026-01")
    session.delete(entry)
    session.commit()
    assert recurring.record(session, item.id, "2026-01")["recorded"] is True
    assert len(session.scalars(select(CashflowEntry)).all()) == 1


def test_future_inactive_and_out_of_range_months_are_refused(session, today):
    item = rent(session, end_on=date(2026, 1, 15))
    with pytest.raises(ValueError):
        recurring.record(session, item.id, "2026-03")
    with pytest.raises(ValueError):
        recurring.record(session, item.id, "2026-02")
    assert recurring.due(session, "2025-12") == []


def test_deleting_schedule_keeps_recorded_entries(session, today):
    item = rent(session)
    recurring.record(session, item.id, "2026-02")
    recurring.delete(session, item.id)
    assert len(session.scalars(select(CashflowEntry)).all()) == 1


def test_unrecorded_due_item_is_a_local_only_signal(session, today, monkeypatch):
    from app.modules.agent import briefing
    rent(session)
    session.commit()
    now = datetime(2026, 2, 20, 3, tzinfo=UTC)
    # Day 31 clamps to Feb 28, which has not arrived: no signal yet.
    assert "recurring_due" not in [s["kind"] for s in signals.collect(session, now)]
    recurring.create(session, RecurringCashflowCreate(
        name="Synthetic salary", kind="income", amount=Decimal("3000000"), day_of_month=10, start_on=date(2026, 1, 1)))
    found = [s for s in signals.collect(session, now) if s["kind"] == "recurring_due"]
    assert found == [{"kind": "recurring_due", "count": 1, "title": signals.LABELS["recurring_due"], "link": "/finance/cashflow"}]
    # Local-only: it never decides that a model briefing should run.
    assert signals.CATEGORIES["recurring_due"] == set() and "recurring_due" not in briefing.SIGNAL_TOOLS


def test_http_contract(client):
    created = client.post("/api/finance/recurring", json={
        "name": "Synthetic phone", "kind": "expense", "amount": "55000", "day_of_month": 1, "start_on": "2026-01-01"})
    assert created.status_code == 201 and created.json()["currency"] == "KRW"
    item_id = created.json()["id"]
    assert client.post("/api/finance/recurring", json={
        "name": "x", "kind": "expense", "amount": "1", "day_of_month": 32, "start_on": "2026-01-01"}).status_code == 422
    recorded = client.post(f"/api/finance/recurring/{item_id}/record", json={"month": "2026-01"})
    assert recorded.status_code == 201 and recorded.json()["recorded"] is True
    assert client.post(f"/api/finance/recurring/{item_id}/record", json={"month": "2026-01"}).status_code == 409
    assert client.get("/api/finance/recurring/due", params={"month": "2026-01"}).json()[0]["recorded"] is True
    assert client.delete(f"/api/finance/recurring/{item_id}").status_code == 204
