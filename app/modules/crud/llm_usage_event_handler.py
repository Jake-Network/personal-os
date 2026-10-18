from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import LLMUsageEvent


class LLMUsageEventHandler(BaseCRUDHandler[LLMUsageEvent]):
    def __init__(self):
        super().__init__(LLMUsageEvent)

    def get_recent(self, session: Session, limit: int = 50) -> list[LLMUsageEvent]:
        return self.get_multiple_with_filters(session, order_by=[LLMUsageEvent.id.desc()], limit=limit)


llm_usage_event_handler = LLMUsageEventHandler()
