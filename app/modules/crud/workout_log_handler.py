from datetime import date

from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import WorkoutLog


class WorkoutLogHandler(BaseCRUDHandler[WorkoutLog]):
    def __init__(self):
        super().__init__(WorkoutLog)

    def get_since(self, session: Session, since: date) -> list[WorkoutLog]:
        return self.get_multiple_with_filters(session, [WorkoutLog.performed_on >= since], [WorkoutLog.performed_on])


workout_log_handler = WorkoutLogHandler()
