"""Read-only agent tools (PRD §7.2) — business logic over the crud handlers.

Each tool reads a bounded slice of the personal DB and returns structured data plus the
record references and freshness needed for the Context Snapshot. Tools run server-side;
the model never receives connection strings or SQL.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import Category
from app.modules.context.calendar_scope import calendar_scope
from app.modules.crud.advisor_handler import personal_memory_handler
from app.modules.crud.app_setting_handler import app_setting_handler
from app.modules.crud.career_handler import career_criterion_handler, interview_handler, job_application_handler
from app.modules.crud.finance_handler import (
    account_handler,
    cashflow_entry_handler,
    fx_rate_handler,
    holding_handler,
    liability_handler,
    other_asset_handler,
    planned_expense_handler,
)
from app.modules.crud.planning_handler import calendar_event_handler, goal_handler, task_handler, workout_log_handler
from app.modules.database.model import CalendarEvent, FxRate, Holding
from app.modules.finance.financial_calculator import financial_calculator
from app.modules.finance.liquidity_policy import account_bucket, account_spendable, holding_bucket
from app.modules.context.types import DataQualityFlag, RecordRef, ToolContext, ToolResult
from app.modules.finance.types import FxTable, Position, q2
from app.modules.context.portfolio_tools import (
    get_monthly_asset_history, sheets_enabled, sheets_accounts, sheets_portfolio, sheets_market,
)

STALE_PRICE_DAYS = 3
STALE_BALANCE_DAYS = 45
TEXT_LIMIT = 1500


def _ref(table: str, row) -> RecordRef:
    updated = getattr(row, "updated_at", None) or getattr(row, "as_of", None)
    return {"table": table, "id": row.id, "updated_at": _iso(updated)}


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _latest(*values) -> datetime | None:
    present = [_aware(v) for v in values if v is not None]
    return max(present) if present else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _clip(text: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + " …[truncated]"


def _flag(code: str, category: Category, detail: str | None = None) -> DataQualityFlag:
    return {"code": code, "category": category.value, **({"detail": detail} if detail else {})}


def base_currency(session: Session) -> str:
    value = app_setting_handler.get_value(session, "base_currency") or {}
    return value.get("currency", "KRW")


def fx_table(session: Session) -> tuple[FxTable, list[FxRate]]:
    base = base_currency(session)
    table = FxTable(base=base)
    used: list[FxRate] = []
    for rate in fx_rate_handler.get_latest_first(session):
        if rate.quote == base and rate.base not in table.rates:
            table.rates[rate.base] = rate.rate
            used.append(rate)
        elif rate.base == base and rate.quote not in table.rates and rate.rate:
            table.rates[rate.quote] = Decimal(1) / rate.rate
            used.append(rate)
    return table, used


def _holding_positions(ctx: ToolContext) -> tuple[list[Position], list[Holding], list[dict]]:
    """Holdings at market value. Never spendable: selling them is the user's decision, not an assumption."""
    holdings = holding_handler.get_all(ctx.session)
    account_kinds = {a.id: a.kind for a in account_handler.get_all(ctx.session)}
    positions, flags = [], []
    for h in holdings:
        bucket = holding_bucket(account_kinds.get(h.account_id))
        if h.last_price is None:
            positions.append(Position(f"holdings:{h.id}", h.symbol, None, h.currency, bucket,
                                      unavailable_reason="no_price"))
            continue
        positions.append(Position(f"holdings:{h.id}", h.symbol, h.quantity * h.last_price, h.currency, bucket))
        if h.price_as_of is None or ctx.now - _aware(h.price_as_of) > timedelta(days=STALE_PRICE_DAYS):
            flags.append(_flag("stale_price", Category.INVESTMENT, h.symbol))
    return positions, holdings, flags


# --- Financial ---------------------------------------------------------------------------


