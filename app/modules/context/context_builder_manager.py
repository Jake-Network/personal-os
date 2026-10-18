"""PRD ContextBuilder: run the selected tools and freeze the result as a Context Snapshot (§3.4)."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.budget import fit_document_excerpts, fit_to_budget
from app.modules.context.context_tool_manager import CATEGORY_TOOLS, base_currency
from app.modules.context.derived import derive_cash_runway
from app.modules.context.snapshots import content_hash, merge_document_evidence, to_package
from app.modules.crud import context_snapshot_handler
from app.modules.database.model import ContextSnapshot
from app.modules.context.types import (
    ContextPackage,
    ContextRecordRef,
    DataQualityFlag,
    RouteDecision,
    ToolContext,
    ToolResult,
    data_citations,
)
from app.modules.documents.retrieval import cited_categories, library_fingerprint, search as search_documents


class ContextBuilderManager:
    def __init__(self, char_limit: int):
        self.char_limit = char_limit

    def collect(self, session: Session, selected: frozenset[Category], now: datetime, *, query: str = "", document_scope: dict | None = None,
                external_sharing: bool = True
                ) -> tuple[dict, list[ContextRecordRef], list[DataQualityFlag], dict]:
        """Run every tool for the selected categories. Returns (data, refs, flags, freshness)."""
        ctx = ToolContext(session=session, now=now, allowed=selected, query=query, external_sharing=external_sharing)
        data: dict[str, dict] = {}
        refs: list[ContextRecordRef] = []
        flags: list[DataQualityFlag] = []
        freshness: dict[str, str | None] = {}
        for category in ALL_CATEGORIES:
            if category not in selected:
                continue
            latest = None
            for name, tool in CATEGORY_TOOLS[category]:
                from app.modules.context.record_privacy import tool_blocked
                if external_sharing and tool_blocked(session, name):
                    flags.append({"code": "records_excluded_by_user", "category": category.value,
                                  "detail": f"{name}: 관련 기록이 로컬 전용이므로 전체 계산/요약을 제외했습니다."})
                    continue
                result = tool(ctx)
                if external_sharing and name == "get_cashflow_summary":
                    from app.modules.context.source_policy import source_allowed
                    # Ledger amounts may derive from a holding even when this
                    # question selected only finance. Omit the aggregate without
                    # making the rest of the consultation unavailable.
                    if not source_allowed(session, result.refs, frozenset(ALL_CATEGORIES) - selected):
                        flags.append({"code": "source_sharing_scope_excluded", "category": category.value,
                                      "detail": name})
                        continue
                if document_scope and name in {"get_profile", "get_career_records"}:
                    from app.modules.context.source_policy import source_allowed
                    if any(not source_allowed(session, [ref], frozenset(ALL_CATEGORIES) - selected,
                                              document_scope=document_scope) for ref in result.refs):
                        flags.append({"code": "source_sharing_scope_excluded", "category": category.value,
                                      "detail": name})
                        continue
                from app.modules.context.record_privacy import aggregate_source_ids
                result.refs.extend(aggregate_source_ids(session, result.refs))
                data[name] = result.data
                refs += [{**r, "category": category.value, "tool": name} for r in result.refs]
                flags += result.flags
                if result.source_updated_at and (latest is None or result.source_updated_at > latest):
                    latest = result.source_updated_at
            freshness[category.value] = latest.isoformat() if latest else None
        runway = derive_cash_runway(data)
        if runway is not None:
            data["cash_runway"] = runway
        return data, refs, flags, freshness

    def build(self, session: Session, route: RouteDecision, conversation_id: int | None = None,
              now: datetime | None = None, *, query: str = "", document_search: bool = True,
              document_ids: tuple[int, ...] = (), excluded: frozenset[Category] = frozenset(),
              inherited_citations: list[dict] | None = None,
              inherited_dependencies: list[dict] | None = None,
              inherited_categories: list[str] | None = None,
              history_document_refs: set[str] | None = None,
              inherited_unknown: bool = False, history_message_refs: list[int] | None = None,
              history_search_flags: list[dict] | None = None,
              historical_experiences: ToolResult | None = None) -> ContextPackage:
        now = now or datetime.now(UTC)
        data, refs, flags, freshness = self.collect(session, route.selected, now, query=query,
            document_scope={"enabled": document_search, "document_ids": list(document_ids)})
        refs += [{"table": "advisor_messages", "id": mid, "category": "profile", "tool": "history"}
                 for mid in history_message_refs or []]
        flags.extend(history_search_flags or [])
        if historical_experiences and historical_experiences.refs:
            data["search_past_experiences"] = historical_experiences.data
            refs.extend({**ref, "category": "profile", "tool": "search_past_experiences"} for ref in historical_experiences.refs)
            flags.extend(historical_experiences.flags)
        from app.modules.context.record_privacy import stamp_references
        refs = stamp_references(session, refs)
        if document_search and query:
            # Every shared document is searchable whatever the question's topic; privacy exclusions still apply.
            result = search_documents(session, query, None, document_ids or None,
                                      excluded_categories=excluded)
            # Empty libraries keep the original stable structured-data snapshot.
            if result.data.get("citations") or any(f["code"] != "no_matching_documents" for f in result.flags) or document_ids:
                data["search_documents"] = result.data
                refs += [{**r, "category": "documents", "tool": "search_documents"} for r in result.refs]
                flags += result.flags
                freshness["documents"] = result.source_updated_at.isoformat() if result.source_updated_at else None
        for category in sorted(route.excluded):
            flags.append({"code": "category_excluded_by_user", "category": category.value})
        dependencies = merge_document_evidence(data, query, inherited_citations, inherited_dependencies)
        fit_document_excerpts(data, self.char_limit)
        cited = data_citations(data)
        available_refs = {c["ref"] for c in cited}
        document_categories = cited_categories(session, cited)
        omitted_refs = (history_document_refs or set()) - available_refs
        if omitted_refs:
            flags.append({"code": "history_document_evidence_omitted", "category": "documents",
                          "count": len(omitted_refs)})
        # The snapshot id, timestamp and query are added to the payload after fitting; reserve their room.
        overhead = len(json.dumps({"context_snapshot_id": str(uuid.uuid4()), "generated_at": now.isoformat(),
                                   "request_query": query}, ensure_ascii=False, separators=(",", ":"))) - 1
        body = fit_to_budget({
            "history_message_ids": history_message_refs or [],
            "document_dependencies": dependencies,
            # Topics of the cited documents: history privacy taints the turn with them too.
            "document_categories": document_categories,
            "history_categories": sorted(set(inherited_categories or []) - {c.value for c in route.selected}),
            **({"history_provenance_unknown": True} if inherited_unknown else {}),
            "document_scope": {"enabled": document_search, "document_ids": list(document_ids),
                               "excluded_categories": sorted(str(c) for c in excluded)},
            "base_currency": base_currency(session),
            "categories": sorted(c.value for c in route.selected),
            "excluded_categories": sorted(c.value for c in route.excluded),
            "data": data,
            "data_quality_flags": flags,
        }, query, self.char_limit - overhead)
        body_hash = content_hash(body)

        # Unchanged data since the previous turn → reuse that snapshot instead of a duplicate.
        if conversation_id is not None:
            previous = context_snapshot_handler.get_latest_for_conversation(session, conversation_id)
            if previous is not None and not previous.payload.get("source_purged") and previous.content_hash == body_hash and previous.record_references == refs:
                return to_package(previous, reused=True)

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
            "content_hash": body_hash,
        })
        return to_package(snapshot, reused=False)

    def compare_with_current(self, session: Session, snapshot: ContextSnapshot,
                             now: datetime | None = None) -> tuple[list[str], list[str]]:
        """Which tool sections differ between a past snapshot and today's data (same categories)."""
        selected = frozenset(Category(c) for c in snapshot.context_categories)
        current, _, _, _ = self.collect(session, selected, now or datetime.now(UTC),
                                      query=snapshot.payload.get("request_query", ""))
        # This action re-reads local domains/documents, never performs external research.
        past = {key: value for key, value in snapshot.payload.get("data", {}).items() if key != 'web_search'}
        if "search_documents" in past:
            scope = snapshot.payload.get("document_scope", {})
            fingerprint = library_fingerprint(session, None, scope.get("document_ids"),
                                              scope.get("excluded_categories", []))
            previous = past["search_documents"]
            current["search_documents"] = previous if previous.get("source_fingerprint") == fingerprint else {
                "source_fingerprint": fingerprint,
            }
        changed = sorted(k for k in set(past) | set(current) if content_hash(past.get(k) or {}) != content_hash(current.get(k) or {}))
        unchanged = sorted(k for k in set(past) & set(current) if k not in changed)
        return changed, unchanged

context_builder_manager = ContextBuilderManager(settings.context_char_limit)
