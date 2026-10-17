"""Typed user input for the Sheets-authoritative holdings editor."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HoldingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]+$")
    position_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    request_id: str | None = Field(default=None, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    ticker: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9][A-Z0-9.:-]*$")
    label: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quantity: Decimal
    avg_cost: Decimal | None = None
    asset_class: Literal["equity", "etf", "bond", "crypto", "other"] = "equity"
    quote_mode: Literal["auto", "manual"] = "auto"
    manual_price: Decimal | None = None
    price_as_of: date | None = None

    @field_validator("quantity", "avg_cost", "manual_price")
    @classmethod
    def valid_amount(cls, value):
        if value is not None and (not value.is_finite() or value < 0 or value >= Decimal("1e20") or value.as_tuple().exponent < -12):
            raise ValueError("Amounts must be finite, nonnegative, below 1e20 with at most 12 decimals")
        return value

    @model_validator(mode="after")
    def valid_quote(self):
        if self.quote_mode == "auto" and ":" not in self.ticker:
            raise ValueError("Automatic quotes require an exchange-qualified ticker, e.g. NASDAQ:AAPL")
        if self.quote_mode == "manual" and (self.manual_price is None or self.price_as_of is None):
            raise ValueError("Manual quotes require a price and its actual date")
        if self.price_as_of and self.price_as_of > date.today():
            raise ValueError("Price date cannot be in the future")
        return self