def get_accounts_summary(ctx: ToolContext) -> ToolResult:
    if sheets_enabled(ctx):
        return sheets_accounts(ctx)
    s = ctx.session
    accounts = account_handler.get_all(s)
    others = other_asset_handler.get_all(s)
    liabilities = liability_handler.get_all(s)
    fx, fx_rows = fx_table(s)
    flags: list[dict] = []
    if not accounts:
        flags.append(_flag("no_accounts", Category.FINANCIAL))
    if not liabilities:
        flags.append(_flag("no_liabilities_recorded", Category.FINANCIAL, "debt may be zero or simply not entered"))
    for a in accounts:
        if (ctx.today - a.balance_as_of).days > STALE_BALANCE_DAYS:
            flags.append(_flag("stale_balance", Category.FINANCIAL, f"{a.name} as of {a.balance_as_of}"))

    assets = [Position(f"accounts:{a.id}", a.name, a.balance, a.currency, account_bucket(a.kind),
                       account_spendable(a.kind, a.is_liquid)) for a in accounts]
    # Other assets (property, vehicles, severance estimates) are never spendable, whatever is_liquid says.
    assets += [Position(f"other_assets:{o.id}", o.name, o.value, o.currency, "other") for o in others]
    holding_rows: list[Holding] = []
    if Category.INVESTMENT in ctx.allowed:
        holding_positions, holding_rows, holding_flags = _holding_positions(ctx)
        assets += holding_positions
        flags += holding_flags
    else:
        flags.append(_flag("investment_excluded_from_net_worth", Category.FINANCIAL,
                           "investment category not shared; net worth omits securities"))
    debts = [Position(f"liabilities:{l.id}", l.name, l.balance, l.currency) for l in liabilities]
    worth = financial_calculator.net_worth(fx, assets, debts)
    if worth.excluded:
        flags.append(_flag("net_worth_incomplete", Category.FINANCIAL,
                           ", ".join(f"{e['label']}({e['reason']})" for e in worth.excluded)))

    return ToolResult(
        data={
            "accounts": [
                {"ref": f"accounts:{a.id}", "name": a.name, "institution": a.institution, "kind": a.kind,
                 "currency": a.currency, "balance": str(a.balance), "as_of": a.balance_as_of.isoformat(),
                 "liquid": a.is_liquid, "liquidity_bucket": account_bucket(a.kind),
                 "spendable": account_spendable(a.kind, a.is_liquid)}
                for a in accounts
            ],
            "other_assets": [
                {"ref": f"other_assets:{o.id}", "name": o.name, "kind": o.kind, "currency": o.currency,
                 "value": str(o.value), "as_of": o.value_as_of.isoformat(), "liquid": o.is_liquid}
                for o in others
            ],
            "liabilities": [
                {"ref": f"liabilities:{l.id}", "name": l.name, "kind": l.kind, "currency": l.currency,
                 "balance": str(l.balance), "interest_rate": str(l.interest_rate) if l.interest_rate is not None else None,
                 "monthly_payment": str(l.monthly_payment) if l.monthly_payment is not None else None,
                 "as_of": l.balance_as_of.isoformat()}
                for l in liabilities
            ],
            "computed": {"net_worth": worth.as_dict(), "computed_by": "FinancialCalculator"},
            "fx_rates_used": [
                {"pair": f"{r.base}/{r.quote}", "rate": str(r.rate), "as_of": r.as_of.isoformat()} for r in fx_rows
            ],
        },
        refs=[_ref("accounts", a) for a in accounts] + [_ref("other_assets", o) for o in others]
        + [_ref("liabilities", l) for l in liabilities] + [_ref("holdings", h) for h in holding_rows],
        source_updated_at=_latest(*(r.updated_at for r in [*accounts, *others, *liabilities, *holding_rows])),
        flags=flags,
    )


def get_cashflow_summary(ctx: ToolContext) -> ToolResult:
    s = ctx.session
    since = date(ctx.today.year - 1, ctx.today.month, 1)
    entries = cashflow_entry_handler.get_since(s, since)
    planned = planned_expense_handler.get_upcoming(s, ctx.today)
    base = base_currency(s)
    foreign = [e for e in entries if e.currency != base]
    usable = [e for e in entries if e.currency == base]
    flags = []
    if foreign:
        flags.append(_flag("cashflow_foreign_currency_ignored", Category.FINANCIAL, f"{len(foreign)} entries"))
    expense = financial_calculator.monthly_average(
        [(e.occurred_on, e.amount) for e in usable if e.kind == "expense"], ctx.today)
    income = financial_calculator.monthly_average(
        [(e.occurred_on, e.amount) for e in usable if e.kind == "income"], ctx.today)
    if expense.get("reason") == "insufficient_coverage":
        flags.append(_flag("monthly_expense_insufficient_coverage", Category.FINANCIAL,
                           f"recorded {expense['months_with_data']}/{expense['months_considered']} months; "
                           "estimate is an assumption, not an observed average"))
    elif not expense["available"]:
        flags.append(_flag("monthly_expense_unknown", Category.FINANCIAL,
                           "ask the user for monthly spending or state an explicit assumption"))

    categories: dict[str, Decimal] = {}
    for e in usable:
        if e.kind == "expense":
            categories[e.category or "uncategorized"] = categories.get(e.category or "uncategorized", Decimal(0)) + e.amount
    return ToolResult(
        data={
            "currency": base,
            "monthly_expense": expense,
            "monthly_income": income,
            "expense_by_category_12m": {k: str(q2(v)) for k, v in sorted(categories.items(), key=lambda kv: -kv[1])[:10]},
            "planned_expenses": [
                {"ref": f"planned_expenses:{p.id}", "name": p.name, "amount": str(p.amount), "currency": p.currency,
                 "due_on": p.due_on.isoformat()}
                for p in planned
            ],
            "computed_by": "FinancialCalculator",
        },
        refs=[{"table": "cashflow_entries", "count": len(entries), "since": since.isoformat()}]
        + [_ref("planned_expenses", p) for p in planned],
        source_updated_at=_latest(*(e.updated_at for e in [*entries, *planned])),
        flags=flags,
    )


