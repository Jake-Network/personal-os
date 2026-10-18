from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Goal


class GoalHandler(BaseCRUDHandler[Goal]):
    def __init__(self):
        super().__init__(Goal)

    def get_active(self, session: Session) -> list[Goal]:
        return self.get_multiple_with_filters(session, [Goal.status == "active"], [Goal.id])


goal_handler = GoalHandler()
