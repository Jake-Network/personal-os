from datetime import date

from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import PlannedExpense


class PlannedExpenseHandler(BaseCRUDHandler[PlannedExpense]):
    def __init__(self):
        super().__init__(PlannedExpense)

    def get_upcoming(self, session: Session, today: date) -> list[PlannedExpense]:
        return self.get_multiple_with_filters(session, [PlannedExpense.due_on >= today], [PlannedExpense.due_on])


planned_expense_handler = PlannedExpenseHandler()