# --- Investment --------------------------------------------------------------------------


def get_portfolio_summary(ctx: ToolContext) -> ToolResult:
    if sheets_enabled(ctx):
        return sheets_portfolio(ctx)
    fx, _ = fx_table(ctx.session)
    positions, holdings, flags = _holding_positions(ctx)
    if not holdings:
        flags.append(_flag("no_holdings", Category.INVESTMENT))
    rows, total = [], Decimal(0)
    by_currency: dict[str, Decimal] = {}
    by_class: dict[str, Decimal] = {}
    for pos, h in zip(positions, holdings, strict=True):
        value_base = fx.to_base(pos.value, h.currency) if pos.value is not None else None
        if pos.value is not None and value_base is None:
            flags.append(_flag("missing_fx", Category.INVESTMENT, f"{h.currency}/{fx.base}"))
        if value_base is not None:
            total += value_base
            by_currency[h.currency] = by_currency.get(h.currency, Decimal(0)) + value_base
            by_class[h.asset_class] = by_class.get(h.asset_class, Decimal(0)) + value_base
        rows.append({
            "ref": f"holdings:{h.id}", "symbol": h.symbol, "name": h.name, "asset_class": h.asset_class,
            "currency": h.currency, "quantity": str(h.quantity),
            "avg_cost": str(h.avg_cost) if h.avg_cost is not None else None,
            "last_price": str(h.last_price) if h.last_price is not None else None,
            "price_as_of": _iso(h.price_as_of),
            "value_base": str(q2(value_base)) if value_base is not None else None,
        })

    def weights(bucket: dict[str, Decimal]) -> dict[str, str]:
        return {k: str((v / total * 100).quantize(Decimal("0.1"))) for k, v in bucket.items()} if total else {}

    for row in rows:
        row["weight_pct"] = str((Decimal(row["value_base"]) / total * 100).quantize(Decimal("0.1"))) \
            if total and row["value_base"] else None
    top = sorted((r for r in rows if r["weight_pct"]), key=lambda r: -Decimal(r["weight_pct"]))[:3]
    return ToolResult(
        data={
            "base_currency": fx.base,
            "holdings": rows,
            "computed": {
                "total_value_base": str(q2(total)),
                "weight_by_currency_pct": weights(by_currency),
                "weight_by_asset_class_pct": weights(by_class),
                "top3_concentration_pct": str(sum((Decimal(r["weight_pct"]) for r in top), Decimal(0))),
                "computed_by": "backend",
            },
        },
        refs=[_ref("holdings", h) for h in holdings],
        source_updated_at=_latest(*(h.updated_at for h in holdings)),
        flags=flags,
    )


def get_market_data(ctx: ToolContext) -> ToolResult:
    if sheets_enabled(ctx):
        return sheets_market(ctx)
    _, fx_rows = fx_table(ctx.session)
    holdings = holding_handler.get_priced(ctx.session)
    return ToolResult(
        data={
            "source": "local_db",
            "note": "prices and FX are the last values stored in Personal OS, not live quotes",
            "prices": [{"symbol": h.symbol, "price": str(h.last_price), "currency": h.currency,
                        "as_of": _iso(h.price_as_of)} for h in holdings],
            "fx": [{"pair": f"{r.base}/{r.quote}", "rate": str(r.rate), "as_of": r.as_of.isoformat()} for r in fx_rows],
        },
        refs=[{"table": "fx_rates", "id": r.id, "updated_at": _iso(r.as_of)} for r in fx_rows],
        source_updated_at=_latest(*(r.as_of for r in fx_rows), *(h.price_as_of for h in holdings)),
    )


