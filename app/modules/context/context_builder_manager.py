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

    def collect(self, session: Session, selected: frozenset[Category], now: datetime
                ) -> tuple[dict, list[dict], list[dict], dict]:
        """Run every tool for the selected categories. Returns (data, refs, flags, freshness)."""
        ctx = ToolContext(session=session, now=now, allowed=selected)
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
              now: datetime | None = None) -> ContextPackage:
        now = now or datetime.now(UTC)
        data, refs, flags, freshness = self.collect(session, route.selected, now)
        for category in sorted(route.excluded):
            flags.append({"code": "category_excluded_by_user", "category": category.value})
        body = self._fit({
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
            "payload": {"context_snapshot_id": snapshot_id, "generated_at": now.isoformat(), **body},
            "content_hash": content_hash,
        })
        return _package(snapshot, reused=False)

    def compare_with_current(self, session: Session, snapshot: ContextSnapshot,
                             now: datetime | None = None) -> tuple[list[str], list[str]]:
        """Which tool sections differ between a past snapshot and today's data (same categories)."""
        selected = frozenset(Category(c) for c in snapshot.context_categories)
        current, _, _, _ = self.collect(session, selected, now or datetime.now(UTC))
        past = snapshot.payload.get("data", {})
        changed = sorted(k for k in set(past) | set(current) if _hash(past.get(k) or {}) != _hash(current.get(k) or {}))
        unchanged = sorted(k for k in set(past) & set(current) if k not in changed)
        return changed, unchanged

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
