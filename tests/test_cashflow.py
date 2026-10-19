from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.database.model import CashflowEntry, FinancialTransaction


def ledger(session, kind, when, amount="10.25", **extra):
    row = FinancialTransaction(kind=kind, occurred_at=when, request_id=f"test-{kind}-{when}-{extra}",
        reverses_id=extra.get("reverses_id"), payload={"amount": amount, "currency": "KRW", **extra})
    session.add(row)
    session.flush()
    return row


def test_unified_cashflow_filters_precision_and_reversal_outside_month(client, session):
    session.add(CashflowEntry(occurred_on=date(2026, 9, 1), kind="expense", amount=Decimal("1.25"), category="식비", description="점심"))
    tx = ledger(session, "expense", datetime(2026, 8, 31, 15, tzinfo=UTC), description="점심")
    cancelled = ledger(session, "income", datetime(2026, 9, 2, tzinfo=UTC), "900")
    ledger(session, "reversal", datetime(2026, 11, 2, tzinfo=UTC), reverses_id=cancelled.id)
    ledger(session, "transfer", datetime(2026, 9, 3, tzinfo=UTC), "500")
    session.add(CashflowEntry(occurred_on=date(2026, 9, 1), kind="expense", amount=Decimal("99"), currency="USD"))
    session.commit()
    response = client.get("/api/finance/cashflow", params={"month": "2026-09", "page_size": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert len(body["items"]) == 1
    assert Decimal(body["summary"]["expense"]) == Decimal("11.50")
    assert body["summary"]["income"] is None
    assert body["summary"]["foreign_count"] == 1
    assert len(body["trend"]) == 6
    assert body["trend"][0]["net"] is None
    filtered = client.get("/api/finance/cashflow", params={"month": "2026-09", "search": "점심"}).json()
    assert filtered["total"] == 2
    assert {r["source"] for r in filtered["items"]} == {"cashflow_entries", "financial_transactions"}
    assert filtered["items"][0]["id"] == tx.id  # same numeric ID, distinct source
    assert Decimal(filtered["summary"]["expense"]) == Decimal("11.50")


def test_cashflow_totals_are_not_capped_at_1000(client, session):
    session.add_all([CashflowEntry(occurred_on=date(2026, 9, 2), kind="expense", amount=Decimal("0.01")) for _ in range(1005)])
    session.commit()
    result = client.get("/api/finance/cashflow", params={"month": "2026-09", "page": 21}).json()
    assert result["total"] == 1005
    assert len(result["items"]) == 5
    assert Decimal(result["summary"]["expense"]) == Decimal("10.05")


def test_new_cashflow_is_krw_existing_foreign_can_be_corrected(client, session):
    body = {"occurred_on": "2026-09-01", "kind": "expense", "amount": "1.25", "currency": "USD"}
    assert client.post("/api/data/cashflow-entries", json=body).status_code == 422
    existing = CashflowEntry(occurred_on=date(2026, 9, 1), kind="expense", amount=Decimal("2"), currency="USD")
    session.add(existing)
    session.commit()
    assert client.put(f"/api/data/cashflow-entries/{existing.id}", json=body).status_code == 200


def test_cashflow_crud_and_ledger_cancel_keep_account_balance(client, session):
    from app.modules.database.model import Account
    account = Account(name="합성 계좌", kind="checking", balance=Decimal("8000"), balance_as_of=date(2026, 9, 1))
    session.add(account)
    tx = ledger(session, "fee", datetime(2026, 9, 2, tzinfo=UTC), "12.34")
    session.commit()
    tx_id, account_id = tx.id, account.id
    body = {"occurred_on": "2026-09-01", "kind": "expense", "amount": "1.2345", "category": "식비"}
    created = client.post("/api/data/cashflow-entries", json=body)
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert client.get(f"/api/data/cashflow-entries/{entry_id}").json()["category"] == "식비"
    body.update(amount="9.8765", category="생활")
    assert client.put(f"/api/data/cashflow-entries/{entry_id}", json=body).status_code == 200
    report = client.get("/api/finance/cashflow", params={"month": "2026-09", "category": "생활"}).json()
    assert Decimal(report["summary"]["expense"]) == Decimal("9.8765")
    assert report["categories"] == [{"category": "생활", "amount": "9.8765", "share": "100.00"}]
    assert client.delete(f"/api/data/cashflow-entries/{entry_id}").status_code == 204
    reversal = client.post("/api/finance/transactions", json={"request_id": "reverse-test", "kind": "reversal", "occurred_at": "2026-10-01T00:00:00Z", "source": "합성 취소", "reverses_id": tx_id})
    assert reversal.status_code == 201, reversal.text
    result = client.get("/api/finance/cashflow", params={"month": "2026-09"}).json()
    assert result["summary"]["net"] is None
    assert result["items"][0]["is_reversed"] is True
    session.expire_all()
    assert session.get(Account, account_id).balance == Decimal("8000")


def test_cashflow_input_validation_and_month_end(client, session):
    # Next month's midnight in the app zone must be excluded.
    from app.config import settings
    from zoneinfo import ZoneInfo
    ledger(session, "expense", datetime(2026, 10, 1, tzinfo=ZoneInfo(settings.timezone)), "10")
    session.commit()
    assert client.get("/api/finance/cashflow", params={"month": "2026-09"}).json()["total"] == 0
    for params in ({"month": "2026-13"}, {"month": "0001-01"}, {"page": 0}, {"kind": "transfer"}):
        assert client.get("/api/finance/cashflow", params=params).status_code == 422


def test_cashflow_amount_precision_is_not_silently_rounded(client):
    body = {"occurred_on": "2026-09-01", "kind": "expense", "amount": "1.23456"}
    assert client.post("/api/data/cashflow-entries", json=body).status_code == 422


def test_mixed_sources_warning_covers_trend_before_pagination(client, session):
    session.add(CashflowEntry(occurred_on=date(2026, 8, 1), kind="expense", amount=Decimal("10")))
    ledger(session, "expense", datetime(2026, 9, 2, tzinfo=UTC))
    session.commit()
    body = client.get("/api/finance/cashflow", params={"month": "2026-09", "page_size": 1}).json()
    assert "cashflow_mixed_sources" in body["data_quality_flags"]
    filtered = client.get("/api/finance/cashflow", params={"month": "2026-09", "kind": "income"}).json()
    assert "cashflow_mixed_sources" not in filtered["data_quality_flags"]


def test_cashflow_uses_advisor_base_currency_for_all_aggregates(client, session):
    from app.modules.crud import app_setting_handler
    app_setting_handler.set_value(session, "base_currency", {"currency": "USD"})
    session.add_all([
        CashflowEntry(occurred_on=date(2026, 9, 1), kind="expense", amount=Decimal("12.50"), currency="USD", category="식비"),
        CashflowEntry(occurred_on=date(2026, 9, 1), kind="expense", amount=Decimal("2000")),
    ])
    session.commit()
    body = client.get("/api/finance/cashflow", params={"month": "2026-09"}).json()
    assert Decimal(body["summary"]["expense"]) == Decimal("12.50")
    assert body["currency"] == "USD"
    assert body["summary"]["foreign_count"] == 1
    assert len(body["categories"]) == 1
    assert body["categories"][0]["category"] == "식비"
    assert Decimal(body["categories"][0]["amount"]) == Decimal("12.50")
    assert Decimal(body["categories"][0]["share"]) == Decimal("100")
    assert Decimal(body["trend"][-1]["expense"]) == Decimal("12.50")
    assert "foreign_currency_excluded" in body["data_quality_flags"]
