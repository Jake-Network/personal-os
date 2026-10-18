from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AdvisorMessage


class MessageHandler(BaseCRUDHandler[AdvisorMessage]):
    def __init__(self):
        super().__init__(AdvisorMessage)

    def get_replayable_before(self, session: Session, conversation_id: int,
                              before_id: int | None) -> list[AdvisorMessage]:
        """Every message a later turn could have replayed, oldest first (failed/incomplete turns never are)."""
        filters = [AdvisorMessage.conversation_id == conversation_id, AdvisorMessage.status == "complete"]
        if before_id is not None:
            filters.append(AdvisorMessage.id < before_id)
        return self.get_multiple_with_filters(session, filters, [AdvisorMessage.id])

    def get_by_conversation(self, session: Session, conversation_id: int) -> list[AdvisorMessage]:
        return self.get_multiple_with_filters(session, [AdvisorMessage.conversation_id == conversation_id],
                                              [AdvisorMessage.id])

    def search(self, session: Session, query: str, limit: int = 50) -> list[AdvisorMessage]:
        return self.get_multiple_with_filters(session, [AdvisorMessage.content.contains(query)],
                                              [AdvisorMessage.id.desc()], limit)


message_handler = MessageHandler()
