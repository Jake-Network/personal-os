from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import DecisionJournalEntry


class DecisionJournalHandler(BaseCRUDHandler[DecisionJournalEntry]):
    def __init__(self):
        super().__init__(DecisionJournalEntry)

    def get_all(self, session: Session) -> list[DecisionJournalEntry]:
        return self.get_multiple_with_filters(session, order_by=[DecisionJournalEntry.decided_at.desc()])


decision_journal_handler = DecisionJournalHandler()
