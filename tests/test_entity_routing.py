from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.enums.context_category import Category as C
from app.modules.context.entity_routing import matched_investment_terms
from app.modules.database.model.domain import Holding
from app.modules.database.model.google_oauth import GoogleOAuthConnection
from app.modules.database.model.portfolio import PortfolioImport, PortfolioSettings


def test_registered_local_positions_and_boundaries(session):
    session.add_all([Holding(symbol="005930", name="삼성전자", quantity=Decimal(10)),
                     Holding(symbol="AAPL", name="Apple", quantity=Decimal(2)),
                     Holding(symbol="F", name="Ford", quantity=Decimal(1))])
    session.commit()
    assert matched_investment_terms(session, "삼성전자는 몇 개 있지?") == ("삼성전자",)
    assert matched_investment_terms(session, "005930은?") == ("005930",)
    assert matched_investment_terms(session, "aapl은 얼마나 있어?") == ("aapl",)
    assert matched_investment_terms(session, "Ford shares?") == ("Ford",)
    assert matched_investment_terms(session, "PineAAPL offer 삼성전자복지") == ()
    assert matched_investment_terms(session, "모르는 종목") == ()


@pytest.mark.parametrize("query,kwargs", [
    ("", {}), ("AAPL", {"excluded": frozenset({C.INVESTMENT})}),
    ("AAPL", {"override": frozenset({C.CALENDAR})}),
])
def test_explicit_privacy_deny_does_not_query(session, query, kwargs):
    def reject(*args):
        raise AssertionError("Private investment metadata must not be queried")
    event.listen(session.bind, "before_cursor_execute", reject)
    try:
        assert matched_investment_terms(session, query, **kwargs) == ()
    finally:
        event.remove(session.bind, "before_cursor_execute", reject)


def test_sheets_latest_selected_identity_only(session, monkeypatch):
    from app.modules.auth.google_oauth_manager import google_oauth_manager
    monkeypatch.setattr(google_oauth_manager, "settings", replace(google_oauth_manager.settings, google_oauth_client_id="entity-test"))
    session.add(PortfolioSettings(id=1, spreadsheet_id="selected"))
    session.add(GoogleOAuthConnection(id=1, subject="user", status="connected", ciphertext=b"never-read"))
    session.add(Holding(symbol="LOCAL", quantity=Decimal(1)))
    session.add_all([
        PortfolioImport(spreadsheet_id="selected", source_identity="oauth:user:entity-test",
                        payload={"Holdings": [{"ticker": "OLD", "label": "Old"}]}),
        PortfolioImport(spreadsheet_id="selected", source_identity="oauth:user:entity-test",
                        payload={"Holdings": [{"ticker": "NEW", "label": "신규종목"}], "Cash": [{"secret": "not fetched"}]}),
        PortfolioImport(spreadsheet_id="other", source_identity="oauth:user:entity-test",
                        payload={"Holdings": [{"ticker": "OTHER"}]}),
        PortfolioImport(spreadsheet_id="selected", source_identity="oauth:someone-else:entity-test",
                        payload={"Holdings": [{"ticker": "WRONG"}]}),
    ])
    session.commit()
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        assert matched_investment_terms(session, "NEW 신규종목은 OLD OTHER WRONG LOCAL") == ("NEW", "신규종목")
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert not any("ciphertext" in statement or "quantity" in statement for statement in statements)
    assert not any("portfolio_imports.payload AS" in statement for statement in statements)
    connection = session.get(GoogleOAuthConnection, 1)
    connection.status = "disconnected"
    session.commit()
    assert matched_investment_terms(session, "NEW 신규종목은") == ()


def test_sheets_adc_legacy_identity(session):
    session.add(PortfolioSettings(id=1, spreadsheet_id="selected"))
    session.add(PortfolioImport(spreadsheet_id="selected", source_identity=None,
                                payload={"Holdings": [{"ticker": "AAPL"}]}))
    session.commit()
    assert matched_investment_terms(session, "AAPL?") == ("AAPL",)
