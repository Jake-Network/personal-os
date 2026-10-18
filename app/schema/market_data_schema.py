"""Local transaction ledger and evidence-backed month closes."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schema.portfolio_schema import HistoricalRow


class CoverageInput(BaseModel):
    kinds: list[Literal["cash", "holding", "liability", "other"]]


class QuotesReplacementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_spreadsheet_id: str = Field(min_length=1, max_length=200)
    expected_account_key: str = Field(pattern=r"^[a-f0-9]{64}$")


class TransactionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal[
        "income",
        "expense",
        "transfer",
        "buy",
        "sell",
        "dividend",
        "interest",
        "fee",
        "tax",
        "repayment",
        "split",
        "reversal",
    ]
    occurred_at: datetime
    account_id: int | None = Field(default=None, gt=0)
    counterparty_account_id: int | None = Field(default=None, gt=0)
    holding_id: int | None = Field(default=None, gt=0)
    amount: Decimal | None = Field(
        default=None, gt=0, lt=Decimal("1e20"), decimal_places=12
    )
    currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$")
    quantity: int | None = Field(default=None, gt=0, lt=10**20)
    reverses_id: int | None = Field(default=None, gt=0)
    source: str = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("occurred_at")
    @classmethod
    def timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Transaction time requires a timezone")
        if value > datetime.now(UTC):
            raise ValueError("Future transaction time is not allowed")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "reversal":
            if self.reverses_id is None:
                raise ValueError("Reversal requires its original transaction")
        elif self.reverses_id is not None:
            raise ValueError("Only a reversal can supersede a transaction")
        if self.kind == "transfer" and (
            not self.account_id
            or not self.counterparty_account_id
            or self.account_id == self.counterparty_account_id
        ):
            raise ValueError("Transfer requires two different local accounts")
        if self.kind in {"buy", "sell", "split"} and (
            not self.holding_id or self.quantity is None
        ):
            raise ValueError("Trade/split requires a holding and explicit quantity")
        if self.kind not in {"split", "reversal"} and self.amount is None:
            raise ValueError("Transaction amount is required")
        return self


class MonthCloseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: date
    reason: str = Field(min_length=3, max_length=2000)
    rows: list[HistoricalRow] = Field(max_length=10000)
    coverage: list[Literal["cash", "holding", "liability", "other"]]


class CsvImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    csv_text: str = Field(min_length=1, max_length=2_000_000)
