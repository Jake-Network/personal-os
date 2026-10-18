from datetime import date
from decimal import Decimal

from app.modules.finance.financial_calculator import financial_calculator as calc
from app.modules.finance.liquidity_policy import account_bucket, account_spendable, holding_bucket
from app.schema.finance_schema import FxTable, Position

FX = FxTable(base="KRW", rates={"USD": Decimal("1400")})


def cash(ref, value, currency="KRW", kind="checking", is_liquid=True):
    return Position(ref, ref, Decimal(value), currency, account_bucket(kind), account_spendable(kind, is_liquid))


def test_net_worth_converts_fx_and_reports_unvalued_positions():
    assets = [
        cash("accounts:1", "1000000"),
        cash("accounts:2", "100", "USD"),
        cash("accounts:3", "1000", "JPY"),
        Position("holdings:1", "AAPL", None, "USD", "investment", unavailable_reason="no_price"),
    ]
    worth = calc.net_worth(FX, assets, [Position("liabilities:1", "대출", Decimal("300000"), "KRW")])
    assert worth.assets == Decimal("1140000")
    assert worth.net_worth == Decimal("840000")
    assert not worth.complete
    assert {e["reason"] for e in worth.excluded} == {"missing_fx_JPY_KRW", "no_price"}


def test_cash_plus_equities_only_cash_is_spendable():
    assets = [cash("accounts:1", "10000000"),
              Position("holdings:1", "005930", Decimal("50000000"), "KRW", holding_bucket("brokerage_cash"))]
    d = calc.net_worth(FX, assets, []).as_dict()
    assert d["net_worth"] == "60000000.00"
    assert d["cash_and_equivalents"] == "10000000.00"
    assert d["spendable_liquidity"] == "10000000.00"
    assert d["investable_assets"] == "50000000.00"
    assert "liquid_assets" not in d  # the old ambiguous figure is gone


def test_pension_accounts_and_their_holdings_are_restricted_not_spendable():
    pension = cash("accounts:2", "30000000", kind="pension", is_liquid=True)  # user flag cannot unlock it
    assert pension.bucket == "retirement" and not pension.spendable
    assets = [cash("accounts:1", "5000000"), pension,
              Position("holdings:9", "TDF", Decimal("7000000"), "KRW", holding_bucket("pension"))]
    d = calc.net_worth(FX, assets, []).as_dict()
    assert d["spendable_liquidity"] == "5000000.00"
    assert d["restricted_retirement_assets"] == "37000000.00"
    assert d["investable_assets"] == "37000000.00"
    assert d["net_worth"] == "42000000.00"


def test_illiquid_flag_and_other_kinds_narrow_spendable_cash():
    assert account_spendable("deposit", True) and not account_spendable("deposit", False)
    assert not account_spendable("other", True)
    assert account_bucket("other") == "other"


def test_missing_fx_on_cash_understates_runway_and_says_so():
    assets = [cash("accounts:1", "6000000"), cash("accounts:2", "1000", "EUR")]
    worth = calc.net_worth(FX, assets, [])
    assert not worth.spendable_complete
    runway = calc.cash_runway(worth.as_dict(), {"available": True, "monthly_average": "2000000"})
    assert runway["available"] is True and runway["months"] == "3.0"
    assert runway["understated"] is True


def test_missing_stock_price_leaves_spendable_liquidity_untouched():
    assets = [cash("accounts:1", "6000000"),
              Position("holdings:1", "AAPL", None, "USD", "investment", unavailable_reason="no_price")]
    worth = calc.net_worth(FX, assets, [])
    assert not worth.complete and worth.spendable_complete
    runway = calc.cash_runway(worth.as_dict(), {"available": True, "monthly_average": "2000000"})
    assert runway["months"] == "3.0" and runway["understated"] is False


def test_negative_net_worth_is_reported_and_runway_uses_cash_only():
    assets = [cash("accounts:1", "4000000")]
    debts = [Position("liabilities:1", "학자금", Decimal("30000000"), "KRW")]
    d = calc.net_worth(FX, assets, debts).as_dict()
    assert d["net_worth"] == "-26000000.00"
    assert d["spendable_liquidity"] == "4000000.00"
    assert calc.cash_runway(d, {"available": True, "monthly_average": "1000000"})["months"] == "4.0"


def test_monthly_average_requires_full_coverage():
    today = date(2026, 10, 17)
    full = [(date(2026, 7, 3), Decimal("300")), (date(2026, 8, 3), Decimal("300")),
            (date(2026, 9, 3), Decimal("600")), (date(2026, 10, 1), Decimal("999"))]  # October: current, ignored
    result = calc.monthly_average(full, today=today, months=3)
    assert result["available"] is True and result["monthly_average"] == "400.00"
    assert result["missing_months"] == []
    assert calc.monthly_average([], today=today)["available"] is False


def test_one_recorded_month_is_not_turned_into_a_three_month_average():
    result = calc.monthly_average([(date(2026, 9, 3), Decimal("3000000"))], today=date(2026, 10, 17), months=3)
    assert result["available"] is False and result["reason"] == "insufficient_coverage"
    assert "monthly_average" not in result  # the old code reported 1,000,000 here
    assert result["missing_months"] == ["2026-07", "2026-08"]
    assert result["estimate"]["monthly_average"] == "3000000.00"
    assert result["estimate"]["basis"] == "recorded_months_only"


def test_runway_refuses_partial_expense_history():
    worth = calc.net_worth(FX, [cash("accounts:1", "9000000")], []).as_dict()
    partial = calc.monthly_average([(date(2026, 9, 3), Decimal("3000000"))], today=date(2026, 10, 17))
    runway = calc.cash_runway(worth, partial)
    assert runway["available"] is False and runway["months"] is None
    assert runway["reason"] == "monthly_expense_insufficient_coverage"
    assert calc.cash_runway(None, partial)["reason"] == "spendable_liquidity_unknown"


def test_runway():
    r = calc.runway(Decimal("9000000"), Decimal("3000000"), emergency_reserve=Decimal("3000000"))
    assert r["months"] == "2.0"
    assert calc.runway(Decimal("100"), Decimal("10"), monthly_income=Decimal("20"))["months"] is None


def test_months_to_target():
    assert calc.months_to_target(Decimal("0"), Decimal("1000"), Decimal("100"))["months"] == 10
