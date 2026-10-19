"""Current local valuation uses the newest FX observation, including intraday updates."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.database.model import FxRate, Holding
from app.modules.portfolio import holdings_manager


def test_holdings_use_latest_intraday_fx_without_discarding_observations(session):
    now = datetime.now(UTC)
    # Keep both observations on the same calendar day even around midnight.
    first = now.replace(hour=0, minute=0, second=0, microsecond=0)
    session.add(Holding(symbol="NASDAQ:TEST", currency="USD", quantity=Decimal("2"),
                        last_price=Decimal("150"), price_as_of=now))
    session.add_all([
        FxRate(base="USD", quote="KRW", rate=Decimal("1300"), as_of=first),
        FxRate(base="USD", quote="KRW", rate=Decimal("1400"), as_of=now),
        FxRate(base="USD", quote="KRW", rate=Decimal("1500"), as_of=now + timedelta(hours=1)),
    ])
    session.commit()

    line = holdings_manager.listing(session)["portfolio"]["lines"][0]
    assert Decimal(line["fx_rate"]) == Decimal("1400")
    assert line["value_krw"] == "420000.00"
    assert "Missing or invalid FX evidence" not in line["issues"]
    assert "Valuation unavailable" not in line["issues"]
    assert session.query(FxRate).count() == 3


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
