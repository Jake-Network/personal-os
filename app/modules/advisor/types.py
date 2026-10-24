"""Types passed through one advisor turn."""

from dataclasses import dataclass, field
from datetime import datetime

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
    history_since: datetime | None = None
    history_until: datetime | None = None
    history_company: str | None = None
    history_project: int | None = None
    history_decision: int | None = None
    web_search: bool = False
    web_query: str | None = None
    allow_data_recording: bool = False


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



@dataclass(frozen=True)
class InheritedEvidence:
    """Document evidence and categories that replayed turns carry into the next Context Package."""

    citations: list[dict]  # marked historical=true
    dependencies: list[dict]
    categories: list[str]
    unknown: bool  # some replayed turn has no recorded provenance
    document_refs: set[str]  # document_chunks refs cited in replayed message text
