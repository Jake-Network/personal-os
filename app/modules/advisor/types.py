"""Types passed through one advisor turn."""

from dataclasses import dataclass, field

from app.enums.context_category import Category
from app.modules.context.types import HistoryDecision, payload_citations
from app.modules.database.model import AdvisorMessage, ContextSnapshot


@dataclass
class AskOptions:
    """Per-request overrides for routing and document search."""

    categories: frozenset[Category] | None = None  # Context Inspector override
    exclude: frozenset[Category] = frozenset()  # per-request exclusions, on top of saved settings
    document_search: bool = True
    document_ids: tuple[int, ...] | None = None  # None inherits; empty clears pins


@dataclass
class PreparedHistory:
    """Replayable messages for a turn, with the snapshots they cite and what privacy withheld."""

    messages: list[AdvisorMessage]
    snapshots: dict[str, ContextSnapshot]
    withheld_ids: list[int] = field(default_factory=list)
    withheld_categories: list[str] = field(default_factory=list)

    def decision(self) -> HistoryDecision:
        return HistoryDecision(self.messages, self.withheld_ids, self.withheld_categories)

    def citations(self, message):
        snapshot = self.snapshots.get(message.context_snapshot_id)
        return payload_citations(snapshot.payload) if snapshot else []
