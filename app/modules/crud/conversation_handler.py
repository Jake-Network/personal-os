from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AdvisorConversation


class ConversationHandler(BaseCRUDHandler[AdvisorConversation]):
    """PRD ConversationRepository."""

    def __init__(self):
        super().__init__(AdvisorConversation)

    def get_recent(self, session: Session, query: str | None = None, limit: int = 50) -> list[AdvisorConversation]:
        filters = [AdvisorConversation.title.contains(query)] if query else []
        return self.get_multiple_with_filters(session, filters, [AdvisorConversation.updated_at.desc()], limit)


conversation_handler = ConversationHandler()
