from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import (
    AdvisorConversation,
    AdvisorMessage,
    AdvisorRecommendation,
    ContextSnapshot,
    DecisionJournalEntry,
    LLMUsageEvent,
    PersonalMemory,
    ProposedAction,
)


class ConversationHandler(BaseCRUDHandler[AdvisorConversation]):
    """PRD ConversationRepository."""

    def __init__(self):
        super().__init__(AdvisorConversation)

    def get_recent(self, session: Session, query: str | None = None, limit: int = 50) -> list[AdvisorConversation]:
        filters = [AdvisorConversation.title.contains(query)] if query else []
        return self.get_multiple_with_filters(session, filters, [AdvisorConversation.updated_at.desc()], limit)


class MessageHandler(BaseCRUDHandler[AdvisorMessage]):
    def __init__(self):
        super().__init__(AdvisorMessage)

    def get_history(self, session: Session, conversation_id: int, before_id: int | None, limit: int) -> list[AdvisorMessage]:
        filters = [AdvisorMessage.conversation_id == conversation_id, AdvisorMessage.status == "complete"]
        if before_id is not None:
            filters.append(AdvisorMessage.id < before_id)
        rows = self.get_multiple_with_filters(
            session,
            filters,
            [AdvisorMessage.id.desc()],
            limit,
        )
        return list(reversed(rows))

    def get_by_conversation(self, session: Session, conversation_id: int) -> list[AdvisorMessage]:
        return self.get_multiple_with_filters(session, [AdvisorMessage.conversation_id == conversation_id],
                                              [AdvisorMessage.id])

    def search(self, session: Session, query: str, limit: int = 50) -> list[AdvisorMessage]:
        return self.get_multiple_with_filters(session, [AdvisorMessage.content.contains(query)],
                                              [AdvisorMessage.id.desc()], limit)


class ContextSnapshotHandler(BaseCRUDHandler[ContextSnapshot]):
    def __init__(self):
        super().__init__(ContextSnapshot)

    def create(self, session, obj_in):
        from app.modules.documents.evidence import record_references
        snapshot = super().create(session, obj_in)
        record_references(session, snapshot)
        return snapshot

    def delete(self, session, obj):
        session.execute(update(AdvisorMessage).where(AdvisorMessage.context_snapshot_id == obj.id)
                        .values(context_purged=True))
        super().delete(session, obj)

    def get_latest_for_conversation(self, session: Session, conversation_id: int) -> ContextSnapshot | None:
        return self.get_first_with_filters(session, [ContextSnapshot.conversation_id == conversation_id],
                                           [ContextSnapshot.generated_at.desc()])


    def delete_for_conversation(self, session: Session, conversation_id: int) -> None:
        for snap in self.get_multiple_with_filters(session, [ContextSnapshot.conversation_id == conversation_id]):
            session.delete(snap)
        session.flush()


class RecommendationHandler(BaseCRUDHandler[AdvisorRecommendation]):
    def __init__(self):
        super().__init__(AdvisorRecommendation)


class ProposedActionHandler(BaseCRUDHandler[ProposedAction]):
    def __init__(self):
        super().__init__(ProposedAction)

    def get_by_status(self, session: Session, status: str) -> list[ProposedAction]:
        return self.get_multiple_with_filters(session, [ProposedAction.status == status], [ProposedAction.id])


class PersonalMemoryHandler(BaseCRUDHandler[PersonalMemory]):
    def __init__(self):
        super().__init__(PersonalMemory)

    def get_by_status(self, session: Session, status: str) -> list[PersonalMemory]:
        return self.get_multiple_with_filters(session, [PersonalMemory.status == status], [PersonalMemory.id])


class DecisionJournalHandler(BaseCRUDHandler[DecisionJournalEntry]):
    def __init__(self):
        super().__init__(DecisionJournalEntry)

    def get_all(self, session: Session) -> list[DecisionJournalEntry]:
        return self.get_multiple_with_filters(session, order_by=[DecisionJournalEntry.decided_at.desc()])


class LLMUsageEventHandler(BaseCRUDHandler[LLMUsageEvent]):
    def __init__(self):
        super().__init__(LLMUsageEvent)

    def get_recent(self, session: Session, limit: int = 50) -> list[LLMUsageEvent]:
        return self.get_multiple_with_filters(session, order_by=[LLMUsageEvent.id.desc()], limit=limit)


conversation_handler = ConversationHandler()
message_handler = MessageHandler()
context_snapshot_handler = ContextSnapshotHandler()
recommendation_handler = RecommendationHandler()
proposed_action_handler = ProposedActionHandler()
personal_memory_handler = PersonalMemoryHandler()
decision_journal_handler = DecisionJournalHandler()
llm_usage_event_handler = LLMUsageEventHandler()
