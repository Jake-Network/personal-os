"""Portfolio regressions using synthetic Sheets responses, never market services."""
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.modules.portfolio.sheets import SheetsClient, TABS


def sheets_client():
    client = SheetsClient.__new__(SheetsClient)
    client.service = MagicMock()
    return client


def test_official_sheets_reader_requests_evaluated_values_and_preserves_missing():
    client = sheets_client()
    request = client.service.spreadsheets.return_value.values.return_value.batchGet
    request.return_value.execute.return_value = {
        "valueRanges": [{"values": [["price", "quantity"], [12.125]]}, {}]
    }
    assert client.read("private-sheet", ["Holdings!A1:B2", "FX!A1"]) == [
        [["price", "quantity"], [12.125]], []
    ]
    request.assert_called_once_with(
        spreadsheetId="private-sheet", ranges=["Holdings!A1:B2", "FX!A1"],
        valueRenderOption="UNFORMATTED_VALUE", dateTimeRenderOption="FORMATTED_STRING",
    )


def test_tables_keep_missing_distinct_from_explicit_zero():
    client = sheets_client()
    client.read = MagicMock(return_value=[
        [["id", "balance"], ["missing"], ["zero", 0]],
        *([[]] * (len(TABS) - 1)),
    ])
    rows = client.tables("private-sheet")["Cash"]
    assert rows == [{"id": "missing", "balance": ""}, {"id": "zero", "balance": "0"}]


@pytest.mark.parametrize("rows", [
    [["id", "id"], ["x", 1]],
    [["id", ""], ["x", 1]],
])
def test_invalid_duplicate_or_empty_headers_rejected(rows):
    client = sheets_client()
    client.read = MagicMock(return_value=[rows, *([[]] * (len(TABS) - 1))])
    with pytest.raises(ValueError, match="headers"):
        client.tables("private-sheet")


def test_missing_tab_response_rejected():
    client = sheets_client()
    client.read = MagicMock(return_value=[[]])
    with pytest.raises(ValueError, match="Incomplete"):
        client.tables("private-sheet")


QUOTE_FORMULA = '=GOOGLEFINANCE("NASDAQ:GOOG", "price")'
FX_FORMULA = '=GOOGLEFINANCE("CURRENCY:USDKRW")'


def test_current_formula_verification_reads_same_cells_as_formulas_and_values():
    client = sheets_client()
    client.read = MagicMock(side_effect=[[[[QUOTE_FORMULA, FX_FORMULA]]], [[[185.125, 1398.75]]]])
    proof = client.verify("private-sheet")
    assert Decimal(proof["quote"]) == Decimal("185.125")
    assert Decimal(proof["fx"]) == Decimal("1398.75")
    assert proof["formulas"] == [QUOTE_FORMULA, FX_FORMULA]
    assert client.read.call_args_list[0].args[-1] == "FORMULA"
    assert client.read.call_args_list[0].args[1] == client.read.call_args_list[1].args[1]


@pytest.mark.parametrize("value", [None, "", "#N/A", "#REF!", "NaN", "Infinity", 0, -1])
def test_verification_rejects_unavailable_and_nonfinite_quotes(value):
    client = sheets_client()
    client.read = MagicMock(side_effect=[[[[QUOTE_FORMULA, FX_FORMULA]]], [[[value, 1400]]]])
    with pytest.raises(ValueError, match="unavailable"):
        client.verify("private-sheet")


@pytest.mark.parametrize("formula", [
    '=GOOGLEFINANCE("NASDAQ:GOOG", "close", DATE(2026, 9, 30))',
    '=GOOGLEFINANCE("NASDAQ:GOOG", "price", TODAY()-30, TODAY())',
    '=IFERROR(GOOGLEFINANCE("NASDAQ:GOOG", "price"), 0)',
    '185.125',
])
def test_historical_or_wrapped_formula_cannot_satisfy_current_value_gate(formula):
    client = sheets_client()
    client.read = MagicMock(side_effect=[[[[formula, FX_FORMULA]]], [[[185.125, 1400]]]])
    with pytest.raises(ValueError):
        client.verify("private-sheet")


