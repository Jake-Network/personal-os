from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ColumnName = Field(min_length=1, max_length=120)


class CashflowColumnMapping(BaseModel):
    """CSV header names for each ledger field. Either `amount` or at least one of `debit`/`credit`."""

    model_config = ConfigDict(extra="forbid")
    date: str = ColumnName
    amount: str | None = Field(None, min_length=1, max_length=120)
    debit: str | None = Field(None, min_length=1, max_length=120)  # money out: expense
    credit: str | None = Field(None, min_length=1, max_length=120)  # money in: income
    description: str | None = Field(None, min_length=1, max_length=120)
    category: str | None = Field(None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _one_amount_shape(self):
        if (self.amount is None) == (self.debit is None and self.credit is None):
            raise ValueError("map either one amount column or debit/credit columns")
        return self


class CashflowImportFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: CashflowColumnMapping
    # For a single amount column: which sign means money out.
    amount_sign: Literal["negative_is_expense", "positive_is_expense"] = "negative_is_expense"
    skip_rows: int = Field(0, ge=0, le=50)  # lines before the header (bank export preambles)


class CashflowImportInput(CashflowImportFormat):
    source_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    csv_text: str = Field(min_length=1, max_length=2_000_000)
    exclude_rows: list[int] = Field(default_factory=list, max_length=10_000)
    category_overrides: dict[int, str] = Field(default_factory=dict)
    # Descriptions whose override should become an `equals` rule, by row number.
    remember_rows: list[int] = Field(default_factory=list, max_length=10_000)


class CashflowImportRow(BaseModel):
    row: int  # 1-based line number in the uploaded text
    occurred_on: date | None
    kind: Literal["income", "expense"] | None
    amount: Decimal | None
    currency: str
    description: str | None
    category: str | None
    category_source: Literal["override", "csv", "rule"] | None
    status: Literal["new", "existing", "deleted", "excluded"]
    possible_duplicate: bool
    issues: list[str]


class CashflowImportCoverage(BaseModel):
    first_date: date | None
    last_date: date | None
    # Months the file covers only partly: their totals are not a complete month.
    partial_months: list[str]


class CashflowImportPreview(BaseModel):
    rows: list[CashflowImportRow]
    coverage: CashflowImportCoverage
    counts: dict[str, int]


class CashflowImportResult(BaseModel):
    imported: int
    existing: int
    deleted: int
    excluded: int
    rules_created: int
    coverage: CashflowImportCoverage


class CashflowImportPreset(CashflowImportFormat):
    name: str = Field(min_length=1, max_length=60)


class CashflowImportPresets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presets: list[CashflowImportPreset] = Field(default_factory=list, max_length=30)


class CashflowCategoryRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_text: str = Field(min_length=1, max_length=200)
    match_kind: Literal["equals", "contains"] = "equals"
    category: str = Field(min_length=1, max_length=64)


class CashflowCategoryRuleItem(CashflowCategoryRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class RecurringCashflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    category: str | None = Field(None, max_length=64)
    day_of_month: int = Field(ge=1, le=31)
    start_on: date
    end_on: date | None = None
    active: bool = True

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_on is not None and self.end_on < self.start_on:
            raise ValueError("end_on must not precede start_on")
        return self


class RecurringCashflowItem(RecurringCashflowCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    currency: str


class RecurringDueItem(BaseModel):
    recurring_id: int
    name: str
    kind: Literal["income", "expense"]
    amount: Decimal
    currency: str
    category: str | None
    month: str
    scheduled_on: date
    recorded: bool
    entry_id: int | None


class RecurringRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class BalanceCheckInItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int
    expected_version: datetime
    # None confirms that the stored balance is still right as of today.
    balance: Decimal | None = Field(None, max_digits=20, decimal_places=4)


class BalanceCheckInInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[BalanceCheckInItem] = Field(min_length=1, max_length=100)


class BalanceCheckInResult(BaseModel):
    account_id: int
    status: Literal["updated", "confirmed", "conflict", "not_found"]
    message: str
