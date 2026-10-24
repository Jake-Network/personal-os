"""Retrieval must preserve concurrent local edits and previously valid prices."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.modules.database.model import Base, Holding, LocalPosition, MarketSettings
from app.modules.portfolio import holdings_manager as holdings
from app.modules.portfolio import market_data_manager as market
from app.schema.holdings_schema import HoldingInput


@pytest.fixture
def quote_session(tmp_path, postgres_url):
    engine = create_engine(postgres_url)
    Base.metadata.create_all(engine, checkfirst=False)
    with Session(engine) as session:
        yield session
    engine.dispose()


def auto_input(**changes):
    return HoldingInput(**{
        "position_id": "local-a", "ticker": "KRX:005930", "label": "Synthetic",
        "currency": "KRW", "quantity": 2, **changes,
    })


class Quotes:
    source_identity = "synthetic"

    def create(self):
        return "synthetic-quotes"

    def read(self, _sheet):
        serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
        return [["KRX:005930", 20, "KRW", serial, 20]], []


@pytest.mark.parametrize("unavailable", ["provider_error", "unsupported"])
def test_partial_refresh_preserves_valid_prices_and_reports_warning(quote_session, unavailable):
    session = quote_session
    holdings.save(session, auto_input())
    ticker = "KRX:000660" if unavailable == "provider_error" else "UNSUPPORTED:TEST"
    holdings.save(session, auto_input(position_id="local-b", ticker=ticker))
    fake = Quotes()
    original_read = fake.read

    def read(sheet):
        quotes, fx = original_read(sheet)
        if unavailable == "provider_error":
            quotes.append([ticker, "#N/A", "KRW", 0, 20])
        return quotes, fx

    fake.read = read
    market.initialize(session, fake)
    result = holdings.refresh(session, fake)
    assert result["refresh_state"] == "partial"
    assert ticker in result["warning"]
    session.expire_all()
    good = session.scalar(select(Holding).where(Holding.symbol == "KRX:005930"))
    unavailable_holding = session.scalar(select(Holding).where(Holding.symbol == ticker))
    assert good.last_price == Decimal("20")
    assert unavailable_holding.last_price is None
    assert session.get(MarketSettings, 1).last_success_at is not None


@pytest.mark.parametrize("edit", ["manual", "symbol", "currency", "mode_roundtrip"])
def test_inflight_quote_cannot_overwrite_local_edit(quote_session, edit):
    session = quote_session
    holdings.save(session, auto_input())
    fake = Quotes()
    market.initialize(session, fake)
    original_read = fake.read

    def read(sheet):
        # A distinct transaction commits while the refresh waits on Google.
        with Session(session.bind) as writer:
            row = holdings.listing(writer)["rows"][0]
            changes = {
                "expected_version": row["expected_version"],
                "quote_mode": "manual", "manual_price": 999,
                "price_as_of": date.today() - timedelta(days=1),
            }
            if edit == "symbol":
                changes["ticker"] = "KRX:000660"
            elif edit == "currency":
                changes["currency"] = "USD"
            saved = holdings.save(writer, auto_input(**changes))
            if edit == "mode_roundtrip":
                holdings.save(writer, auto_input(expected_version=saved["rows"][0]["expected_version"]))
        return original_read(sheet)

    fake.read = read
    result = market.refresh(session, fake)
    assert not result.get("warning")
    session.expire_all()
    obj = session.scalar(select(Holding))
    mapping = session.scalar(select(LocalPosition))
    if edit == "mode_roundtrip":
        assert mapping.quote_mode == "auto"
        assert obj.last_price is None and obj.price_as_of is None
    else:
        assert mapping.quote_mode == "manual"
        assert obj.last_price == Decimal("999")
        assert obj.price_as_of.date() == date.today() - timedelta(days=1)


@pytest.mark.parametrize("changes", [
    {"label": "Corrected"}, {"quantity": 3}, {"avg_cost": "10.5"},
    {"asset_class": "etf"},
])
def test_unrelated_save_preserves_quote_during_cooldown(quote_session, changes):
    session = quote_session
    holdings.save(session, auto_input())
    fake = Quotes()
    market.initialize(session, fake)
    market.refresh(session, fake)
    session.expire_all()
    obj = session.scalar(select(Holding))
    price, observed = obj.last_price, obj.price_as_of
    assert price == 20 and observed is not None
    row = holdings.listing(session)["rows"][0]
    saved = holdings.save(session, auto_input(expected_version=row["expected_version"], **changes))
    assert saved["quote_status"] == "ready"
    assert market.refresh(session, fake)["refresh_after_seconds"] > 0
    session.refresh(obj)
    assert obj.last_price == price and obj.price_as_of == observed


@pytest.mark.parametrize("changes", [
    {"ticker": "KRX:000660"}, {"currency": "USD"},
])
def test_changed_quote_identity_invalidates_old_price(quote_session, changes):
    session = quote_session
    holdings.save(session, auto_input())
    fake = Quotes()
    market.initialize(session, fake)
    market.refresh(session, fake)
    session.expire_all()
    row = holdings.listing(session)["rows"][0]
    saved = holdings.save(session, auto_input(expected_version=row["expected_version"], **changes))
    assert saved["quote_status"] == "pending"
    obj = session.scalar(select(Holding))
    assert obj.last_price is None and obj.price_as_of is None
