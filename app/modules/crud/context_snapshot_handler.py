from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AdvisorMessage, ContextSnapshot


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

    def get_many(self, session: Session, ids: set[str]) -> list[ContextSnapshot]:
        return self.get_multiple_with_filters(session, [ContextSnapshot.id.in_(ids)]) if ids else []

    def delete_for_conversation(self, session: Session, conversation_id: int) -> None:
        for snap in self.get_multiple_with_filters(session, [ContextSnapshot.conversation_id == conversation_id]):
            session.delete(snap)
        session.flush()


context_snapshot_handler = ContextSnapshotHandler()
