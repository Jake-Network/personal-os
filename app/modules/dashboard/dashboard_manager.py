"""Dashboard summary: the same read-only tools the advisor uses, without any LLM call."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.database.model import Account
from app.modules.finance.liquidity_policy import CASH_ACCOUNT_KINDS
from app.modules.llm.llm_gateway_manager import llm_gateway_manager

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.context_builder_manager import context_builder_manager


class DashboardManager:
    def summary(self, session: Session, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        # Local display only, so privacy exclusions (which govern what leaves the machine) do not apply.
        selected = frozenset(ALL_CATEGORIES) - {Category.PROFILE}
        data, _, flags, freshness = context_builder_manager.collect(session, selected, now, external_sharing=False)
        today = now.astimezone(ZoneInfo(settings.timezone)).date()
        cashflow = data.get("get_cashflow_summary", {})
        goals = data.get("get_goals", {}).get("active_goals", [])
        applications = data.get("get_job_applications", {}).get("applications", [])
        interviews = data.get("get_interview_schedule", {}).get("interviews", [])
        signals = []
        if (cashflow.get("expense_comparison_complete")
                and Decimal(cashflow["current_month_expense"]) > Decimal(cashflow["monthly_expense"]["monthly_average"])):
            signals.append({"kind": "expenses", "count": 1})
        due_goals = [g for g in goals if g.get("target_date")
                     and today <= date.fromisoformat(g["target_date"]) < today + timedelta(days=14)]
        if due_goals:
            signals.append({"kind": "goals", "count": len(due_goals)})
        upcoming = [i for i in interviews if now <= datetime.fromisoformat(i["starts_at"]) < now + timedelta(days=7)]
        if upcoming:
            signals.append({"kind": "interviews", "count": len(upcoming)})
        last = data.get("get_health_summary", {}).get("last_session_on")
        if last and date.fromisoformat(last) < today - timedelta(days=6):
            signals.append({"kind": "exercise", "count": 1})
        checklist = {
            "ai_configuration_complete": llm_gateway_manager.configuration_complete(session),
            "has_cash_account": session.scalar(select(Account.id).where(Account.kind.in_(CASH_ACCOUNT_KINDS)).limit(1)) is not None,
            "has_recent_expense": cashflow.get("has_recent_expense", False),
            "has_active_application_or_goal": bool(applications or goals),
        }
        return {"signals": signals, "checklist": checklist, "generated_at": now.isoformat(), "data": data, "data_quality_flags": flags,
                "source_updated_at": freshness, "computed": {"runway": data.get("cash_runway")}}


dashboard_manager = DashboardManager()
