"""PRD ContextBuilder: run the selected tools and freeze the result as a Context Snapshot (§3.4)."""

import copy
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.context_tool_manager import CATEGORY_TOOLS, base_currency, derive_cash_runway
from app.modules.crud.advisor_handler import context_snapshot_handler
from app.modules.database.model import ContextSnapshot
from app.modules.llm.errors import AdvisorError
from app.schema.context_schema import ContextPackage, RouteDecision, ToolContext
from app.modules.documents.retrieval import library_fingerprint, search as search_documents


# Budget reduction order, lowest priority first. Sections not listed rank just above news.
SECTION_PRIORITY: tuple[str, ...] = (
    "get_relevant_news", "get_market_data", "get_health_summary", "get_monthly_asset_history", "get_tasks",
    "search_documents", "get_calendar_events", "get_interview_schedule", "get_goals", "get_job_applications",
    "get_profile", "get_portfolio_summary", "get_cashflow_summary", "get_accounts_summary", "cash_runway",
)
# Calculated numbers the advisor must never lose; their row lists can be summarized, the section cannot go.
ESSENTIAL_SECTIONS = frozenset({"get_accounts_summary", "get_cashflow_summary", "get_portfolio_summary",
                                "cash_runway"})
ESSENTIAL_KEYS = frozenset({"computed", "computed_by", "currency", "base_currency", "monthly_expense",
                            "monthly_income", "source", "synced_at", "stale"})
FREE_TEXT_KEYS = ("jd_excerpt", "notes", "prep_notes", "description", "compensation_note", "next_step", "location")
TEXT_CAP = 300
ROW_FLOOR = 5
MAX_FLAGS = 40


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
        # The snapshot id, timestamp and query are added to the payload after fitting; reserve their room.
        overhead = len(json.dumps({"context_snapshot_id": str(uuid.uuid4()), "generated_at": now.isoformat(),
                                   "request_query": query}, ensure_ascii=False, separators=(",", ":"))) - 1
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
        }, query, self.char_limit - overhead)
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

    def _fit(self, body: dict, query: str = "", limit: int | None = None) -> dict:
        """Enforce the serialized size budget deterministically, reporting everything left out.

        Steps run in order until the package fits: cap long text, drop free text, keep only the
        first rows of low-priority lists (question-relevant rows first), drop whole low-priority
        sections, reduce essential sections to their calculated numbers. Calculated numbers in
        ESSENTIAL_SECTIONS are never removed. If even that does not fit, BudgetExceeded is raised:
        an oversized package is never returned.
        """
        limit = self.char_limit if limit is None else limit
        body = copy.deepcopy(body)
        data: dict = body["data"]
        base_flags: list[dict] = body["data_quality_flags"]
        fit_flags: list[dict] = []
        terms = _query_terms(query)
        cap_flags = False

        def fits() -> bool:
            # Budget flags always survive; only the tools' own flags are ever capped (last step).
            body["data_quality_flags"] = (_cap_flags(base_flags) if cap_flags else base_flags) + fit_flags
            return _size(body) <= limit

        if fits():
            return body

        order = _reduction_order(data, terms)

        # 1-2. Free text: cap, then drop.
        if _cap_text(data, TEXT_CAP):
            fit_flags.append({"code": "context_text_trimmed", "category": "system"})
            if fits():
                return body
        dropped = _drop_text(data)
        if dropped:
            fit_flags.append({"code": "context_text_omitted", "category": "system", "detail": ", ".join(dropped)})
            if fits():
                return body

        # 3. Long row lists, lowest priority section first; relevant rows survive.
        for name in order:
            omitted = _shrink_rows(data.get(name), terms, ROW_FLOOR)
            if omitted:
                fit_flags.append({"code": "context_rows_omitted", "category": "system", "detail": f"{name}: {omitted}"})
                if fits():
                    return body

        # 4. Whole low-priority sections.
        for name in order:
            if name in data and name not in ESSENTIAL_SECTIONS:
                del data[name]
                fit_flags.append({"code": "context_section_omitted", "category": "system", "detail": name})
                if fits():
                    return body

        # 5. Essential sections keep only their calculated numbers.
        for name in order:
            section = data.get(name)
            if isinstance(section, dict):
                removed = sorted(k for k in section if k not in ESSENTIAL_KEYS)
                if removed:
                    data[name] = {k: v for k, v in section.items() if k in ESSENTIAL_KEYS}
                    fit_flags.append({"code": "context_records_summarized", "category": "system",
                                      "detail": f"{name}: {', '.join(removed)}"})
                    if fits():
                        return body

        # 6. Repetitive tool flags (e.g. one stale_price per holding).
        cap_flags = True
        if fits():
            return body
        raise BudgetExceeded(f"context package exceeds {limit} chars even with only calculated numbers")


