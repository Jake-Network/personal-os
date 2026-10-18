"""Types passed between context routing, tools, package building and history privacy."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.modules.database.model import AdvisorMessage
from app.enums.context_category import Category


def data_citations(data: dict) -> list[dict]:
    """Document excerpts in a package's `data` section (the one place this path is spelled out)."""
    return data.get("search_documents", {}).get("citations", [])


def payload_citations(payload: dict) -> list[dict]:
    return data_citations(payload.get("data", {}))


def payload_evidence(payload: dict) -> list[dict]:
    """Every (document_id, version_id) a snapshot depends on: inherited dependencies and its own citations."""
    return [*payload.get("document_dependencies", []), *payload_citations(payload)]


@dataclass(frozen=True)
class RouteDecision:
    """Which categories of personal data one question may draw on."""

    requested: frozenset[Category]  # what the question needs
    selected: frozenset[Category]  # requested minus excluded
    excluded: frozenset[Category]  # needed but blocked by the user's privacy settings
    matched_terms: tuple[str, ...]
    reason: str  # keyword | override | previous_turn | domain | fallback

    def as_dict(self) -> dict:
        return {
            "requested": sorted(self.requested),
            "selected": sorted(self.selected),
            "excluded": sorted(self.excluded),
            "matched_terms": list(self.matched_terms),
            "reason": self.reason,
        }


@dataclass
class ToolContext:
    """Input to one context tool run."""

    session: Session
    now: datetime
    allowed: frozenset[Category]
    query: str = ""

    @property
    def today(self) -> date:
        return self.now.date()


@dataclass
class ToolResult:
    """Output of one context tool. The builder tags refs with category and tool name when it merges them."""

    data: dict
    refs: list[dict] = field(default_factory=list)
    source_updated_at: datetime | None = None
    flags: list[dict] = field(default_factory=list)


@dataclass
class ContextPackage:
    """One turn's personal data: sent to the LLM and stored as a context snapshot."""

    snapshot_id: str
    payload: dict
    reused: bool
    categories: list[str]
    excluded_categories: list[str]
    source_updated_at: dict
    record_references: list[dict]
    data_quality_flags: list[dict]

    @property
    def text(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))

    def inspector(self) -> dict:
        """Context Inspector view: which categories, how fresh, which records."""
        return {
            "context_snapshot_id": self.snapshot_id,
            "context_reused": self.reused,
            "categories": self.categories,
            "excluded_categories": self.excluded_categories,
            "source_updated_at": self.source_updated_at,
            "record_references": self.record_references,
            "data_quality_flags": self.data_quality_flags,
            "document_citations": payload_citations(self.payload),
        }


@dataclass(frozen=True)
class HistoryDecision:
    """Replayed history after privacy filtering: messages kept and messages withheld."""

    kept: list[AdvisorMessage]
    withheld_ids: list[int]
    withheld_categories: list[str]  # excluded categories that caused withholding

    def as_dict(self) -> dict:
        return {"history_withheld_messages": len(self.withheld_ids),
                "history_withheld_categories": self.withheld_categories}


@dataclass(frozen=True)
class CalendarScope:
    """Calendar window read from a question; `end` is exclusive."""

    start: datetime
    end: datetime
    status: str
    label: str

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end_exclusive": self.end.isoformat(),
                "timezone": str(self.start.tzinfo), "status": self.status, "label": self.label}
