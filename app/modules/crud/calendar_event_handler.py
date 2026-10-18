from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import CalendarEvent


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


calendar_event_handler = CalendarEventHandler()
