"""Read contracts for the unified, recorded-only household ledger."""
from datetime import date
from typing import Literal

from pydantic import BaseModel


class CashflowRow(BaseModel):
    source: Literal["cashflow_entries", "financial_transactions"]
    id: int
    occurred_on: date
    kind: str
    original_kind: str
    amount: str | None
    quantity: str | None = None
    currency: str | None
    category: str
    description: str | None
    is_reversed: bool


class CashflowSummary(BaseModel):
    income: str | None
    expense: str | None
    net: str | None
    record_count: int
    foreign_count: int


class CashflowMonth(CashflowSummary):
    month: str


class CashflowCategory(BaseModel):
    category: str
    amount: str
    share: str


class CashflowResponse(BaseModel):
    scope: Literal["household", "all"] = "household"
    month: str
    currency: str
    items: list[CashflowRow]
    total: int
    page: int
    page_size: int
    summary: CashflowSummary
    categories: list[CashflowCategory]
    trend: list[CashflowMonth]
    data_quality_flags: list[str]
