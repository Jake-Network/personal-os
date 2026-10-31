from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.context.types import DataQualityFlag


class _ToolOutput(BaseModel):
    """A context tool output. Only the fields the home screen reads are typed; the rest pass through unchanged."""

    model_config = ConfigDict(extra='allow')


class DashboardSignal(BaseModel):
    kind: Literal['expenses', 'goals', 'interviews', 'exercise']
    count: int


class DashboardChecklist(BaseModel):
    ai_configuration_complete: bool
    has_cash_account: bool
    has_recent_expense: bool
    has_active_application_or_goal: bool


class DashboardNetWorth(_ToolOutput):
    """Decimal strings from the backend valuation; `None` when a value is not computable."""

    total_assets: str | None = None
    total_liabilities: str | None = None
    net_worth: str | None = None
    spendable_liquidity: str | None = None
    complete: bool = False


class DashboardAccountsComputed(_ToolOutput):
    net_worth: DashboardNetWorth | None = None


class DashboardAccountsSummary(_ToolOutput):
    computed: DashboardAccountsComputed | None = None


class DashboardMonthlyExpense(_ToolOutput):
    available: bool
    monthly_average: str | None = None
    months_considered: int | None = None
    months_with_data: int | None = None
    reason: str | None = None


class DashboardCashflowSummary(_ToolOutput):
    monthly_expense: DashboardMonthlyExpense | None = None


class DashboardApplication(_ToolOutput):
    ref: str
    company: str
    role: str
    status: str
    next_step: str | None = None


class DashboardJobApplications(_ToolOutput):
    applications: list[DashboardApplication] = []


class DashboardInterview(_ToolOutput):
    ref: str
    company: str
    stage: str
    starts_at: str


class DashboardInterviewSchedule(_ToolOutput):
    interviews: list[DashboardInterview] = []


class DashboardCalendarEvent(_ToolOutput):
    ref: str
    title: str
    kind: str
    starts_at: str
    all_day: bool = False


class DashboardCalendarConflict(_ToolOutput):
    a: str
    b: str


class DashboardCalendarEvents(_ToolOutput):
    events: list[DashboardCalendarEvent] = []
    conflicts: list[DashboardCalendarConflict] = []


class DashboardTask(_ToolOutput):
    ref: str
    title: str
    due_on: str | None = None
    overdue: bool = False


class DashboardTasks(_ToolOutput):
    open_tasks: list[DashboardTask] = []


class DashboardGoal(_ToolOutput):
    ref: str
    title: str
    target_value: str | None = None
    current_value: str | None = None
    unit: str | None = None
    target_date: str | None = None


class DashboardGoals(_ToolOutput):
    active_goals: list[DashboardGoal] = []


class DashboardHealth(_ToolOutput):
    sessions: int = 0
    total_seconds: int = 0
    last_session_on: str | None = None


class DashboardRunway(_ToolOutput):
    """Cash runway from spendable liquidity only; `available: false` carries the reason instead of a guess."""

    available: bool
    months: str | None = None
    reason: str | None = None
    understated: bool | None = None


class DashboardData(_ToolOutput):
    """Tool outputs keyed by tool name. A key is absent when its tool was not collected."""

    get_accounts_summary: DashboardAccountsSummary | None = None
    get_cashflow_summary: DashboardCashflowSummary | None = None
    get_job_applications: DashboardJobApplications | None = None
    get_interview_schedule: DashboardInterviewSchedule | None = None
    get_calendar_events: DashboardCalendarEvents | None = None
    get_tasks: DashboardTasks | None = None
    get_goals: DashboardGoals | None = None
    get_health_summary: DashboardHealth | None = None
    cash_runway: DashboardRunway | None = None


class DashboardComputed(BaseModel):
    runway: DashboardRunway | None = None


class DashboardSummary(BaseModel):
    generated_at: str
    data: DashboardData
    data_quality_flags: list[DataQualityFlag]
    source_updated_at: dict[str, str | None]
    computed: DashboardComputed
    signals: list[DashboardSignal]
    checklist: DashboardChecklist


class OnboardingState(BaseModel):
    # Set when the user finishes or skips the first-run guide; the checklist stays on the home screen.
    dismissed: bool = False
