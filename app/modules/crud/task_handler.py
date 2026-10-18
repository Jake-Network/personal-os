from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Task


class TaskHandler(BaseCRUDHandler[Task]):
    def __init__(self):
        super().__init__(Task)

    def get_open(self, session: Session, limit: int = 50) -> list[Task]:
        return self.get_multiple_with_filters(
            session, [Task.status != "done"], [Task.due_on.is_(None), Task.due_on, Task.id], limit=limit
        )


task_handler = TaskHandler()
