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


@pytest.mark.parametrize(("start_on", "end_on", "month", "expected"), [
    (date(2026, 1, 20), None, "2026-01", False),
    (date(2026, 1, 1), date(2026, 2, 5), "2026-02", False),
    (date(2026, 1, 10), date(2026, 2, 10), "2026-02", True),
])
def test_occurrence_must_fall_within_schedule_dates(start_on, end_on, month, expected):
    from app.modules.database.model import RecurringCashflow

    item = RecurringCashflow(active=True, start_on=start_on, end_on=end_on, day_of_month=10)
    assert recurring.applies(item, month) is expected


def test_concurrent_rerecord_after_delete_keeps_one_entry(session, today):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from time import monotonic, sleep
    from uuid import uuid4

    from sqlalchemy import event, text
    from sqlalchemy.orm import Session

    item_id = rent(session).id
    original = recurring.record(session, item_id, "2026-01")
    session.delete(session.get(CashflowEntry, original["entry_id"]))
    session.commit()
    engine = session.get_bind()
    inserted, release = Event(), Event()
    second_name = "recurring_test_" + uuid4().hex

    def hold_first_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO cashflow_entries") and current_thread().name.endswith("_0"):
            inserted.set()
            assert release.wait(10), "first request was never released"

    def record_one(name):
        with Session(engine) as other:
            other.execute(text("SELECT set_config('application_name', :name, true)"), {"name": name})
            try:
                recurring.record(other, item_id, "2026-01")
                return "recorded"
            except RuntimeError:
                return "duplicate"

    event.listen(engine, "after_cursor_execute", hold_first_insert)
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="recurring") as pool:
            first = pool.submit(record_one, "recurring_first")
            assert inserted.wait(10)
            second = pool.submit(record_one, second_name)
            try:
                # Observe a real DB lock, rather than relying on a scheduling delay.
                deadline = monotonic() + 5
                waiting = False
                while monotonic() < deadline and not second.done():
                    with engine.connect() as observer:
                        waiting = observer.execute(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE application_name = :name AND wait_event_type = 'Lock')"
                        ), {"name": second_name}).scalar_one()
                    if waiting:
                        break
                    sleep(0.01)
                assert waiting, "second request completed without serializing against the first"
            finally:
                release.set()
            assert first.result(timeout=10) == "recorded"
            assert second.result(timeout=10) == "duplicate"
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", hold_first_insert)
    assert len(session.scalars(select(CashflowEntry)).all()) == 1
