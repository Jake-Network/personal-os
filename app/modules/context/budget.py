"""Deterministic size budget for the Context Package: what to trim, drop or summarize, in order."""

import copy
import json
import re

from app.modules.context.errors import BudgetExceeded
from app.modules.context.types import DataQualityFlag, data_citations

# Budget reduction order, lowest priority first. Sections not listed rank just above news.
SECTION_PRIORITY: tuple[str, ...] = (
    "get_relevant_news", "get_market_data", "get_health_summary", "get_monthly_asset_history", "get_tasks",
    "playbooks",
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


def fit_document_excerpts(data: dict, char_limit: int) -> None:
    """Share at most half the budget (10,000 chars) evenly among the cited excerpts."""
    citations = data_citations(data)
    if not citations:
        return
    budget = min(10_000, max(0, char_limit // 2))
    allowance = budget // len(citations)
    for citation in citations:
        if len(citation["text"]) > allowance:
            citation["text"] = citation["text"][:allowance] + " …[truncated]"


def fit_to_budget(body: dict, query: str, limit: int) -> dict:
    """Enforce the serialized size budget deterministically, reporting everything left out.

    Steps run in order until the package fits: cap long text, drop free text, keep only the
    first rows of low-priority lists (question-relevant rows first), drop whole low-priority
    sections, reduce essential sections to their calculated numbers. Calculated numbers in
    ESSENTIAL_SECTIONS are never removed. If even that does not fit, BudgetExceeded is raised:
    an oversized package is never returned.
    """
    body = copy.deepcopy(body)
    data: dict = body["data"]
    base_flags: list[DataQualityFlag] = body["data_quality_flags"]
    fit_flags: list[DataQualityFlag] = []
    terms = _query_terms(query)
    required_memories = [row for row in data.get("get_profile", {}).get("confirmed_memories", [])
                         if row.get("kind") in {"constraint", "priority"}]
    essential_sections = ESSENTIAL_SECTIONS | ({"get_profile"} if required_memories else set())
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
        if name in data and name not in essential_sections:
            del data[name]
            fit_flags.append({"code": "context_section_omitted", "category": "system", "detail": name})
            if fits():
                return body

    # 5. Essential sections keep only their calculated numbers.
    for name in order:
        section = data.get(name)
        if name == "get_profile" and required_memories:
            data[name] = {"confirmed_memories": required_memories}
            fit_flags.append({"code": "optional_memories_omitted", "category": "profile"})
            if fits():
                return body
            continue
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
        if row.get("kind") in {"constraint", "priority"}:
            continue
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
        required = [i for i, row in enumerate(rows) if row.get("kind") in {"constraint", "priority"}]
        optional = sorted((i for i in range(len(rows)) if i not in required),
                          key=lambda i: (not _row_relevant(rows[i], terms), i))[:max(0, keep - len(required))]
        ranked = required + optional
        section[key] = [rows[i] for i in sorted(ranked)]
        section[f"{key}_omitted_rows"] = len(rows) - len(ranked)
        omitted += len(rows) - len(ranked)
    return omitted


def _cap_flags(flags: list[DataQualityFlag]) -> list[DataQualityFlag]:
    """One flag per (code, category), with a repeat count, then at most MAX_FLAGS."""
    merged: dict[tuple, DataQualityFlag] = {}
    for f in flags:
        key = (f.get("code"), f.get("category"))
        if key in merged:
            merged[key]["count"] = merged[key].get("count", 1) + 1
        else:
            merged[key] = f.copy()
    out = list(merged.values())
    if len(out) > MAX_FLAGS:
        out = out[:MAX_FLAGS - 1] + [{"code": "data_quality_flags_omitted", "category": "system",
                                      "detail": str(len(out) - MAX_FLAGS + 1)}]
    return out
