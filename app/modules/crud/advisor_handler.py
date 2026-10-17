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


class ContextSnapshotHandler(BaseCRUDHandler[ContextSnapshot]):
    def __init__(self):
        super().__init__(ContextSnapshot)

    def get_latest_for_conversation(self, session: Session, conversation_id: int) -> ContextSnapshot | None:
        return self.get_first_with_filters(session, [ContextSnapshot.conversation_id == conversation_id],
                                           [ContextSnapshot.generated_at.desc()])

    def get_many(self, session: Session, ids: set[str]) -> list[ContextSnapshot]:
        return self.get_multiple_with_filters(session, [ContextSnapshot.id.in_(ids)]) if ids else []

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

    def transition(self, session: Session, proposal_id: int, from_status: str, to_status: str,
                   values: dict | None = None) -> bool:
        """Compare-and-set the status in one UPDATE; True only for the request that won."""
        result = session.execute(
            update(ProposedAction)
            .where(ProposedAction.id == proposal_id, ProposedAction.status == from_status)
            .values(status=to_status, **(values or {}))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            # Refresh the identity-map copy so the caller sees the new status.
            proposal = session.get(ProposedAction, proposal_id)
            if proposal is not None:
                session.refresh(proposal)
        return result.rowcount == 1


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
