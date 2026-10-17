from datetime import date
from decimal import Decimal

from app.modules.finance.financial_calculator import financial_calculator as calc
from app.schema.finance_schema import FxTable, Position


def test_net_worth_converts_fx_and_reports_unvalued_positions():
    fx = FxTable(base="KRW", rates={"USD": Decimal("1400")})
    assets = [
        Position("accounts:1", "통장", Decimal("1000000"), "KRW", liquid=True),
        Position("accounts:2", "달러", Decimal("100"), "USD", liquid=True),
        Position("accounts:3", "엔화", Decimal("1000"), "JPY", liquid=True),
        Position("holdings:1", "AAPL", None, "USD", True, "no_price"),
    ]
    worth = calc.net_worth(fx, assets, [Position("liabilities:1", "대출", Decimal("300000"), "KRW")])
    assert worth.assets == Decimal("1140000")
    assert worth.net_worth == Decimal("840000")
    assert not worth.complete
    assert {e["reason"] for e in worth.excluded} == {"missing_fx_JPY_KRW", "no_price"}


def test_monthly_average_uses_full_months_only_and_flags_partial():
    entries = [(date(2026, 9, 3), Decimal("300")), (date(2026, 10, 1), Decimal("999"))]
    result = calc.monthly_average(entries, today=date(2026, 10, 17), months=3)
    assert result["monthly_average"] == "100.00"
    assert result["partial"] is True
    assert calc.monthly_average([], today=date(2026, 10, 17))["available"] is False


def test_runway():
    r = calc.runway(Decimal("9000000"), Decimal("3000000"), emergency_reserve=Decimal("3000000"))
    assert r["months"] == "2.0"
    assert calc.runway(Decimal("100"), Decimal("10"), monthly_income=Decimal("20"))["months"] is None


def test_months_to_target():
    assert calc.months_to_target(Decimal("0"), Decimal("1000"), Decimal("100"))["months"] == 10
