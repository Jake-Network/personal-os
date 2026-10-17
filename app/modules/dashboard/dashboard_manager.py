"""Dashboard summary: the same read-only tools the advisor uses, without any LLM call."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.context_builder_manager import context_builder_manager
from app.modules.finance.financial_calculator import financial_calculator


class DashboardManager:
    def summary(self, session: Session, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        # Local display only, so privacy exclusions (which govern what leaves the machine) do not apply.
        selected = frozenset(ALL_CATEGORIES) - {Category.PROFILE}
        data, _, flags, freshness = context_builder_manager.collect(session, selected, now)
        return {"generated_at": now.isoformat(), "data": data, "data_quality_flags": flags,
                "source_updated_at": freshness, "computed": {"runway": self._runway(data)}}

    @staticmethod
    def _runway(data: dict) -> dict | None:
        """Months of liquid assets at the recent average spend; None when either input is missing."""
        worth = data.get("get_accounts_summary", {}).get("computed", {}).get("net_worth")
        expense = data.get("get_cashflow_summary", {}).get("monthly_expense", {})
        if not worth or not expense.get("available"):
            return None
        return financial_calculator.runway(Decimal(worth["liquid_assets"]), Decimal(expense["monthly_average"]))


dashboard_manager = DashboardManager()
