from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import ManualValueChange


class ManualValueChangeHandler(BaseCRUDHandler[ManualValueChange]):
    """Insert and read only; the model rejects updates and deletes."""

    def __init__(self):
        super().__init__(ManualValueChange)

    def get_for_record(self, session: Session, table: str, record_id: int,
                       field: str | None = None, limit: int | None = None) -> list[ManualValueChange]:
        filters = [ManualValueChange.table_name == table, ManualValueChange.record_id == record_id]
        if field is not None:
            filters.append(ManualValueChange.field == field)
        return self.get_multiple_with_filters(session, filters, [ManualValueChange.id], limit)


manual_value_change_handler = ManualValueChangeHandler()
