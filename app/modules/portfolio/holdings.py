"""The edit-form view of a Sheets holding row."""
from app.modules.portfolio.sheets import holding_version


def editable_row(row):
    return dict(row, position_id=row.get("id"), expected_version=holding_version(row),
                quote_mode="auto" if row.get("source") == "googlefinance" else "manual",
                manual_price=row.get("price") if row.get("source") != "googlefinance" else None)
