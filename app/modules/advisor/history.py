"""Which replayed messages are safe to send, and what document evidence they carry into this turn."""

import re

from app.enums.context_category import Category
from app.modules.advisor.types import AskOptions, InheritedEvidence, PreparedHistory
from app.modules.context.types import payload_evidence
from app.modules.database.model import AdvisorMessage, ContextSnapshot

DOCUMENT_REFERENCE_PATTERN = re.compile(r"\[(document_chunks:\d+)\]")


def replay_safe_messages(history: list[AdvisorMessage], snapshots: dict[str, ContextSnapshot],
                         excluded: frozenset[Category], options: AskOptions,
                         visible_document_ids: set[int], version_ids: set[int]) -> list[AdvisorMessage]:
    """Drop turns whose categories or document evidence this request may not share."""
    safe = []
    for message in history:
        if getattr(message, "context_purged", False):
            continue
        snapshot = snapshots.get(message.context_snapshot_id)
        if snapshot is None:
            # Legacy user conversations have no captured provenance. Preserve normal
            # continuity, but cannot prove them safe under a new sharing restriction.
            if not message.context_snapshot_id and not excluded and options.document_search and not options.document_ids:
                safe.append(message)
            continue
        if snapshot.payload.get("history_provenance_unknown") and (excluded or not options.document_search or options.document_ids):
            continue
        if (set(snapshot.context_categories) | set(snapshot.payload.get("history_categories", []))
                | set(snapshot.payload.get("document_categories", []))).intersection(str(c) for c in excluded):
            continue
        evidence = payload_evidence(snapshot.payload)
        if evidence and not options.document_search:
            continue
        if any(c["document_id"] not in visible_document_ids or c["version_id"] not in version_ids or
               (options.document_ids and c["document_id"] not in options.document_ids)
               for c in evidence):
            continue
        safe.append(message)
    return safe


def inherited_evidence(prepared: PreparedHistory) -> InheritedEvidence:
    """Citations, dependencies and categories the replayed turns carry into this turn."""
    citations, dependencies, categories = {}, {}, set()
    unknown = False
    for message in prepared.messages:
        snapshot = prepared.snapshots.get(message.context_snapshot_id)
        unknown |= snapshot is None or bool(snapshot.payload.get("history_provenance_unknown"))
        for citation in prepared.citations(message):
            # Old excerpts explain past turns; they never become freshly retrieved facts.
            citations[citation["ref"]] = {**citation, "historical": True}
        if snapshot:
            categories.update(snapshot.context_categories)
            categories.update(snapshot.payload.get("history_categories", []))
            for dependency in snapshot.payload.get("document_dependencies", []):
                dependencies[(dependency["document_id"], dependency["version_id"])] = dependency
    return InheritedEvidence(
        citations=list(citations.values()),
        dependencies=list(dependencies.values()),
        categories=sorted(categories),
        unknown=unknown,
        document_refs={ref for message in prepared.messages
                       for ref in DOCUMENT_REFERENCE_PATTERN.findall(message.content)},
    )