@pytest.fixture
def sheet_tables():
    """October's quantity deliberately differs from the September history."""
    return {
        "Cash": [{"id": "bank", "label": "Cash", "currency": "KRW", "balance": "1000000",
                  "as_of": "2026-10-17"}],
        "Holdings": [{"id": "goog", "label": "Google", "ticker": "NASDAQ:GOOG", "currency": "USD",
                      "quantity": "20", "avg_cost": "100", "price": "185.125", "source": "manual",
                      "as_of": "2026-10-17", "price_as_of": "2026-10-16"}],
        "Liabilities": [{"id": "loan", "label": "Loan", "currency": "KRW", "balance": "100000",
                         "as_of": "2026-10-17"}],
        "OtherAssets": [],
        "FX": [{"currency": "USD", "rate": "1400", "as_of": "2026-09-30", "source": "manual"},
               {"currency": "USD", "rate": "1420", "as_of": "2026-10-16", "source": "manual"}],
        "Closes": [
            {"ticker": "NASDAQ:GOOG", "currency": "USD", "price": "120", "as_of": "2026-09-29", "valid_through": "2026-09-30", "source": "manual"},
            {"ticker": "NASDAQ:GOOG", "currency": "USD", "price": "125", "as_of": "2026-09-30", "valid_through": "2026-09-30", "source": "manual"},
            {"ticker": "NASDAQ:GOOG", "currency": "USD", "price": "200", "as_of": "2026-10-01", "source": "manual"},
        ],
        "History": [
            {"month": "2026-09", "kind": "cash", "id": "bank", "label": "Cash", "currency": "KRW",
             "balance": "1000000", "as_of": "2026-09-30"},
            {"month": "2026-09", "kind": "holding", "id": "goog", "label": "Google", "ticker": "NASDAQ:GOOG",
             "currency": "USD", "quantity": "2.5", "avg_cost": "100", "as_of": "2026-09-30"},
            {"month": "2026-09", "kind": "liability", "id": "loan", "label": "Loan", "currency": "KRW",
             "balance": "100000", "as_of": "2026-09-30"},
        ],
        "Coverage": [
            {"month": "current", "cash": "true", "holding": "true", "liability": "true", "other": "true"},
            {"month": "2026-09", "cash": "true", "holding": "true", "liability": "true", "other": "true"},
        ],
    }


class FakeSheets:
    def __init__(self, tables, error=None):
        self.data = tables
        self.error = error

    def tables(self, spreadsheet_id):
        if self.error:
            raise self.error
        return self.data

    def verify(self, spreadsheet_id):
        if self.error:
            raise self.error
        return {"quote": "185.125", "fx": "1420", "formulas": [QUOTE_FORMULA, FX_FORMULA]}


@pytest.fixture
def portfolio_api(client, session, monkeypatch, sheet_tables):
    from app.modules.portfolio import portfolio_manager as manager

    class OctoberDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 17)

    monkeypatch.setattr(manager, "date", OctoberDate)
    fake = FakeSheets(sheet_tables)
    monkeypatch.setattr(manager, "SheetsClient", lambda **kwargs: fake)
    # Historical import evaluation stays tested directly after public personal-Sheets
    # endpoints retire. Snapshot/history requests still use the actual API.
    import httpx
    manager.configure(session, "private-test-sheet")
    class LegacyImportHarness:
        def put(self, path, json):
            if path == "/api/finance/settings":
                from app.schema.portfolio_schema import SheetsSettingsInput
                try:
                    data = SheetsSettingsInput(**json)
                    value = manager.configure(session, data.spreadsheet_id)
                    return httpx.Response(200, json=value)
                except ValueError as exc:
                    return httpx.Response(422, json={"detail": str(exc)})
            return client.put(path, json=json)
        def post(self, path, **kwargs):
            if path in {"/api/finance/sync", "/api/finance/verify"}:
                try:
                    value = manager.sync(session) if path.endswith("sync") else manager.verify(session)
                    from fastapi.encoders import jsonable_encoder
                    return httpx.Response(200, json=jsonable_encoder(value))
                except ValueError as exc:
                    return httpx.Response(422, json={"detail": str(exc)})
            return client.post(path, **kwargs)
        def get(self, path):
            if path == "/api/finance/portfolio":
                return httpx.Response(200, json=manager.imported_portfolio_preview(session))
            return client.get(path)
    return LegacyImportHarness(), fake


def import_sheet(portfolio_api):
    client, fake = portfolio_api
    response = client.post("/api/finance/sync")
    assert response.status_code == 200, response.text
    return client, fake, response.json()


