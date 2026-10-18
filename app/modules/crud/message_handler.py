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
        from sqlalchemy import select
        from sqlalchemy.orm import defer
        return list(session.scalars(select(AdvisorMessage).options(defer(AdvisorMessage.content)).where(*filters).order_by(AdvisorMessage.id)))

    def get_by_conversation(self, session: Session, conversation_id: int) -> list[AdvisorMessage]:
        return self.get_multiple_with_filters(session, [AdvisorMessage.conversation_id == conversation_id],
                                              [AdvisorMessage.id])

    def search(self, session: Session, query: str, limit: int = 50, offset: int = 0,
               since=None, until=None, conversation_id=None) -> list[AdvisorMessage]:
        from sqlalchemy import select
        statement = select(AdvisorMessage).where(AdvisorMessage.content.icontains(query, autoescape=True))
        if since:
            statement = statement.where(AdvisorMessage.created_at >= since)
        if until:
            statement = statement.where(AdvisorMessage.created_at < until)
        if conversation_id is not None:
            statement = statement.where(AdvisorMessage.conversation_id == conversation_id)
        return list(session.scalars(statement.order_by(AdvisorMessage.id.desc()).offset(offset).limit(limit)))

    def page(self, session, conversation_id, limit=100, before_id=None):
        from sqlalchemy import select
        statement = select(AdvisorMessage).where(AdvisorMessage.conversation_id == conversation_id)
        if before_id is not None:
            statement = statement.where(AdvisorMessage.id < before_id)
        return list(reversed(list(session.scalars(statement.order_by(AdvisorMessage.id.desc()).limit(limit)))))


message_handler = MessageHandler()
