"""Which manual edits keep value history, and the shape of a history row."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

# resource name -> (table name, as-of attribute on the row, tracked fields)
TRACKED: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "accounts": ("accounts", "balance_as_of", ("balance",)),
    "liabilities": ("liabilities", "balance_as_of", ("balance",)),
    "other-assets": ("other_assets", "value_as_of", ("value",)),
    "holdings": ("holdings", None, ("quantity", "avg_cost")),
}
# Request fields that only date the history row and are not columns of the current-state table.
HISTORY_ONLY_FIELDS: dict[str, frozenset[str]] = {"holdings": frozenset({"trade_date"})}


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def tracks(resource: str) -> bool:
    return resource in TRACKED


def capture(resource: str, obj) -> dict:
    """Tracked values and as-of date of `obj` before an edit."""
    _, as_of, fields = TRACKED[resource]
    return {"as_of": getattr(obj, as_of) if as_of else None, **{f: _dec(getattr(obj, f)) for f in fields}}


def split_history_fields(name: str, body: BaseModel, exclude_unset: bool = False) -> tuple[dict, date | None]:
    """Row columns, and the history-only trade date that must not reach the table."""
    history_only = HISTORY_ONLY_FIELDS.get(name, frozenset())
    return (body.model_dump(exclude_unset=exclude_unset, exclude=set(history_only)),
            getattr(body, "trade_date", None) if history_only else None)


def history_row(table, record_id, field, old, new, currency, as_of, kind) -> dict:
    return {"table_name": table, "record_id": record_id, "field": field, "old_value": old, "new_value": new,
            "currency": currency, "as_of": as_of, "change_kind": kind}
