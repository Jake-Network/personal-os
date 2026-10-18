"""Dashboard summary: the same read-only tools the advisor uses, without any LLM call."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.context_builder_manager import context_builder_manager


class DashboardManager:
    def summary(self, session: Session, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        # Local display only, so privacy exclusions (which govern what leaves the machine) do not apply.
        selected = frozenset(ALL_CATEGORIES) - {Category.PROFILE}
        data, _, flags, freshness = context_builder_manager.collect(session, selected, now)
        return {"generated_at": now.isoformat(), "data": data, "data_quality_flags": flags,
                "source_updated_at": freshness, "computed": {"runway": data.get("cash_runway")}}


dashboard_manager = DashboardManager()
