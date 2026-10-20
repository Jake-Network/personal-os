from typing import Any, Literal

from pydantic import BaseModel

from app.modules.context.types import DataQualityFlag


class DashboardSignal(BaseModel):
    kind: Literal['expenses', 'goals', 'interviews', 'exercise']
    count: int


class DashboardChecklist(BaseModel):
    ai_configuration_complete: bool
    has_cash_account: bool
    has_recent_expense: bool
    has_active_application_or_goal: bool


class DashboardSummary(BaseModel):
    generated_at: str
    data: dict[str, Any]
    data_quality_flags: list[DataQualityFlag]
    source_updated_at: dict[str, str | None]
    computed: dict[str, Any]
    signals: list[DashboardSignal]
    checklist: DashboardChecklist