def get_relevant_news(ctx: ToolContext) -> ToolResult:
    # No news provider is wired in v0.2. When one is, wrap items as untrusted content.
    return ToolResult(
        data={"items": [], "untrusted_external_content": True},
        flags=[_flag("news_source_not_configured", Category.INVESTMENT)],
    )


# --- Career ------------------------------------------------------------------------------

ACTIVE_STATUSES = ("interested", "applied", "screening", "interviewing", "offer")


def get_job_applications(ctx: ToolContext) -> ToolResult:
    s = ctx.session
    apps = job_application_handler.get_by_statuses(s, ACTIVE_STATUSES)
    criteria = career_criterion_handler.get_by_weight(s)
    flags = []
    if not apps:
        flags.append(_flag("no_active_applications", Category.CAREER))
    if not criteria:
        flags.append(_flag("no_career_criteria", Category.CAREER, "ask the user which criteria matter"))
    return ToolResult(
        data={
            "applications": [
                {"ref": f"job_applications:{a.id}", "company": a.company, "role": a.role, "status": a.status,
                 "applied_on": _iso(a.applied_on), "compensation_note": a.compensation_note,
                 "next_step": a.next_step, "jd_excerpt": _clip(a.jd_text), "notes": _clip(a.notes, 500)}
                for a in apps
            ],
            "evaluation_criteria": [
                {"name": c.name, "weight": c.weight, "description": c.description} for c in criteria
            ],
            "policy": "no numeric offer probabilities without verifiable statistics",
        },
        refs=[_ref("job_applications", a) for a in apps] + [_ref("career_criteria", c) for c in criteria],
        source_updated_at=_latest(*(r.updated_at for r in [*apps, *criteria])),
        flags=flags,
    )


def get_interview_schedule(ctx: ToolContext, days: int = 30) -> ToolResult:
    rows = interview_handler.get_with_application_between(
        ctx.session, ctx.now - timedelta(days=1), ctx.now + timedelta(days=days))
    return ToolResult(
        data={
            "window_days": days,
            "interviews": [
                {"ref": f"interviews:{i.id}", "company": a.company, "role": a.role, "stage": i.stage,
                 "starts_at": _iso(i.starts_at), "ends_at": _iso(i.ends_at), "location": i.location,
                 "prep_notes": _clip(i.prep_notes, 500)}
                for i, a in rows
            ],
        },
        refs=[_ref("interviews", i) for i, _ in rows],
        source_updated_at=_latest(*(i.updated_at for i, _ in rows)),
        flags=[] if rows else [_flag("no_upcoming_interviews", Category.CAREER)],
    )


# --- Calendar ----------------------------------------------------------------------------


def get_calendar_events(ctx: ToolContext, days: int = 14) -> ToolResult:
    # Day/week/month boundaries are the user's local midnights, not UTC ones.
    scope = calendar_scope(ctx.query, ctx.now.astimezone(ZoneInfo(settings.timezone)), days)
    events = calendar_event_handler.get_between(ctx.session, scope.start, scope.end)
    flags = [] if events else [_flag("no_events_in_window", Category.CALENDAR)]
    if scope.status == "unresolved":
        flags.append(_flag("calendar_time_scope_unresolved", Category.CALENDAR,
                           "requested dates could not be resolved; events cover only the reported default window"))
    return ToolResult(
        data={
            "window_days": (scope.end - scope.start).total_seconds() / 86400,
            "window": scope.as_dict(),
            "now": ctx.now.isoformat(),
            "events": [
                {"ref": f"calendar_events:{e.id}", "title": e.title, "kind": e.kind, "starts_at": _iso(e.starts_at),
                 "ends_at": _iso(e.ends_at), "location": e.location}
                for e in events
            ],
            "conflicts": _conflicts(events),
            "computed_by": "backend",
        },
        refs=[_ref("calendar_events", e) for e in events],
        source_updated_at=_latest(*(e.updated_at for e in events)),
        flags=flags,
    )


def _conflicts(events: list[CalendarEvent]) -> list[dict]:
    out = []
    for i, a in enumerate(events):
        a_end = a.ends_at or a.starts_at
        for b in events[i + 1:]:
            if b.starts_at >= a_end:
                break
            out.append({"a": f"calendar_events:{a.id}", "b": f"calendar_events:{b.id}"})
    return out


