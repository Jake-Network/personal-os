"""Explicit quotes reconnection remains bound to the selected Google account."""

from datetime import UTC, datetime

import pytest

from app.modules.database.model import Holding, LocalPosition, MarketSettings
from app.modules.portfolio import market_data_manager as market
from app.modules.portfolio import portfolio_manager
from app.schema.market_data_schema import QuotesReplacementInput


class NewAccountQuotes:
    source_identity = "account-b"

    def __init__(self, on_create=None):
        self.on_create = on_create
        self.created = 0

    def create(self):
        self.created += 1
        if self.on_create:
            self.on_create()
        return "account-b-quotes"


def setup_connection(session, monkeypatch):
    current = ["account-b"]
    monkeypatch.setattr(portfolio_manager, "_source", lambda session: (current[0], False))
    session.add(MarketSettings(
        id=1, spreadsheet_id="account-a-quotes", source_identity="account-a",
        last_attempt_at=datetime.now(UTC), last_success_at=datetime.now(UTC),
        last_error="old failure",
    ))
    session.commit()
    state = market.status(session)
    body = QuotesReplacementInput(
        expected_spreadsheet_id=state["spreadsheet_id"],
        expected_account_key=state["current_account_key"],
    )
    return current, body


def test_account_switch_requires_explicit_replacement_and_allows_refresh(session, monkeypatch):
    _, body = setup_connection(session, monkeypatch)
    fake = NewAccountQuotes()
    assert not market.status(session)["account_matches"]
    with pytest.raises(ValueError, match="explicitly replace"):
        market.initialize(session, fake)
    assert fake.created == 0
    result = market.replace(session, body, fake)
    assert result["account_matches"]
    assert result["spreadsheet_id"] == "account-b-quotes"
    assert result["last_attempt_at"] is None
    assert result["last_success_at"] is None
    assert result["last_error"] is None
    assert session.get(MarketSettings, 1).source_identity == "account-b"
    assert market.initialize(session, fake)["spreadsheet_id"] == "account-b-quotes"
    assert fake.created == 1


def test_failed_creation_keeps_previous_connection(session, monkeypatch):
    _, body = setup_connection(session, monkeypatch)

    def fail():
        raise ValueError("offline")

    with pytest.raises(ValueError, match="offline"):
        market.replace(session, body, NewAccountQuotes(fail))
    assert session.get(MarketSettings, 1).spreadsheet_id == "account-a-quotes"
    assert session.get(MarketSettings, 1).last_error == "old failure"


@pytest.mark.parametrize("during_creation", [False, True])
def test_account_change_rejects_stale_replacement(session, monkeypatch, during_creation):
    current, body = setup_connection(session, monkeypatch)

    def switch():
        current[0] = "account-c"

    fake = NewAccountQuotes(switch if during_creation else None)
    if not during_creation:
        switch()
    with pytest.raises(RuntimeError, match="account changed"):
        market.replace(session, body, fake)
    assert fake.created == int(during_creation)
    assert session.get(MarketSettings, 1).spreadsheet_id == "account-a-quotes"


def test_concurrent_replacement_does_not_overwrite_newer_connection(session, monkeypatch):
    _, body = setup_connection(session, monkeypatch)

    def change_connection():
        session.get(MarketSettings, 1).spreadsheet_id = "newer-file"
        session.commit()

    with pytest.raises(RuntimeError, match="connection changed"):
        market.replace(session, body, NewAccountQuotes(change_connection))
    assert session.get(MarketSettings, 1).spreadsheet_id == "newer-file"


def test_replace_endpoint_validates_and_applies_current_account(session, client, monkeypatch):
    _, body = setup_connection(session, monkeypatch)
    fake = NewAccountQuotes()
    monkeypatch.setattr(market, "QuotesSheet", lambda session: fake)
    result = client.post("/api/market-data/replace", json=body.model_dump())
    assert result.status_code == 200
    assert result.json()["account_matches"]
    assert client.post("/api/market-data/replace", json=body.model_dump()).status_code == 409
    assert fake.created == 1


@pytest.mark.parametrize("during_provision", [False, True])
def test_replacement_during_refresh_rejects_old_file_prices(session, monkeypatch, during_provision):
    monkeypatch.setattr(portfolio_manager, "_source", lambda session: ("account-b", False))
    holding = Holding(symbol="KRX:005930", currency="KRW", quantity=1)
    session.add(holding)
    session.flush()
    session.add(LocalPosition(position_id="p", holding_id=holding.id, quote_mode="auto", version="v"))
    session.add(MarketSettings(id=1, spreadsheet_id="old-file", source_identity="account-b"))
    session.commit()
    body = QuotesReplacementInput(expected_spreadsheet_id="old-file", expected_account_key=market.status(session)["current_account_key"])

    class ReplacingQuotes(NewAccountQuotes):
        def read(self, spreadsheet_id):
            assert spreadsheet_id == "old-file"
            if during_provision:
                return [], []
            market.replace(session, body, NewAccountQuotes())
            serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
            return [["KRX:005930", 20, "KRW", serial, 20]], []

        def provision(self, spreadsheet_id, symbols, currencies):
            assert spreadsheet_id == "old-file"
            market.replace(session, body, NewAccountQuotes())

    result = market.refresh(session, ReplacingQuotes())
    assert result["warning"]
    assert session.get(Holding, holding.id).last_price is None
    settings = session.get(MarketSettings, 1)
    assert settings.spreadsheet_id == "account-b-quotes"
    assert settings.last_attempt_at is None
    assert settings.last_error is None
