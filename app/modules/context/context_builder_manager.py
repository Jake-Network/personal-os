"""PRD ContextBuilder: run the selected tools and freeze the result as a Context Snapshot (§3.4)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.context_tool_manager import CATEGORY_TOOLS, base_currency
from app.modules.crud.advisor_handler import context_snapshot_handler
from app.modules.database.model import ContextSnapshot
from app.schema.context_schema import ContextPackage, RouteDecision, ToolContext
from app.modules.documents.retrieval import library_fingerprint, search as search_documents


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _package(snapshot: ContextSnapshot, reused: bool) -> ContextPackage:
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


class ContextBuilderManager:
    def __init__(self, char_limit: int):
        self.char_limit = char_limit

    def collect(self, session: Session, selected: frozenset[Category], now: datetime, *, query: str = ""
                ) -> tuple[dict, list[dict], list[dict], dict]:
        """Run every tool for the selected categories. Returns (data, refs, flags, freshness)."""
        ctx = ToolContext(session=session, now=now, allowed=selected, query=query)
        data: dict[str, dict] = {}
        refs: list[dict] = []
        flags: list[dict] = []
        freshness: dict[str, str | None] = {}
        for category in ALL_CATEGORIES:
            if category not in selected:
                continue
            latest = None
            for name, tool in CATEGORY_TOOLS[category]:
                result = tool(ctx)
                data[name] = result.data
                refs += [{**r, "category": category.value, "tool": name} for r in result.refs]
                flags += result.flags
                if result.source_updated_at and (latest is None or result.source_updated_at > latest):
                    latest = result.source_updated_at
            freshness[category.value] = latest.isoformat() if latest else None
        return data, refs, flags, freshness

    def build(self, session: Session, route: RouteDecision, conversation_id: int | None = None,
              now: datetime | None = None, *, query: str = "", document_search: bool = True,
              document_ids: tuple[int, ...] = (), excluded: frozenset[Category] = frozenset(),
              inherited_citations: list[dict] | None = None,
              inherited_dependencies: list[dict] | None = None,
              inherited_categories: list[str] | None = None,
              history_document_refs: set[str] | None = None,
              inherited_unknown: bool = False) -> ContextPackage:
        now = now or datetime.now(UTC)
        data, refs, flags, freshness = self.collect(session, route.selected, now, query=query)
        if document_search and query:
            result = search_documents(session, query, route.selected, document_ids or None,
                                      excluded_categories=excluded)
            # Empty libraries keep the original stable structured-data snapshot.
            if result.data.get("citations") or any(f["code"] != "no_matching_documents" for f in result.flags) or document_ids:
                data["search_documents"] = result.data
                refs += [{**r, "category": "documents", "tool": "search_documents"} for r in result.refs]
                flags += result.flags
                freshness["documents"] = result.source_updated_at.isoformat() if result.source_updated_at else None
        for category in sorted(route.excluded):
            flags.append({"code": "category_excluded_by_user", "category": category.value})
        dependencies = {(d["document_id"], d["version_id"]): d for d in inherited_dependencies or []}
        direct = data.get("search_documents", {}).get("citations", [])
        for citation in [*direct, *(inherited_citations or [])]:
            key = (citation["document_id"], citation["version_id"])
            dependencies[key] = {"document_id": key[0], "version_id": key[1]}
        if inherited_citations:
            section = data.setdefault("search_documents", {"query": query, "citations": []})
            combined = {c["ref"]: dict(c) for c in direct}
            for citation in inherited_citations:
                combined.setdefault(citation["ref"], dict(citation))
            section["citations"] = list(combined.values())[:10]
        self._fit_document_excerpts(data)
        available_refs = {c["ref"] for c in data.get("search_documents", {}).get("citations", [])}
        omitted_refs = (history_document_refs or set()) - available_refs
        if omitted_refs:
            flags.append({"code": "history_document_evidence_omitted", "category": "documents",
                          "count": len(omitted_refs)})
        body = self._fit({
            "document_dependencies": list(dependencies.values()),
            "history_categories": sorted(set(inherited_categories or []) - {c.value for c in route.selected}),
            **({"history_provenance_unknown": True} if inherited_unknown else {}),
            "document_scope": {"enabled": document_search, "document_ids": list(document_ids),
                               "excluded_categories": sorted(str(c) for c in excluded)},
            "base_currency": base_currency(session),
            "categories": sorted(c.value for c in route.selected),
            "excluded_categories": sorted(c.value for c in route.excluded),
            "data": data,
            "data_quality_flags": flags,
        })
        content_hash = _hash(body)

        # Unchanged data since the previous turn → reuse that snapshot instead of a duplicate.
        if conversation_id is not None:
            previous = context_snapshot_handler.get_latest_for_conversation(session, conversation_id)
            if previous is not None and previous.content_hash == content_hash:
                return _package(previous, reused=True)

        snapshot_id = str(uuid.uuid4())
        snapshot = context_snapshot_handler.create(session, {
            "id": snapshot_id,
            "conversation_id": conversation_id,
            "generated_at": now,
            "context_categories": body["categories"],
            "excluded_categories": body["excluded_categories"],
            "record_references": refs,
            "source_updated_at": freshness,
            "data_quality_flags": body["data_quality_flags"],
            "payload": {"context_snapshot_id": snapshot_id, "generated_at": now.isoformat(),
                        "request_query": query, **body},
            "content_hash": content_hash,
        })
        return _package(snapshot, reused=False)

    def compare_with_current(self, session: Session, snapshot: ContextSnapshot,
                             now: datetime | None = None) -> tuple[list[str], list[str]]:
        """Which tool sections differ between a past snapshot and today's data (same categories)."""
        selected = frozenset(Category(c) for c in snapshot.context_categories)
        current, _, _, _ = self.collect(session, selected, now or datetime.now(UTC),
                                      query=snapshot.payload.get("request_query", ""))
        past = snapshot.payload.get("data", {})
        if "search_documents" in past:
            scope = snapshot.payload.get("document_scope", {})
            fingerprint = library_fingerprint(session, selected, scope.get("document_ids"),
                                              scope.get("excluded_categories", []))
            previous = past["search_documents"]
            current["search_documents"] = previous if previous.get("source_fingerprint") == fingerprint else {
                "source_fingerprint": fingerprint,
            }
        changed = sorted(k for k in set(past) | set(current) if _hash(past.get(k) or {}) != _hash(current.get(k) or {}))
        unchanged = sorted(k for k in set(past) & set(current) if k not in changed)
        return changed, unchanged

    def _fit_document_excerpts(self, data: dict) -> None:
        citations = data.get("search_documents", {}).get("citations", [])
        if not citations:
            return
        budget = min(10_000, max(0, self.char_limit // 2))
        allowance = budget // len(citations)
        for citation in citations:
            if len(citation["text"]) > allowance:
                citation["text"] = citation["text"][:allowance] + " …[truncated]"

    def _fit(self, body: dict) -> dict:
        """Enforce the context length budget by dropping bulky free text first, never numbers."""
        if len(json.dumps(body, ensure_ascii=False, default=str)) <= self.char_limit:
            return body
        for app in body["data"].get("get_job_applications", {}).get("applications", []):
            app["jd_excerpt"] = (app["jd_excerpt"] or "")[:300] or None
        for section in body["data"].values():
            for rows in section.values():
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            for key in ("notes", "prep_notes"):
                                if key in row:
                                    row[key] = None
        over = len(json.dumps(body, ensure_ascii=False, default=str)) > self.char_limit
        body["data_quality_flags"] = body["data_quality_flags"] + [
            {"code": "context_over_budget" if over else "context_text_trimmed", "category": "system"}
        ]
        return body


context_builder_manager = ContextBuilderManager(settings.context_char_limit)
