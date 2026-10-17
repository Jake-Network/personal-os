"""Opt-in real Sheets proof; mocks cannot establish GOOGLEFINANCE availability.

Use server-side ADC with spreadsheets.readonly access. Share the private test
sheet with that identity. Verification!A1 must be a current GOOGLEFINANCE ticker
price, B1 a current GOOGLEFINANCE CURRENCY:USDKRW formula. Never writes a sheet.
"""
import os
from decimal import Decimal

import pytest


@pytest.mark.skipif(
    os.environ.get("PERSONAL_OS_LIVE_SHEETS") != "1",
    reason="Real Google credentials and explicit live Sheets opt-in are required",
)
def test_real_current_googlefinance_price_and_fx_are_readable():
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_TEST_SPREADSHEET_ID")
    if not spreadsheet_id:
        pytest.skip("GOOGLE_SHEETS_TEST_SPREADSHEET_ID is required")
    pytest.importorskip("google.auth")
    pytest.importorskip("googleapiclient.discovery")
    from app.modules.portfolio.sheets import SheetsClient

    proof = SheetsClient().verify(spreadsheet_id)
    assert Decimal(proof["quote"]).is_finite() and Decimal(proof["quote"]) > 0
    assert Decimal(proof["fx"]).is_finite() and Decimal(proof["fx"]) > 0
    assert len(proof["formulas"]) == 2
