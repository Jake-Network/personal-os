from datetime import date, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import CalendarEvent, Goal, Task, WorkoutLog


class CalendarEventHandler(BaseCRUDHandler[CalendarEvent]):
    def __init__(self):
        super().__init__(CalendarEvent)

    def get_between(self, session: Session, start: datetime, end: datetime) -> list[CalendarEvent]:
        # Half-open intervals also include events already in progress at start.
        return self.get_multiple_with_filters(
            session,
            [CalendarEvent.starts_at < end,
             or_(CalendarEvent.ends_at > start, CalendarEvent.starts_at >= start)],
            [CalendarEvent.starts_at, CalendarEvent.id],
        )


class TaskHandler(BaseCRUDHandler[Task]):
    def __init__(self):
        super().__init__(Task)

    def get_open(self, session: Session, limit: int = 50) -> list[Task]:
        return self.get_multiple_with_filters(
            session, [Task.status != "done"], [Task.due_on.is_(None), Task.due_on, Task.id], limit=limit
        )


class GoalHandler(BaseCRUDHandler[Goal]):
    def __init__(self):
        super().__init__(Goal)

    def get_active(self, session: Session) -> list[Goal]:
        return self.get_multiple_with_filters(session, [Goal.status == "active"], [Goal.id])


class WorkoutLogHandler(BaseCRUDHandler[WorkoutLog]):
    def __init__(self):
        super().__init__(WorkoutLog)

    def get_since(self, session: Session, since: date) -> list[WorkoutLog]:
        return self.get_multiple_with_filters(session, [WorkoutLog.performed_on >= since], [WorkoutLog.performed_on])


calendar_event_handler = CalendarEventHandler()
task_handler = TaskHandler()
goal_handler = GoalHandler()
workout_log_handler = WorkoutLogHandler()
