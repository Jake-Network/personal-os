"""Snapshot content hashing and the Context Package view of a stored snapshot."""

import hashlib
import json

from app.modules.context.types import ContextPackage, data_citations
from app.modules.database.model import ContextSnapshot


def content_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def to_package(snapshot: ContextSnapshot, reused: bool) -> ContextPackage:
    return ContextPackage(
        snapshot_id=snapshot.id,
        payload=snapshot.payload,
        reused=reused,
        categories=snapshot.context_categories,
        excluded_categories=snapshot.excluded_categories,
        source_updated_at=snapshot.source_updated_at,
        record_references=snapshot.record_references,
        data_quality_flags=snapshot.data_quality_flags,
    )


def merge_document_evidence(data: dict, query: str, inherited_citations: list[dict] | None,
                            inherited_dependencies: list[dict] | None) -> list[dict]:
    """Carry earlier turns' document evidence into this turn.

    Adds inherited citations to `data["search_documents"]` (direct hits first, at most 10) and
    returns every (document_id, version_id) the turn depends on.
    """
    dependencies = {(d["document_id"], d["version_id"]): d for d in inherited_dependencies or []}
    direct = data_citations(data)
    for citation in [*direct, *(inherited_citations or [])]:
        key = (citation["document_id"], citation["version_id"])
        dependencies[key] = {"document_id": key[0], "version_id": key[1]}
    if inherited_citations:
        section = data.setdefault("search_documents", {"query": query, "citations": []})
        combined = {c["ref"]: dict(c) for c in direct}
        for citation in inherited_citations:
            combined.setdefault(citation["ref"], dict(citation))
        section["citations"] = list(combined.values())[:10]
    return list(dependencies.values())
