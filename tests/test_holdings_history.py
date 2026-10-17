from datetime import date

from app.modules.portfolio.portfolio_manager import _enrich, _value


def test_live_fx_does_not_shadow_recorded_month_end_fx():
    tables = {"FX": [
        {"currency": "USD", "rate": "1200", "as_of": "2026-09-29", "source": "manual"},
        {"currency": "USD", "rate": "1400", "as_of": "2026-09-30", "source": "googlefinance"},
    ], "Closes": [
        {"ticker": "NASDAQ:AAPL", "currency": "USD", "price": "100", "as_of": "2026-09-30",
         "source": "manual", "valid_through": "2026-09-30"},
    ]}
    rows = [{"kind": "holding", "ticker": "NASDAQ:AAPL", "currency": "USD", "quantity": "2"}]
    historical = _enrich(rows, tables, date(2026, 9, 30), historical=True)[0]
    current = _enrich(rows, tables, date(2026, 9, 30), historical=False)[0]
    assert historical["fx_rate"] == "1200"
    assert historical["fx_source"] == "manual"
    assert current["fx_rate"] == "1400"


def test_small_prices_are_exposed_as_plain_decimal_strings():
    result = _value([{
        "kind": "holding", "id": "micro", "currency": "KRW", "quantity": "1",
        "avg_cost": "0.000000001", "price": "0.00000001", "source": "manual",
        "as_of": "2026-09-30", "price_as_of": "2026-09-30",
    }], {"cash", "holding", "liability", "other"}, date(2026, 9, 30), False)
    assert result["lines"][0]["price"] == "0.00000001"
    assert result["lines"][0]["avg_cost"] == "0.000000001"