def test_portfolio_decimal_valuation_fx_and_unrealized_gain(portfolio_api):
    _, _, data = import_sheet(portfolio_api)
    assert data["complete"] is True
    assert data["net_worth"] == "6157550.00"
    holding = next(row for row in data["lines"] if row["kind"] == "holding")
    assert Decimal(holding["value_krw"]) == Decimal("20") * Decimal("185.125") * Decimal("1420")
    assert Decimal(holding["unrealized_gain_krw"]) == Decimal("20") * Decimal("85.125") * Decimal("1420")
    assert holding["fx_rate"] == "1420"
    assert holding["fx_as_of"] == "2026-10-16"
    assert data["synced_at"]


def test_sync_failure_retains_last_success_and_sanitizes_error(portfolio_api, session):
    from app.modules.database.model.portfolio import PortfolioImport

    client, fake, good = import_sheet(portfolio_api)
    before = client.get("/api/finance/settings").json()
    fake.error = RuntimeError("private credential secret and spreadsheet contents")
    response = client.post("/api/finance/sync")
    assert response.status_code == 422
    assert "private credential" not in response.text
    after = client.get("/api/finance/settings").json()
    assert after["last_success_at"] == before["last_success_at"]
    assert after["last_sync_at"] and after["last_error"]
    current = client.get("/api/finance/portfolio").json()
    assert current["net_worth"] == good["net_worth"]
    assert current["synced_at"] == good["synced_at"]
    assert current["stale"] is True
    assert len(session.scalars(select(PortfolioImport)).all()) == 1


def test_missing_worksheet_does_not_partially_replace_import(portfolio_api):
    client, fake, good = import_sheet(portfolio_api)
    fake.data = {"Cash": []}
    assert client.post("/api/finance/sync").status_code == 422
    assert client.get("/api/finance/portfolio").json()["net_worth"] == good["net_worth"]


@pytest.mark.parametrize("field", ["price", "quantity"])
def test_missing_current_holding_fields_never_become_zero(portfolio_api, field):
    client, fake = portfolio_api
    fake.data["Holdings"][0][field] = ""
    data = client.post("/api/finance/sync").json()
    assert data["complete"] is False
    assert data["net_worth"] is None and data["total_assets"] is None
    assert next(row for row in data["lines"] if row["kind"] == "holding")["value_krw"] is None


def test_googlefinance_quote_is_gated_until_actual_verification(portfolio_api):
    client, fake = portfolio_api
    fake.data["Holdings"][0]["source"] = "googlefinance"
    data = client.post("/api/finance/sync").json()
    assert data["investments"] is None
    assert client.get("/api/finance/settings").json()["verified_at"] is None
    assert client.post("/api/finance/verify").status_code == 200
    assert client.get("/api/finance/portfolio").json()["complete"] is True
    assert client.get("/api/finance/settings").json()["verified_at"]
    fake.error = ValueError("#N/A")
    assert client.post("/api/finance/verify").status_code == 422
    assert client.get("/api/finance/portfolio").json()["investments"] is None


def test_missing_fx_is_not_assumed_to_be_one(portfolio_api):
    client, fake = portfolio_api
    fake.data["FX"] = []
    data = client.post("/api/finance/sync").json()
    assert data["net_worth"] is None
    holding = next(row for row in data["lines"] if row["kind"] == "holding")
    assert holding["value_krw"] is None and holding["fx_rate"] is None


def test_empty_categories_require_explicit_coverage(portfolio_api):
    client, fake = portfolio_api
    fake.data["Coverage"] = []
    data = client.post("/api/finance/sync").json()
    assert data["complete"] is False
    assert data["net_worth"] is None
    assert any("coverage" in issue for issue in data["issues"])


def test_month_end_snapshot_uses_historical_quantity_and_last_close(portfolio_api):
    client, _, _ = import_sheet(portfolio_api)
    response = client.post("/api/finance/history", json={"month": "2026-09-01"})
    assert response.status_code == 201, response.text
    snap = response.json()
    assert snap["complete"] is True
    assert snap["net_worth"] == "1337500.00"
    row = next(row for row in snap["lines"] if row["kind"] == "holding")
    assert row["quantity"] == "2.5"
    assert row["price"] == "125"
    assert row["price_as_of"] == "2026-09-30"
    assert row["fx_rate"] == "1400"
    assert row["fx_as_of"] == "2026-09-30"


