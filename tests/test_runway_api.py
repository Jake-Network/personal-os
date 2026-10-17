"""Dashboard runway: spendable cash only, and never from an incomplete expense history."""
from app.modules.database.model import CashflowEntry


def summary(client):
    res = client.get("/api/dashboard/summary")
    assert res.status_code == 200
    return res.json()


def test_dashboard_runway_excludes_equities(client, seeded):
    body = summary(client)
    worth = body["data"]["get_accounts_summary"]["computed"]["net_worth"]
    # 12,000,000 KRW + 1,000 USD × 1,400; the 700,000 KRW of shares is investable, not spendable.
    assert worth["spendable_liquidity"] == "13400000.00"
    assert worth["investable_assets"] == "700000.00"
    assert worth["net_worth"] == "9100000.00"
    runway = body["computed"]["runway"]
    assert runway["available"] is True and runway["months"] == "6.7"  # 13.4M / 2M (old code: 7.1 with shares)


def test_dashboard_runway_is_unavailable_with_one_month_of_expenses(client, seeded):
    for entry in seeded.query(CashflowEntry).order_by(CashflowEntry.occurred_on).all()[:2]:
        seeded.delete(entry)
    seeded.commit()
    body = summary(client)
    expense = body["data"]["get_cashflow_summary"]["monthly_expense"]
    assert expense["available"] is False and expense["estimate"]["monthly_average"] == "2000000.00"
    assert body["computed"]["runway"] == {**body["computed"]["runway"], "available": False, "months": None,
                                          "reason": "monthly_expense_insufficient_coverage"}
    assert "monthly_expense_insufficient_coverage" in {f["code"] for f in body["data_quality_flags"]}
