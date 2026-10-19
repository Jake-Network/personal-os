"""Values computed from rows the context tools already read: FX table, calendar conflicts, cash runway."""

from collections.abc import Iterable
from decimal import Decimal

from app.modules.database.model import CalendarEvent, FxRate
from app.modules.finance.financial_calculator import financial_calculator
from app.modules.finance.types import FxTable


def fx_table_from_rates(base: str, rates: Iterable[FxRate]) -> tuple[FxTable, list[FxRate]]:
    """Newest rate per currency into `base`, using the inverse when only base→currency is stored."""
    table = FxTable(base=base)
    used: list[FxRate] = []
    for rate in rates:
        if rate.quote == base and rate.base not in table.rates:
            table.rates[rate.base] = rate.rate
            used.append(rate)
        elif rate.base == base and rate.quote not in table.rates and rate.rate:
            table.rates[rate.quote] = Decimal(1) / rate.rate
            used.append(rate)
    return table, used


def calendar_conflicts(events: list[CalendarEvent]) -> list[dict]:
    """Overlapping timed pairs among events sorted by start; all-day entries do not reserve time."""
    events = [event for event in events if not event.all_day]
    out = []
    for i, a in enumerate(events):
        a_end = a.ends_at or a.starts_at
        for b in events[i + 1:]:
            if b.starts_at >= a_end:
                break
            out.append({"a": f"calendar_events:{a.id}", "b": f"calendar_events:{b.id}"})
    return out


def derive_cash_runway(data: dict) -> dict | None:
    """Runway from the accounts and cashflow sections; None unless both were collected."""
    accounts, cashflow = data.get("get_accounts_summary"), data.get("get_cashflow_summary")
    if accounts is None or cashflow is None:
        return None
    worth = accounts.get("computed", {}).get("net_worth")
    return {**financial_calculator.cash_runway(worth, cashflow.get("monthly_expense")),
            "computed_by": "FinancialCalculator"}