def test_snapshot_creation_is_idempotent_and_keeps_original_evidence(portfolio_api, session):
    from app.modules.database.model.portfolio import MonthlySnapshot

    client, fake, _ = import_sheet(portfolio_api)
    first = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    fake.data["History"][1]["quantity"] = "99"
    assert client.post("/api/finance/sync").status_code == 200
    second = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    assert second == first
    assert len(session.scalars(select(MonthlySnapshot)).all()) == 1


def test_no_historical_quantity_is_reconstructed_from_current_holdings(portfolio_api):
    client, fake = portfolio_api
    fake.data["History"] = []
    fake.data["Coverage"] = [r for r in fake.data["Coverage"] if r["month"] == "current"]
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    assert snap["complete"] is False and snap["net_worth"] is None
    assert snap["lines"] == []


def test_historical_googlefinance_arrays_are_never_used_as_close_evidence(portfolio_api):
    client, fake = portfolio_api
    for row in fake.data["Closes"]:
        row["source"] = "googlefinance"
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    assert snap["net_worth"] is None and snap["complete"] is False
    assert next(row for row in snap["lines"] if row["kind"] == "holding")["price"] is None


def test_month_end_on_weekend_uses_preceding_valid_close(portfolio_api):
    client, fake = portfolio_api
    # August 31, 2026 is Monday. May 31 is Sunday; May 29 is Friday.
    for row in fake.data["History"]:
        row["month"], row["as_of"] = "2026-05", "2026-05-31"
    fake.data["Coverage"][1]["month"] = "2026-05"
    fake.data["Closes"] = [
        {"ticker": "NASDAQ:GOOG", "currency": "USD", "price": "125", "as_of": "2026-05-29", "valid_through": "2026-05-31", "source": "manual"},
        {"ticker": "NASDAQ:GOOG", "currency": "USD", "price": "999", "as_of": "2026-06-01", "source": "manual"},
    ]
    fake.data["FX"] = [{"currency": "USD", "rate": "1400", "as_of": "2026-05-29", "source": "manual"}]
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-05-01"}).json()
    assert snap["net_worth"] == "1337500.00"
    assert next(row for row in snap["lines"] if row["kind"] == "holding")["price_as_of"] == "2026-05-29"


def test_missing_historical_price_is_not_fabricated(portfolio_api):
    client, fake = portfolio_api
    fake.data["Closes"] = [fake.data["Closes"][-1]]  # future evidence only
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    assert snap["net_worth"] is None
    assert snap["investments"] is None


def test_correction_appends_audited_revision_and_rejects_stale_edit(portfolio_api):
    client, _, _ = import_sheet(portfolio_api)
    first = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    body = {"reason": "Reconciled statement ending balance", "coverage": ["cash", "holding", "liability", "other"],
            "rows": [{"kind": "cash", "id": "bank", "label": "Cash", "currency": "KRW",
                      "as_of": "2026-09-30", "balance": "1200000.125"}]}
    response = client.post(f"/api/finance/history/{first['id']}/corrections", json=body)
    assert response.status_code == 201, response.text
    corrected = response.json()
    assert corrected["revision"] == 2 and corrected["supersedes_id"] == first["id"]
    assert corrected["net_worth"] == "1200000.12"
    audit = client.get(f"/api/finance/history/{first['id']}/audit").json()
    assert audit == [first, corrected]
    assert client.post(f"/api/finance/history/{first['id']}/corrections", json=body).status_code == 409
    assert client.get("/api/finance/history").json()["snapshots"] == [
        dict(corrected, change_krw=None, change_pct=None)
    ]


@pytest.mark.parametrize("month", ["2026-09-02", "2026-10-01", "2027-01-01"])
def test_snapshot_requires_completed_canonical_month(portfolio_api, month):
    client, _, _ = import_sheet(portfolio_api)
    assert client.post("/api/finance/history", json={"month": month}).status_code == 422


def test_settings_validate_id_and_changing_sheet_resets_trust(portfolio_api):
    client, _, _ = import_sheet(portfolio_api)
    assert client.post("/api/finance/verify").status_code == 200
    assert client.put("/api/finance/settings", json={"spreadsheet_id": "https://secret/url"}).status_code == 422
    changed = client.put("/api/finance/settings", json={"spreadsheet_id": "different-private-sheet"}).json()
    assert changed["verified_at"] is None and changed["last_success_at"] is None
    assert client.get("/api/finance/portfolio").json()["synced_at"] is None


