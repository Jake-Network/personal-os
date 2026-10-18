from datetime import date

from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import CashflowEntry


class CashflowEntryHandler(BaseCRUDHandler[CashflowEntry]):
    def __init__(self):
        super().__init__(CashflowEntry)

    def get_since(self, session: Session, since: date) -> list[CashflowEntry]:
        return self.get_multiple_with_filters(session, [CashflowEntry.occurred_on >= since],
                                              [CashflowEntry.occurred_on])


cashflow_entry_handler = CashflowEntryHandler()
