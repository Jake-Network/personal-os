"""Google connection selection cannot transfer quote proof or fall back silently."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.modules.auth.google_oauth_manager import google_oauth_manager
from app.modules.database.model.google_oauth import GoogleOAuthConnection
from app.modules.portfolio import portfolio_manager as manager
from app.modules.portfolio.sheets import SheetsClient, TABS


class FakeSheet:
    def verify(self, spreadsheet_id):
        return {"quote": "10", "fx": "1400", "formulas": []}

    def tables(self, spreadsheet_id):
        tables = {tab: [] for tab in TABS}
        tables["Holdings"] = [{"id": "h", "label": "Stock", "ticker": "TEST", "currency": "KRW",
                               "quantity": "2", "price": "10", "price_as_of": date.today().isoformat(),
                               "as_of": date.today().isoformat(), "source": "googlefinance"}]
        tables["Coverage"] = [{"month": "current", **{k: "TRUE" for k in manager.KINDS}}]
        return tables


def test_adc_proof_and_import_are_not_reused_after_google_login(session):
    manager.configure(session, "private-spreadsheet")
    manager.verify(session, FakeSheet())
    assert manager.sync(session, FakeSheet())["investments"] == "20.00"
    connection = GoogleOAuthConnection(id=1, status="connected", subject="account-a", scopes=[])
    session.add(connection)
    session.commit()
    assert manager.portfolio(session)["import_id"] is None
    imported = manager.sync(session, FakeSheet())
    assert imported["investments"] is None
    manager.verify(session, FakeSheet())
    assert manager.portfolio(session)["investments"] == "20.00"


def test_google_account_switch_requires_its_own_import_and_quote_verification(session):
    connection = GoogleOAuthConnection(id=1, status="connected", subject="account-a", scopes=[])
    session.add(connection)
    session.commit()
    manager.configure(session, "private-spreadsheet")
    manager.verify(session, FakeSheet())
    manager.sync(session, FakeSheet())
    connection.subject = "account-b"
    session.commit()
    assert manager.portfolio(session)["import_id"] is None
    assert manager.sync(session, FakeSheet())["investments"] is None
    manager.verify(session, FakeSheet())
    assert manager.portfolio(session)["investments"] == "20.00"
    connection.status = "needs_reauth"
    session.commit()
    result = manager.portfolio(session)
    assert result["investments"] is None
    assert result["stale"] is True


def test_sheets_client_uses_google_user_credentials_before_adc(session, monkeypatch):
    import google.auth
    import googleapiclient.discovery
    credentials = object()
    provider = MagicMock(return_value=credentials)
    adc = MagicMock()
    build = MagicMock()
    monkeypatch.setattr(google_oauth_manager, "get_credentials", provider)
    monkeypatch.setattr(google.auth, "default", adc)
    monkeypatch.setattr(googleapiclient.discovery, "build", build)
    SheetsClient(session=session)
    provider.assert_called_once_with(session)
    adc.assert_not_called()
    assert build.call_args.kwargs["credentials"] is credentials


def test_disconnected_google_user_cannot_silently_read_with_adc(session, monkeypatch):
    import google.auth
    session.add(GoogleOAuthConnection(id=1, status="disconnected", scopes=[]))
    session.commit()
    adc = MagicMock()
    monkeypatch.setattr(google.auth, "default", adc)
    with pytest.raises(ValueError, match="disconnected"):
        SheetsClient(session=session)
    adc.assert_not_called()


def test_legacy_adc_remains_available_only_before_google_connection(session, monkeypatch):
    import google.auth
    import googleapiclient.discovery
    credentials = object()
    adc = MagicMock(return_value=(credentials, None))
    build = MagicMock()
    monkeypatch.setattr(google.auth, "default", adc)
    monkeypatch.setattr(googleapiclient.discovery, "build", build)
    SheetsClient(session=session)
    adc.assert_called_once()
    assert build.call_args.kwargs["credentials"] is credentials


@pytest.mark.parametrize("operation", ["verify", "sync"])
@pytest.mark.parametrize("change", ["principal", "spreadsheet"])
def test_retrieval_cannot_be_relabelled_by_concurrent_configuration(session, operation, change):
    from app.modules.database import db
    from app.modules.database.model.portfolio import PortfolioImport
    from sqlalchemy import select
    session.add(GoogleOAuthConnection(id=1, status="connected", subject="account-a", scopes=[]))
    session.commit()
    manager.configure(session, "private-spreadsheet")

    class ChangedDuringRead(FakeSheet):
        def change_source(self):
            with db.session() as other:
                if change == "principal":
                    other.get(GoogleOAuthConnection, 1).subject = "account-b"
                    other.commit()
                else:
                    manager.configure(other, "different-spreadsheet")

        def verify(self, spreadsheet_id):
            self.change_source()
            return super().verify(spreadsheet_id)

        def tables(self, spreadsheet_id):
            self.change_source()
            return super().tables(spreadsheet_id)

    with pytest.raises(ValueError):
        getattr(manager, operation)(session, ChangedDuringRead())
    assert manager.get_settings(session).verified_at is None
    assert session.scalars(select(PortfolioImport)).all() == []