class BudgetExceeded(AdvisorError):
    code = "context_over_budget"
    http_status = 422
    user_message = "필수 재무 수치만으로도 Context 길이 제한을 넘어 요청을 보내지 않았습니다."


def _size(body: dict) -> int:
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str))


def _query_terms(query: str) -> list[str]:
    return [t for t in re.split(r"[\s,.?!·()\[\]\"'/]+", query.lower()) if len(t) >= 2]


def _row_relevant(row: dict, terms: list[str]) -> bool:
    for value in row.values():
        if isinstance(value, str) and len(value) >= 2:
            v = value.lower()
            if any(t in v or v in t for t in terms):
                return True
    return False


def _row_lists(section) -> list[tuple[str, list]]:
    if not isinstance(section, dict):
        return []
    return [(k, v) for k, v in section.items() if isinstance(v, list) and v and all(isinstance(r, dict) for r in v)]


def _reduction_order(data: dict, terms: list[str]) -> list[str]:
    """Lowest priority first; a section holding question-relevant rows is reduced after the others."""
    rank = {name: i for i, name in enumerate(SECTION_PRIORITY)}

    def key(name: str) -> tuple[int, int, str]:
        relevant = any(_row_relevant(r, terms) for _, rows in _row_lists(data[name]) for r in rows)
        return (1 if relevant else 0, rank.get(name, 0), name)

    return sorted(data, key=key)


def _walk_rows(data: dict):
    for section in data.values():
        for _, rows in _row_lists(section):
            yield from rows


def _cap_text(data: dict, cap: int) -> bool:
    changed = False
    for row in _walk_rows(data):
        for key, value in row.items():
            if isinstance(value, str) and len(value) > cap:
                row[key] = value[:cap] + " …[truncated]"
                changed = True
    return changed


def _drop_text(data: dict) -> list[str]:
    dropped = set()
    for row in _walk_rows(data):
        for key in FREE_TEXT_KEYS:
            if row.get(key) is not None:
                row[key] = None
                dropped.add(key)
    return sorted(dropped)


def _shrink_rows(section, terms: list[str], keep: int) -> int:
    omitted = 0
    for key, rows in _row_lists(section):
        if len(rows) <= keep:
            continue
        ranked = sorted(range(len(rows)), key=lambda i: (not _row_relevant(rows[i], terms), i))[:keep]
        section[key] = [rows[i] for i in sorted(ranked)]
        section[f"{key}_omitted_rows"] = len(rows) - keep
        omitted += len(rows) - keep
    return omitted


def _cap_flags(flags: list[dict]) -> list[dict]:
    """One flag per (code, category), with a repeat count, then at most MAX_FLAGS."""
    merged: dict[tuple, dict] = {}
    for f in flags:
        key = (f.get("code"), f.get("category"))
        if key in merged:
            merged[key]["count"] = merged[key].get("count", 1) + 1
        else:
            merged[key] = dict(f)
    out = list(merged.values())
    if len(out) > MAX_FLAGS:
        out = out[:MAX_FLAGS - 1] + [{"code": "data_quality_flags_omitted", "category": "system",
                                      "detail": str(len(out) - MAX_FLAGS + 1)}]
    return out


context_builder_manager = ContextBuilderManager(settings.context_char_limit)
