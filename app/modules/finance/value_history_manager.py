"""Append-only history for manual financial edits (balances, holding quantities, average cost).

The manual-entry workflow is unchanged: the user still edits `accounts` and `holdings` directly.
Each create/update/delete also appends a ManualValueChange row in the same transaction, with an
explicit as-of date: the account's `balance_as_of`, or for holdings the trade date entered with the
edit (`trade_date`, kept only in the history) and otherwise the date the edit was recorded. A record edited for the first time without any history (created
before this table existed) first gets a `baseline` row holding the value being replaced.
"""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.modules.crud import manual_value_change_handler
from app.modules.database.model import ManualValueChange
from app.modules.finance.value_history import TRACKED, capture, history_row

class ValueHistoryManager:
    def record(self, session: Session, resource: str, obj, before: dict | None, verb: str,
               today: date | None = None, trade_date: date | None = None) -> list[ManualValueChange]:
        """Append one row per tracked field that changed. `before` is None on create."""
        table, as_of_attr, fields = TRACKED[resource]
        today = today or datetime.now(UTC).date()
        after = None if verb == "delete" else capture(resource, obj)
        if after is not None and trade_date is not None:
            after["as_of"] = trade_date
        rows = []
        for field in fields:
            old = before[field] if before else None
            new = after[field] if after else None
            new_as_of = (after or {}).get("as_of") or today
            old_as_of = (before or {}).get("as_of") or today
            # An unchanged value is only worth a row when it is re-confirmed at a new as-of date of the
            # record itself (an account balance); a holding's trade date alone changes nothing.
            if verb == "update" and old == new and (old is None or as_of_attr is None or old_as_of == new_as_of):
                continue
            if verb == "create" and new is None:
                continue
            if verb != "create" and old is not None and not self._has_history(session, table, obj.id, field):
                rows.append(history_row(table, obj.id, field, None, old, obj.currency, old_as_of, "baseline"))
            rows.append(history_row(table, obj.id, field, old, new, obj.currency,
                                  today if verb == "delete" else new_as_of, verb))
        return [manual_value_change_handler.create(session, row) for row in rows]

    @staticmethod
    def list(session: Session, resource: str, record_id: int) -> list[ManualValueChange]:
        table, _, _ = TRACKED[resource]
        return manual_value_change_handler.get_for_record(session, table, record_id)

    @staticmethod
    def _has_history(session: Session, table: str, record_id: int, field: str) -> bool:
        return bool(manual_value_change_handler.get_for_record(session, table, record_id, field, limit=1))

value_history_manager = ValueHistoryManager()
