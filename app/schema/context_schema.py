import json
from dataclasses import dataclass, field
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

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
    session: Session
    now: datetime
    allowed: frozenset[Category]
    query: str = ""

    @property
    def today(self) -> date:
        return self.now.date()


@dataclass
class ToolResult:
    data: dict
    refs: list[dict] = field(default_factory=list)
    source_updated_at: datetime | None = None
    flags: list[dict] = field(default_factory=list)


@dataclass
class ContextPackage:
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


class PrivacySettings(BaseModel):
    excluded_categories: list[Category]


class SnapshotResponse(BaseModel):
    context_snapshot_id: str
    conversation_id: int | None
    generated_at: datetime
    context_categories: list[str]
    excluded_categories: list[str]
    record_references: list[dict]
    source_updated_at: dict
    data_quality_flags: list[dict]
    payload: dict


class SnapshotCompareResponse(BaseModel):
    context_snapshot_id: str
    snapshot_generated_at: datetime
    compared_at: datetime
    changed_sections: list[str]
    unchanged_sections: list[str]
