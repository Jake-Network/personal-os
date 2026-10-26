"""Current local valuation uses one current FX rate per pair, refreshed in place."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.database.model import FxRate, Holding, MarketSettings
from app.modules.portfolio import holdings_manager


class FxQuotes:
    source_identity = "synthetic-fx-test"

    def __init__(self):
        self.rate = "1400"

    def create(self):
        return "public-test-quotes"

    def read(self, sheet):
        serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
        return [["NASDAQ:TEST", 150, "USD", serial, 20]], [["USDKRW", self.rate]]

    def provision(self, sheet, symbols, currencies):
        pass


def usd_holding(client):
    saved = client.post("/api/finance/holdings", json=dict(
        position_id="fx-example", request_id="fx-create", ticker="NASDAQ:TEST",
        label="Synthetic holding", currency="USD", quantity="2", quote_mode="auto"))
    assert saved.status_code == 200, saved.text


def test_refresh_keeps_one_current_rate_per_pair(client, session):
    from app.modules.portfolio import market_data_manager as market

    usd_holding(client)
    quotes = FxQuotes()
    market.initialize(session, quotes)
    stamps = []
    # Returning to an earlier value must still become current, with a fresh as_of.
    for rate in ("1400", "1410", "1400"):
        quotes.rate = rate
        session.get(MarketSettings, 1).last_attempt_at = None  # skip the refresh cooldown
        session.commit()
        market.refresh(session, quotes)
        session.expire_all()
        row = session.query(FxRate).one()
        assert (row.base, row.quote, row.rate) == ("USD", "KRW", Decimal(rate))
        stamps.append(row.as_of)
    assert stamps == sorted(stamps) and stamps[0] < stamps[-1]
    line = holdings_manager.listing(session)["portfolio"]["lines"][0]
    assert Decimal(line["fx_rate"]) == Decimal("1400")


def test_refresh_does_not_overwrite_a_later_manual_rate(client, session):
    from app.modules.portfolio import market_data_manager as market

    usd_holding(client)
    later = datetime.now(UTC) + timedelta(hours=1)
    session.add(FxRate(base="USD", quote="KRW", rate=Decimal("1500"), as_of=later))
    session.commit()
    quotes = FxQuotes()
    market.initialize(session, quotes)
    market.refresh(session, quotes)
    session.expire_all()
    assert session.query(FxRate).one().rate == Decimal("1500")


def test_manual_entry_for_existing_pair_replaces_the_current_rate(client, session):
    first = client.post("/api/data/fx-rates", json=dict(
        base="USD", quote="KRW", rate="1300", as_of=datetime.now(UTC).isoformat()))
    assert first.status_code == 201, first.text
    second = client.post("/api/data/fx-rates", json=dict(
        base="USD", quote="KRW", rate="1450", as_of=datetime.now(UTC).isoformat()))
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert [(r["base"], r["rate"]) for r in client.get("/api/data/fx-rates").json()] == [("USD", "1450.00000000")]


@pytest.mark.parametrize("age, expected_issue", [
    (None, "Missing or invalid FX evidence"),
    (10, "Stale FX rate"),
])
def test_missing_and_stale_fx_remain_visible(session, age, expected_issue):
    now = datetime.now(UTC)
    session.add(Holding(symbol="NASDAQ:TEST", currency="USD", quantity=Decimal("2"),
                        last_price=Decimal("150"), price_as_of=now))
    if age is not None:
        session.add(FxRate(base="USD", quote="KRW", rate=Decimal("1400"),
                           as_of=now - timedelta(days=age)))
    session.commit()
    line = holdings_manager.listing(session)["portfolio"]["lines"][0]
    assert expected_issue in line["issues"]
    assert line["value_krw"] == (None if age is None else "420000.00")


def test_editing_a_rate_into_an_existing_pair_is_rejected(client):
    now = datetime.now(UTC).isoformat()
    client.post("/api/data/fx-rates", json=dict(base="USD", quote="KRW", rate="1400", as_of=now))
    jpy = client.post("/api/data/fx-rates", json=dict(base="JPY", quote="KRW", rate="9.1", as_of=now)).json()
    moved = client.put(f"/api/data/fx-rates/{jpy['id']}", json=dict(base="USD", quote="KRW", rate="1410", as_of=now))
    assert moved.status_code == 422
    assert {r["base"]: r["rate"] for r in client.get("/api/data/fx-rates").json()} == {
        "USD": "1400.00000000", "JPY": "9.10000000"}
