"""Whole-share input policy preserves pre-existing fractional evidence on reads."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.modules.database.model import Holding, PortfolioImport
from app.modules.finance.formatting import quantity_text
from app.modules.portfolio import holdings_manager, local_portfolio, market_data_manager
from app.schema.domain_schema import HoldingItem
from app.schema.holdings_schema import HoldingInput
from app.schema.market_data_schema import CsvImportInput
from app.schema.portfolio_schema import HistoricalRow


@pytest.mark.parametrize("quantity", ["1.5", 0.25, "-1", "NaN", "100000000000000000000"])
def test_holding_and_transaction_endpoints_reject_invalid_share_counts(client, quantity):
    local = {"position_id": "whole-shares", "ticker": "NASDAQ:AAPL", "label": "Synthetic",
             "currency": "USD", "quantity": quantity}
    assert client.post("/api/finance/holdings", json=local).status_code == 422
    assert client.post("/api/data/holdings", json={"symbol": "AAPL", "quantity": quantity}).status_code == 422
    transaction = {"request_id": "whole-trade", "kind": "buy", "holding_id": 1,
                   "occurred_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                   "quantity": quantity, "amount": "100", "source": "synthetic"}
    assert client.post("/api/finance/transactions", json=transaction).status_code == 422


def test_updates_reject_fractional_quantity_and_reads_omit_trailing_zeros(client):
    body = {"symbol": "AAPL", "quantity": 12, "currency": "USD"}
    response = client.post("/api/data/holdings", json=body)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["quantity"] == "12"
    assert client.put(f"/api/data/holdings/{item['id']}", json={**body, "quantity": "12.5"}).status_code == 422
    assert client.get("/api/data/holdings").json()[0]["quantity"] == "12"


@pytest.mark.parametrize("quantity", ["2.5", "-1", "100000000000000000000"])
def test_import_preview_rejects_invalid_share_counts_without_creating_holdings(session, quantity):
    body = CsvImportInput(source_id="whole-import", csv_text=(
        "kind,id,label,currency,ticker,quantity\n"
        f"holding,a,Synthetic,USD,NASDAQ:AAPL,{quantity}\n"
    ))
    preview = market_data_manager.csv_preview(session, body)
    assert preview["rows"][0]["issues"]
    with pytest.raises(ValueError, match="preview issues"):
        market_data_manager.csv_import(session, body)
    assert session.scalar(select(func.count()).select_from(Holding)) == 0
    assert session.scalar(select(func.count()).select_from(PortfolioImport)) == 0


def test_existing_fractional_records_are_read_without_truncation(session, client):
    session.add(Holding(symbol="LEGACY", currency="USD", quantity=Decimal("1.125")))
    session.commit()
    assert client.get("/api/data/holdings").json()[0]["quantity"] == "1.125"
    assert holdings_manager.listing(session)["rows"][0]["quantity"] == "1.125"
    assert local_portfolio.rows(session)[0]["quantity"] == "1.125"


def test_local_holding_listing_and_portfolio_omit_storage_scale(session):
    session.add(Holding(symbol="WHOLE", currency="USD", quantity=12))
    session.commit()
    assert holdings_manager.listing(session)["rows"][0]["quantity"] == "12"
    assert local_portfolio.rows(session)[0]["quantity"] == "12"


def test_legacy_quantity_serialization_preserves_all_thirty_two_digits():
    quantity = "12345678901234567890.123456789123"
    item = HoldingItem(id=1, symbol="LEGACY", currency="USD", quantity=quantity)
    assert item.model_dump(mode="json")["quantity"] == quantity


def test_new_historical_evidence_requires_whole_share_quantity():
    with pytest.raises(ValidationError):
        HistoricalRow(kind="holding", id="new-evidence", label="Synthetic", currency="USD",
                      as_of="2026-01-01", quantity="1.125")


def test_freshly_saved_large_integer_quantity_is_not_converted_to_float(session):
    quantity = 9007199254740993
    assert quantity_text(quantity) == str(quantity)
    body = HoldingInput(position_id="large-count", ticker="NASDAQ:AAPL", label="Synthetic",
                        currency="USD", quantity=quantity)
    assert holdings_manager.save(session, body)["rows"][0]["quantity"] == str(quantity)
