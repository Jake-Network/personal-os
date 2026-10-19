"""Purchase-cost returns use synthetic prices and Decimal arithmetic only."""
from datetime import date

import pytest

from app.modules.portfolio.valuation import value_positions


def holding_line(**changes):
    row = dict(kind="holding", id="example", label="Example", currency="USD",
               quantity="12", avg_cost="150.125", price="180.15",
               as_of="2026-10-19", price_as_of="2026-10-19",
               fx_rate="1400", fx_as_of="2026-10-19", source="manual")
    row.update(changes)
    return value_positions([row], ["holding"], date(2026, 10, 19), True)["lines"][0]


def test_purchase_cost_and_return_are_calculated_in_quote_currency():
    line = holding_line()
    assert line["cost_basis_native"] == "1801.50"
    assert line["unrealized_gain_native"] == "360.30"
    assert line["unrealized_return_pct"] == "20.00"
    assert line["unrealized_gain_krw"] == "504420.00"


@pytest.mark.parametrize("changes, cost, gain, rate", [
    ({"price": "120.1"}, "1801.50", "-360.30", "-20.00"),
    ({"price": "150.125"}, "1801.50", "0.00", "0.00"),
    ({"avg_cost": None}, None, None, None),
    ({"price": None}, "1801.50", None, None),
    ({"price_as_of": "2026-10-20"}, "1801.50", None, None),
    ({"avg_cost": "0"}, "0.00", "2161.80", None),
    ({"quantity": "0"}, "0.00", "0.00", None),
    ({"quantity": None}, None, None, None),
    ({"source": "googlefinance"}, "1801.50", "360.30", "20.00"),
    ({"price": "0"}, "1801.50", "-1801.50", "-100.00"),
])
def test_returns_preserve_losses_zero_and_missing_evidence(changes, cost, gain, rate):
    line = holding_line(**changes)
    assert line["cost_basis_native"] == cost
    assert line["unrealized_gain_native"] == gain
    assert line["unrealized_return_pct"] == rate


@pytest.mark.parametrize("changes", [
    {"fx_rate": None},
    {"fx_source": "googlefinance"},
])
def test_native_return_does_not_require_verified_fx(changes):
    row = dict(kind="holding", id="example", currency="USD", quantity="12",
               avg_cost="150.125", price="180.15", as_of="2026-10-19",
               price_as_of="2026-10-19", fx_rate="1400", fx_as_of="2026-10-19")
    row.update(changes)
    line = value_positions([row], ["holding"], date(2026, 10, 19), False)["lines"][0]
    assert line["unrealized_return_pct"] == "20.00"
    assert line["unrealized_gain_native"] == "360.30"
    assert line["unrealized_gain_krw"] is None
    assert line["value_krw"] is None


def test_unverified_quote_does_not_produce_return():
    row = dict(kind="holding", id="example", currency="KRW", quantity="2",
               avg_cost="100", price="120", as_of="2026-10-19",
               price_as_of="2026-10-19", source="googlefinance")
    line = value_positions([row], ["holding"], date(2026, 10, 19), False)["lines"][0]
    assert line["unrealized_gain_native"] is None
    assert line["unrealized_return_pct"] is None


def test_small_purchase_cost_is_not_rounded_before_return_calculation():
    line = holding_line(quantity="3", avg_cost="0.000000000005", price="0.000000000006")
    assert line["unrealized_return_pct"] == "20.00"


def test_saved_purchase_price_and_refreshed_quote_reach_holdings_response(client, session):
    from datetime import UTC, datetime
    from app.modules.portfolio import market_data_manager as market

    class Quotes:
        source_identity = "synthetic-return-test"

        def __init__(self):
            serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
            self.price = 150
            self.serial = serial
            self.calls = []

        def create(self):
            return "public-test-quotes"

        def read(self, sheet):
            return [["KRX:005930", self.price, "KRW", self.serial, 20]], []

        def provision(self, sheet, symbols, currencies):
            self.calls.append((symbols, currencies))

    payload = dict(position_id="return-example", request_id="return-create",
                   ticker="KRX:005930", label="Synthetic holding", currency="KRW",
                   quantity="2", avg_cost="120", quote_mode="auto")
    saved = client.post("/api/finance/holdings", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["portfolio"]["lines"][0]["unrealized_return_pct"] is None
    quotes = Quotes()
    market.initialize(session, quotes)
    market.refresh(session, quotes)
    loaded = client.get("/api/finance/holdings").json()
    line = loaded["portfolio"]["lines"][0]
    assert line["unrealized_return_pct"] == "25.00"
    assert line["unrealized_gain_native"] == "60.00"
    payload.update(request_id="return-edit", expected_version=loaded["rows"][0]["expected_version"],
                   avg_cost="100")
    edited = client.post("/api/finance/holdings", json=payload)
    assert edited.status_code == 200, edited.text
    assert edited.json()["portfolio"]["lines"][0]["unrealized_return_pct"] == "50.00"
    assert client.get("/api/finance/holdings").json()["portfolio"]["lines"][0]["unrealized_return_pct"] == "50.00"
