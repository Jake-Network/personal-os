"""Privacy over replayed conversation history: loads snapshot categories, then applies `decide_history`."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.context.history_privacy import decide_history
from app.modules.context.types import HistoryDecision
from app.modules.crud import context_snapshot_handler
from app.modules.database.model import AdvisorMessage


class HistoryPrivacyManager:
    def filter(self, session: Session, messages: Sequence[AdvisorMessage],
               excluded: frozenset[Category]) -> HistoryDecision:
        ids = {m.context_snapshot_id for m in messages if m.context_snapshot_id}
        categories = {
            s.id: frozenset(Category(c) for c in [*s.context_categories, *s.payload.get("document_categories", [])]
                            if c in Category._value2member_map_)
            for s in context_snapshot_handler.get_many(session, ids)
        }
        return decide_history(messages, categories, excluded)


history_privacy_manager = HistoryPrivacyManager()