def get_tasks(ctx: ToolContext) -> ToolResult:
    tasks = task_handler.get_open(ctx.session)
    return ToolResult(
        data={"open_tasks": [
            {"ref": f"tasks:{t.id}", "title": t.title, "status": t.status, "priority": t.priority,
             "due_on": _iso(t.due_on), "estimate_minutes": t.estimate_minutes,
             "overdue": bool(t.due_on and t.due_on < ctx.today), "goal_ref": f"goals:{t.goal_id}" if t.goal_id else None}
            for t in tasks
        ]},
        refs=[_ref("tasks", t) for t in tasks],
        source_updated_at=_latest(*(t.updated_at for t in tasks)),
    )


# --- Goals / Health / Profile ------------------------------------------------------------


def get_goals(ctx: ToolContext) -> ToolResult:
    goals = goal_handler.get_active(ctx.session)
    rows = []
    for g in goals:
        progress = None
        if g.target_value and g.current_value is not None:
            progress = str((g.current_value / g.target_value * 100).quantize(Decimal("0.1")))
        rows.append({"ref": f"goals:{g.id}", "title": g.title, "category": g.category, "horizon": g.horizon,
                     "target_value": str(g.target_value) if g.target_value is not None else None,
                     "current_value": str(g.current_value) if g.current_value is not None else None,
                     "unit": g.unit, "target_date": _iso(g.target_date), "progress_pct": progress})
    return ToolResult(
        data={"active_goals": rows},
        refs=[_ref("goals", g) for g in goals],
        source_updated_at=_latest(*(g.updated_at for g in goals)),
        flags=[] if goals else [_flag("no_goals", Category.GOALS)],
    )


def get_health_summary(ctx: ToolContext, days: int = 28) -> ToolResult:
    logs = workout_log_handler.get_since(ctx.session, ctx.today - timedelta(days=days))
    total = sum(l.duration_minutes for l in logs)
    return ToolResult(
        data={
            "window_days": days,
            "sessions": len(logs),
            "total_minutes": total,
            "last_session_on": _iso(logs[-1].performed_on) if logs else None,
            "recent": [{"ref": f"workout_logs:{l.id}", "on": l.performed_on.isoformat(), "activity": l.activity,
                        "minutes": l.duration_minutes, "intensity": l.intensity} for l in logs[-10:]],
        },
        refs=[_ref("workout_logs", l) for l in logs],
        source_updated_at=_latest(*(l.updated_at for l in logs)),
        flags=[] if logs else [_flag("no_workout_logs", Category.HEALTH)],
    )


def get_profile(ctx: ToolContext) -> ToolResult:
    memories = personal_memory_handler.get_by_status(ctx.session, "confirmed")
    return ToolResult(
        data={"confirmed_memories": [{"ref": f"personal_memories:{m.id}", "kind": m.kind, "content": m.content}
                                     for m in memories]},
        refs=[{"table": "personal_memories", "id": m.id, "updated_at": _iso(m.confirmed_at)} for m in memories],
        source_updated_at=_latest(*(m.confirmed_at for m in memories)),
    )


def derive_cash_runway(data: dict) -> dict | None:
    """Runway from the accounts and cashflow sections; None unless both were collected."""
    accounts, cashflow = data.get("get_accounts_summary"), data.get("get_cashflow_summary")
    if accounts is None or cashflow is None:
        return None
    worth = accounts.get("computed", {}).get("net_worth")
    return {**financial_calculator.cash_runway(worth, cashflow.get("monthly_expense")),
            "computed_by": "FinancialCalculator"}


Tool = Callable[[ToolContext], ToolResult]

# Which read-only tools serve each context category.
CATEGORY_TOOLS: dict[Category, tuple[tuple[str, Tool], ...]] = {
    Category.FINANCIAL: (("get_accounts_summary", get_accounts_summary), ("get_cashflow_summary", get_cashflow_summary),
                         ("get_monthly_asset_history", get_monthly_asset_history)),
    Category.INVESTMENT: (("get_portfolio_summary", get_portfolio_summary), ("get_market_data", get_market_data),
                          ("get_relevant_news", get_relevant_news)),
    Category.CAREER: (("get_job_applications", get_job_applications), ("get_interview_schedule", get_interview_schedule)),
    Category.CALENDAR: (("get_calendar_events", get_calendar_events), ("get_tasks", get_tasks)),
    Category.HEALTH: (("get_health_summary", get_health_summary),),
    Category.GOALS: (("get_goals", get_goals),),
    Category.PROFILE: (("get_profile", get_profile),),
}