def test_saved_legacy_import_does_not_block_local_writes(portfolio_api):
    client, _ = portfolio_api
    response = client.post("/api/data/holdings", json={"symbol": "OTHER", "quantity": "1"})
    assert response.status_code == 201


def test_history_period_validation_and_missing_month_indicators(portfolio_api):
    client, _, _ = import_sheet(portfolio_api)
    client.post("/api/finance/history", json={"month": "2026-09-01"})
    history = client.get("/api/finance/history?period=6m").json()
    assert len(history["snapshots"]) == 1
    assert "2026-08-01" in history["missing_months"]
    assert "2026-09-01" not in history["missing_months"]
    assert client.get("/api/finance/history?period=invalid").status_code == 422


def test_monthly_changes_compare_adjacent_observed_values(portfolio_api):
    client, fake = portfolio_api
    fake.data["History"].append({
        "month": "2026-08", "kind": "cash", "id": "bank", "label": "Cash", "currency": "KRW",
        "balance": "1000000", "as_of": "2026-08-31",
    })
    fake.data["Coverage"].append({
        "month": "2026-08", "cash": "true", "holding": "true", "liability": "true", "other": "true",
    })
    client.post("/api/finance/sync")
    for month in ("2026-08-01", "2026-09-01"):
        assert client.post("/api/finance/history", json={"month": month}).status_code == 201
    snapshots = client.get("/api/finance/history").json()["snapshots"]
    assert snapshots[0]["change_krw"] is None
    assert snapshots[1]["change_krw"] == "337500.00"
    assert snapshots[1]["change_pct"] == "33.75"


def test_gap_in_history_does_not_report_multimonth_change_as_monthly(portfolio_api):
    client, fake = portfolio_api
    fake.data["History"].append({
        "month": "2026-07", "kind": "cash", "id": "bank", "label": "Cash", "currency": "KRW",
        "balance": "1000000", "as_of": "2026-07-31",
    })
    fake.data["Coverage"].append({
        "month": "2026-07", "cash": "true", "holding": "true", "liability": "true", "other": "true",
    })
    client.post("/api/finance/sync")
    for month in ("2026-07-01", "2026-09-01"):
        client.post("/api/finance/history", json={"month": month})
    data = client.get("/api/finance/history").json()
    assert "2026-08-01" in data["missing_months"]
    assert data["snapshots"][-1]["change_krw"] is None
    assert data["snapshots"][-1]["change_pct"] is None


def test_unsupported_ticker_works_with_manual_price(portfolio_api):
    client, fake = portfolio_api
    fake.data["Holdings"][0]["ticker"] = "UNSUPPORTED:PRIVATE"
    data = client.post("/api/finance/sync").json()
    assert data["complete"] is True
    assert next(row for row in data["lines"] if row["kind"] == "holding")["value_krw"] is not None
    assert client.get("/api/finance/settings").json()["verified_at"] is None


def test_old_quote_sets_stale_warning_and_prevents_complete_total(portfolio_api):
    client, fake = portfolio_api
    fake.data["Holdings"][0]["price_as_of"] = "2026-09-01"
    data = client.post("/api/finance/sync").json()
    assert data["stale"] is True
    assert data["complete"] is False and data["net_worth"] is None


def test_close_requires_attestation_that_no_later_close_is_missing(portfolio_api):
    client, fake = portfolio_api
    for row in fake.data["Closes"]:
        row.pop("valid_through", None)
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    assert snap["complete"] is False and snap["net_worth"] is None


def test_correction_validation_rejects_nonfinite_financial_values(portfolio_api):
    client, _, _ = import_sheet(portfolio_api)
    first = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    body = {"reason": "Correct cash balance", "coverage": ["cash", "holding", "liability", "other"],
            "rows": [{"kind": "cash", "id": "bank", "label": "Cash", "currency": "KRW",
                      "as_of": "2026-09-30", "balance": "NaN"}]}
    assert client.post(f"/api/finance/history/{first['id']}/corrections", json=body).status_code == 422
    assert len(client.get(f"/api/finance/history/{first['id']}/audit").json()) == 1


