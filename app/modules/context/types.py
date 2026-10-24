"""Types passed between context routing, tools, package building and history privacy."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import NotRequired, TypedDict

from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.database.model import AdvisorMessage
from app.modules.documents.types import DocumentCitation


class RecordRef(TypedDict):
    """A source a context tool read. Row refs carry `id`; aggregate refs carry `count` and `since`."""

    table: str
    id: NotRequired[int | None]
    updated_at: NotRequired[str | None]
    count: NotRequired[int]
    since: NotRequired[str]
    document_id: NotRequired[int]
    version_id: NotRequired[int]
    position_id: NotRequired[str]


class ContextRecordRef(RecordRef):
    """A RecordRef tagged by the builder with the category and tool that produced it."""

    category: str
    tool: str


class DataQualityFlag(TypedDict):
    """A caveat on the context data, surfaced to the model and the Context Inspector."""

    code: str
    category: str  # a Category value, "documents" or "system"
    detail: NotRequired[str]
    count: NotRequired[int]  # repeats merged into this flag
    document_ids: NotRequired[list[int]]


class RouteDecisionDict(TypedDict):
    requested: list[str]
    selected: list[str]
    excluded: list[str]
    matched_terms: list[str]
    reason: str


class HistoryDecisionDict(TypedDict):
    history_withheld_messages: int
    history_withheld_categories: list[str]


class CalendarScopeDict(TypedDict):
    start: str
    end_exclusive: str
    timezone: str
    status: str
    label: str


def data_citations(data: dict) -> list[DocumentCitation]:
    """Document excerpts in a package's `data` section (the one place this path is spelled out)."""
    return data.get("search_documents", {}).get("citations", [])


def payload_citations(payload: dict) -> list[DocumentCitation]:
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

    def as_dict(self) -> RouteDecisionDict:
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
    external_sharing: bool = True

    @property
    def today(self) -> date:
        return self.now.date()


@dataclass
class ToolResult:
    """Output of one context tool. The builder tags refs with category and tool name when it merges them."""

    data: dict
    refs: list[RecordRef] = field(default_factory=list)
    source_updated_at: datetime | None = None
    flags: list[DataQualityFlag] = field(default_factory=list)


@dataclass
class ContextPackage:
    """One turn's personal data: sent to the LLM and stored as a context snapshot."""

    snapshot_id: str
    payload: dict
    reused: bool
    categories: list[str]
    excluded_categories: list[str]
    source_updated_at: dict
    record_references: list[ContextRecordRef]
    data_quality_flags: list[DataQualityFlag]

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
            # Catalog entries were only offered to the planner; the panel lists what the answer used.
            "record_references": [ref for ref in self.record_references if ref.get("role") != "catalog"],
            "data_quality_flags": self.data_quality_flags,
            "document_citations": payload_citations(self.payload),
            "web_sources": self.payload.get('data', {}).get('web_search', {}).get('pages', []),
            "playbooks": [{"ref": ref, "playbook_id": item.get("playbook_id"), "slug": item.get("slug"),
                           "title": item.get("title")}
                          for ref, item in self.payload.get('data', {}).get('playbooks', {}).get('items', {}).items()],
        }


@dataclass(frozen=True)
class HistoryDecision:
    """Replayed history after privacy filtering: messages kept and messages withheld."""

    kept: list[AdvisorMessage]
    withheld_ids: list[int]
    withheld_categories: list[str]  # excluded categories that caused withholding

    def as_dict(self) -> HistoryDecisionDict:
        return {"history_withheld_messages": len(self.withheld_ids),
                "history_withheld_categories": self.withheld_categories}


@dataclass(frozen=True)
class CalendarScope:
    """Calendar window read from a question; `end` is exclusive."""

    start: datetime
    end: datetime
    status: str
    label: str

    def as_dict(self) -> CalendarScopeDict:
        return {"start": self.start.isoformat(), "end_exclusive": self.end.isoformat(),
                "timezone": str(self.start.tzinfo), "status": self.status, "label": self.label}
