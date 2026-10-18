from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AdvisorConversation


class ConversationHandler(BaseCRUDHandler[AdvisorConversation]):
    """PRD ConversationRepository."""

    def __init__(self):
        super().__init__(AdvisorConversation)

    def get_recent(self, session: Session, query: str | None = None, limit: int = 50,
                   offset: int = 0, since=None, until=None, domain=None, company=None, project=None, decision=None) -> list[AdvisorConversation]:
        from sqlalchemy import or_, select
        from app.modules.database.model import AdvisorMessage
        statement = select(AdvisorConversation)
        if query:
            statement = statement.where(or_(AdvisorConversation.title.icontains(query, autoescape=True),
                AdvisorConversation.id.in_(select(AdvisorMessage.conversation_id).where(AdvisorMessage.content.icontains(query, autoescape=True)))))
        if since:
            statement = statement.where(AdvisorConversation.created_at >= since)
        if until:
            statement = statement.where(AdvisorConversation.created_at < until)
        from app.modules.database.model import ConversationLink
        for kind, target in (("company", company), ("project", project), ("decision", decision)):
            if target is not None:
                statement = statement.where(AdvisorConversation.id.in_(select(ConversationLink.conversation_id).where(
                    ConversationLink.kind == kind, ConversationLink.target == str(target))))
        if domain:
            statement = statement.where(AdvisorConversation.domain == domain)
        return list(session.scalars(statement.order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc()).offset(offset).limit(limit)))


conversation_handler = ConversationHandler()
