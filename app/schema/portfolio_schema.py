from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SheetsSettingsInput(BaseModel):
    spreadsheet_id: str = Field(min_length=10, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")


class SnapshotInput(BaseModel):
    month: date


class HistoricalRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["cash", "holding", "liability", "other"]
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of: date
    balance: Decimal | None = None
    quantity: Decimal | None = None
    avg_cost: Decimal | None = None
    ticker: str | None = None
    asset_class: Literal["equity", "etf", "bond", "crypto", "other"] = "other"
    price: Decimal | None = None
    price_as_of: date | None = None
    close_valid_through: date | None = None
    source: str | None = None
    fx_rate: Decimal | None = None
    fx_as_of: date | None = None

    @field_validator("balance", "quantity", "avg_cost", "price", "fx_rate")
    @classmethod
    def finite(cls, value):
        if value is not None and (not value.is_finite() or value < 0 or value >= Decimal("1e20") or value.as_tuple().exponent < -12):
            raise ValueError("Amounts must be finite, nonnegative, below 1e20 and have at most 12 decimal places")
        return value


class SnapshotCorrection(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    rows: list[HistoricalRow] = Field(max_length=10000)
    coverage: list[Literal["cash", "holding", "liability", "other"]]

    @field_validator("reason", mode="before")
    @classmethod
    def meaningful_reason(cls, value):
        return value.strip() if isinstance(value, str) else value