def test_formula_read_detects_googlefinance_even_if_source_claims_manual():
    client = sheets_client()
    values = [[] for _ in TABS]
    formulas = [[] for _ in TABS]
    index = TABS.index("Holdings")
    values[index] = [["id", "price", "source"], ["goog", 185.125, "manual"]]
    formulas[index] = [["id", "price", "source"], ["goog", QUOTE_FORMULA, "manual"]]
    client.read = MagicMock(side_effect=[values, formulas])
    assert client.tables("private-sheet")["Holdings"][0]["source"] == "googlefinance"


def test_formula_wrapped_error_zero_is_missing_not_a_free_holding():
    client = sheets_client()
    values = [[] for _ in TABS]
    formulas = [[] for _ in TABS]
    index = TABS.index("Holdings")
    values[index] = [["id", "price", "source"], ["unsupported", 0, "manual"]]
    formulas[index] = [["id", "price", "source"], ["unsupported", '=IFERROR(GOOGLEFINANCE("INVALID","price"),0)', "manual"]]
    client.read = MagicMock(side_effect=[values, formulas])
    row = client.tables("private-sheet")["Holdings"][0]
    assert row["source"] == "googlefinance" and row["price"] == ""


@pytest.mark.parametrize("tab", ["Closes", "History"])
def test_historical_formula_rows_are_rejected_even_when_cached_values_are_numeric(tab):
    client = sheets_client()
    values = [[] for _ in TABS]
    formulas = [[] for _ in TABS]
    index = TABS.index(tab)
    values[index] = [["id", "price"], ["goog", 125]]
    formulas[index] = [["id", "price"], ["goog", '=INDEX(GOOGLEFINANCE("NASDAQ:GOOG","close",DATE(2026,9,30)),2,2)']]
    client.read = MagicMock(side_effect=[values, formulas])
    with pytest.raises(ValueError, match="literal"):
        client.tables("private-sheet")


def test_last_valid_close_skips_unavailable_later_row(portfolio_api):
    client, fake = portfolio_api
    fake.data["Closes"][1]["price"] = "#N/A"
    client.post("/api/finance/sync")
    snap = client.post("/api/finance/history", json={"month": "2026-09-01"}).json()
    holding = next(row for row in snap["lines"] if row["kind"] == "holding")
    assert holding["price"] == "120"
    assert holding["price_as_of"] == "2026-09-29"
    assert snap["net_worth"] == "1320000.00"


@pytest.mark.parametrize("share_financial", [False, True])
def test_advisor_stock_proportion_respects_financial_privacy(portfolio_api, session, share_financial, monkeypatch):
    from app.enums.context_category import Category
    from app.modules.context.portfolio_tools import sheets_portfolio
    from app.modules.context.types import ToolContext

    from app.modules.context import portfolio_tools
    from app.modules.portfolio import portfolio_manager
    monkeypatch.setattr(portfolio_tools, "_portfolio", lambda ctx: portfolio_manager.imported_portfolio_preview(ctx.session))
    client, fake = portfolio_api
    fake.data["Holdings"][0]["asset_class"] = "equity"
    assert client.post("/api/finance/sync").status_code == 200
    allowed = {Category.INVESTMENT}
    if share_financial:
        allowed.add(Category.FINANCIAL)
    result = sheets_portfolio(ToolContext(session=session, now=datetime.now(UTC), allowed=frozenset(allowed)))
    proportion = result.data["computed"]["stock_share_of_assets_pct"]
    assert result.data["computed"]["total_value_base"] is not None
    if share_financial:
        assert proportion is not None and Decimal(proportion) > 0
    else:
        assert proportion is None
        assert "total_assets" not in result.data["computed"]


@pytest.mark.parametrize("allowed_names", [["financial"], ["investment"], []])
def test_advisor_history_withholds_aggregate_if_either_category_excluded(portfolio_api, session, allowed_names):
    from app.enums.context_category import Category
    from app.modules.context.portfolio_tools import get_monthly_asset_history
    from app.modules.context.types import ToolContext

    client, _, _ = import_sheet(portfolio_api)
    client.post("/api/finance/history", json={"month": "2026-09-01"})
    allowed = frozenset(Category(name) for name in allowed_names)
    result = get_monthly_asset_history(ToolContext(session=session, now=datetime.now(UTC), allowed=allowed))
    assert result.data == {"snapshots": [], "withheld": True}
    assert result.refs == []
