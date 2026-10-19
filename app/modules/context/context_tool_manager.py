"""Read-only agent tools (PRD §7.2) — business logic over the crud handlers.

Each tool reads a bounded slice of the personal DB and returns structured data plus the
record references and freshness needed for the Context Snapshot. Tools run server-side;
the model never receives connection strings or SQL.
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import Category
from app.modules.context.calendar_scope import calendar_scope
from app.modules.career.context import get_career_records
from app.modules.crud import (
    account_handler,
    app_setting_handler,
    calendar_event_handler,
    career_criterion_handler,
    cashflow_entry_handler,
    fx_rate_handler,
    goal_handler,
    holding_handler,
    interview_handler,
    job_application_handler,
    liability_handler,
    other_asset_handler,
    personal_memory_handler,
    planned_expense_handler,
    task_handler,
    workout_log_handler,
)
from app.modules.database.model import FinancialTransaction, FxRate, Holding, LocalFinanceCoverage
from app.modules.finance.financial_calculator import financial_calculator
from app.modules.finance.liquidity_policy import account_bucket, account_spendable, holding_bucket
from app.modules.context.derived import calendar_conflicts, fx_table_from_rates
from app.modules.context.records import as_aware, clip_text, iso_or_none, latest_of, quality_flag, record_ref
from app.modules.context.types import ToolContext, ToolResult
from app.modules.finance.types import FxTable, Position, q2
from app.modules.context.portfolio_tools import (
    get_monthly_asset_history, sheets_enabled, sheets_accounts, sheets_portfolio, sheets_market,
)

STALE_PRICE_DAYS = 3
STALE_BALANCE_DAYS = 45


def base_currency(session: Session) -> str:
    value = app_setting_handler.get_value(session, "base_currency") or {}
    return value.get("currency", "KRW")


def fx_table(session: Session) -> tuple[FxTable, list[FxRate]]:
    return fx_table_from_rates(base_currency(session), fx_rate_handler.get_latest_first(session))


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
        if h.price_as_of is None or ctx.now - as_aware(h.price_as_of) > timedelta(days=STALE_PRICE_DAYS):
            flags.append(quality_flag("stale_price", Category.INVESTMENT, h.symbol))
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
        flags.append(quality_flag("no_accounts", Category.FINANCIAL))
    if not liabilities:
        flags.append(quality_flag("no_liabilities_recorded", Category.FINANCIAL, "debt may be zero or simply not entered"))
    for a in accounts:
        if (ctx.today - a.balance_as_of).days > STALE_BALANCE_DAYS:
            flags.append(quality_flag("stale_balance", Category.FINANCIAL, f"{a.name} as of {a.balance_as_of}"))

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
        flags.append(quality_flag("investment_excluded_from_net_worth", Category.FINANCIAL,
                           "investment category not shared; net worth omits securities"))
    debts = [Position(f"liabilities:{l.id}", l.name, l.balance, l.currency) for l in liabilities]
    worth = financial_calculator.net_worth(fx, assets, debts)
    if worth.excluded:
        flags.append(quality_flag("net_worth_incomplete", Category.FINANCIAL,
                           ", ".join(f"{e['label']}({e['reason']})" for e in worth.excluded)))

    worth_data = worth.as_dict()
    coverage = s.get(LocalFinanceCoverage, 1)
    # No accounts is an unknown scope until the user explicitly confirms cash coverage.
    if not any(account_bucket(a.kind) == "cash" for a in accounts) and (coverage is None or "cash" not in coverage.kinds):
        worth_data.update(spendable_liquidity=None, spendable_liquidity_complete=False,
                          cash_and_equivalents=None)
        flags.append(quality_flag("spendable_liquidity_unknown", Category.FINANCIAL,
                                  "생활비로 사용할 현금 계좌와 현금 기록 범위를 확인하세요."))
    from app.modules.portfolio.local_portfolio import portfolio as local_portfolio
    allowed_kinds = ("cash", "liability", "other", "holding") if Category.INVESTMENT in ctx.allowed else ("cash", "liability", "other")
    valuation = local_portfolio(s, kinds=allowed_kinds)
    if fx.base == "KRW":
        worth_data.update(total_assets=valuation["total_assets"] if Category.INVESTMENT in ctx.allowed else None,
                          total_liabilities=valuation["total_liabilities"],
                          net_worth=valuation["net_worth"] if Category.INVESTMENT in ctx.allowed else None,
                          complete=valuation["complete"] and Category.INVESTMENT in ctx.allowed)
    else:
        worth_data.update(total_assets=None,total_liabilities=None,net_worth=None,complete=False)
        flags.append(quality_flag("valuation_base_unavailable", Category.FINANCIAL, "Canonical local valuation is recorded in KRW"))
    if not worth_data["complete"]:
        flags.append(quality_flag("net_worth_incomplete", Category.FINANCIAL, "; ".join(valuation["issues"])))
    # Preserve the separate eligible-cash calculation used by runway; these
    # aggregate totals never make securities spendable.
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
            "computed": {"net_worth": worth_data, "computed_by": "backend_local_valuation"},
            "fx_rates_used": [
                {"pair": f"{r.base}/{r.quote}", "rate": str(r.rate), "as_of": r.as_of.isoformat()} for r in fx_rows
            ],
        },
        refs=[record_ref("accounts", a) for a in accounts] + [record_ref("other_assets", o) for o in others]
        + [record_ref("liabilities", l) for l in liabilities] + [record_ref("holdings", h) for h in holding_rows],
        source_updated_at=latest_of(*(r.updated_at for r in [*accounts, *others, *liabilities, *holding_rows])),
        flags=flags,
    )


def get_cashflow_summary(ctx: ToolContext) -> ToolResult:
    s = ctx.session
    zone = ZoneInfo(settings.timezone)
    today = as_aware(ctx.now).astimezone(zone).date()
    since = date(today.year - 1, today.month, 1)
    entries = [e for e in cashflow_entry_handler.get_since(s, since) if e.occurred_on <= today]
    # A reversal may be recorded outside this reporting window. It still removes
    # its original fact, and remains a dependency of this calculation.
    transactions = list(s.scalars(select(FinancialTransaction).where(
        FinancialTransaction.occurred_at >= datetime.combine(since, time.min, zone),
        FinancialTransaction.occurred_at <= ctx.now,
        FinancialTransaction.kind.in_(("income", "dividend", "interest", "expense", "fee", "tax")),
    )))
    reversals = list(s.scalars(select(FinancialTransaction).where(
        FinancialTransaction.reverses_id.in_([t.id for t in transactions]),
        FinancialTransaction.kind == "reversal",
    ))) if transactions else []
    reversed_ids = {r.reverses_id for r in reversals}
    from app.modules.finance.ledger import INCOME
    flows = [(e.occurred_on, e.amount, e.currency, e.kind, e.category or "uncategorized") for e in entries]
    flows += [(as_aware(t.occurred_at).astimezone(zone).date(), Decimal(t.payload["amount"]),
               t.payload["currency"], "income" if t.kind in INCOME else "expense", "uncategorized")
              for t in transactions if t.id not in reversed_ids]
    planned = planned_expense_handler.get_upcoming(s, today)
    base = base_currency(s)
    foreign = [e for e in flows if e[2] != base]
    usable = [e for e in flows if e[2] == base]
    flags = []
    if entries and transactions:
        flags.append(quality_flag("cashflow_mixed_sources", Category.FINANCIAL,
            "기존 수입·지출과 거래 기록을 함께 합산했습니다. 같은 지출을 두 화면에 중복 입력하지 마세요."))
    if foreign:
        flags.append(quality_flag("cashflow_foreign_currency_ignored", Category.FINANCIAL, f"{len(foreign)} entries"))
    expense = financial_calculator.monthly_average(
        [(day, amount) for day, amount, _, kind, _ in usable if kind == "expense"], today)
    income = financial_calculator.monthly_average(
        [(day, amount) for day, amount, _, kind, _ in usable if kind == "income"], today)
    if expense.get("reason") == "insufficient_coverage":
        flags.append(quality_flag("monthly_expense_insufficient_coverage", Category.FINANCIAL,
                           f"recorded {expense['months_with_data']}/{expense['months_considered']} months; "
                           "estimate is an assumption, not an observed average"))
    elif not expense["available"]:
        flags.append(quality_flag("monthly_expense_unknown", Category.FINANCIAL,
                           "ask the user for monthly spending or state an explicit assumption"))

    categories: dict[str, Decimal] = {}
    for _, amount, _, kind, category in usable:
        if kind == "expense":
            categories[category] = categories.get(category, Decimal(0)) + amount
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
        refs=[record_ref("cashflow_entries", e) for e in entries]
        + [{"table": "financial_transactions", "id": t.id, "updated_at": t.recorded_at.isoformat()}
           for t in [*transactions, *reversals]]
        + [{"table": table, "id": t.payload[field]}
           for t in transactions for field, table in (("account_id", "accounts"), ("counterparty_account_id", "accounts"), ("holding_id", "holdings"))
           if t.payload.get(field) is not None]
        + [record_ref("planned_expenses", p) for p in planned],
        source_updated_at=latest_of(*(e.updated_at for e in [*entries, *planned]),
                                    *(t.recorded_at for t in [*transactions, *reversals])),
        flags=flags,
    )


# --- Investment --------------------------------------------------------------------------


def get_portfolio_summary(ctx: ToolContext) -> ToolResult:
    if sheets_enabled(ctx):
        return sheets_portfolio(ctx)
    fx, _ = fx_table(ctx.session)
    positions, holdings, flags = _holding_positions(ctx)
    if not holdings:
        flags.append(quality_flag("no_holdings", Category.INVESTMENT))
    rows, total = [], Decimal(0)
    by_currency: dict[str, Decimal] = {}
    by_class: dict[str, Decimal] = {}
    for pos, h in zip(positions, holdings, strict=True):
        value_base = fx.to_base(pos.value, h.currency) if pos.value is not None else None
        if pos.value is not None and value_base is None:
            flags.append(quality_flag("missing_fx", Category.INVESTMENT, f"{h.currency}/{fx.base}"))
        if value_base is not None:
            total += value_base
            by_currency[h.currency] = by_currency.get(h.currency, Decimal(0)) + value_base
            by_class[h.asset_class] = by_class.get(h.asset_class, Decimal(0)) + value_base
        rows.append({
            "ref": f"holdings:{h.id}", "symbol": h.symbol, "name": h.name, "asset_class": h.asset_class,
            "currency": h.currency, "quantity": str(h.quantity),
            "avg_cost": str(h.avg_cost) if h.avg_cost is not None else None,
            "last_price": str(h.last_price) if h.last_price is not None else None,
            "price_as_of": iso_or_none(h.price_as_of),
            "value_base": str(q2(value_base)) if value_base is not None else None,
        })

    from app.modules.portfolio.local_portfolio import portfolio as local_portfolio
    valuation=local_portfolio(ctx.session,kinds=("holding",))
    complete_total=valuation["investments"] if fx.base=="KRW" else None
    holding_issues=[issue for line in valuation["lines"] for issue in line["issues"]]
    if complete_total is None:
        flags.append(quality_flag("portfolio_incomplete", Category.INVESTMENT, "; ".join(holding_issues) or "Portfolio valuation coverage is unconfirmed"))
    def weights(bucket: dict[str, Decimal]) -> dict[str, str]:
        return {k: str((v / total * 100).quantize(Decimal("0.1"))) for k, v in bucket.items()} if total else {}

    for row in rows:
        row["weight_pct"] = str((Decimal(row["value_base"]) / total * 100).quantize(Decimal("0.1"))) \
            if total and row["value_base"] else None
    if complete_total is None:
        for row in rows:
            row["weight_pct"] = None
    top = sorted((r for r in rows if r["weight_pct"]), key=lambda r: -Decimal(r["weight_pct"]))[:3]
    return ToolResult(
        data={
            "base_currency": fx.base,
            "holdings": rows,
            "computed": {
                "total_value_base": complete_total,
                "recorded_subtotal_base": str(q2(total)),
                "complete": complete_total is not None,
                "weight_by_currency_pct": weights(by_currency) if complete_total is not None else {},
                "weight_by_asset_class_pct": weights(by_class) if complete_total is not None else {},
                "top3_concentration_pct": str(sum((Decimal(r["weight_pct"]) for r in top), Decimal(0))) if complete_total is not None else None,
                "computed_by": "backend",
            },
        },
        refs=[record_ref("holdings", h) for h in holdings],
        source_updated_at=latest_of(*(h.updated_at for h in holdings)),
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
                        "as_of": iso_or_none(h.price_as_of)} for h in holdings],
            "fx": [{"pair": f"{r.base}/{r.quote}", "rate": str(r.rate), "as_of": r.as_of.isoformat()} for r in fx_rows],
        },
        refs=[{"table": "fx_rates", "id": r.id, "updated_at": iso_or_none(r.as_of)} for r in fx_rows],
        source_updated_at=latest_of(*(r.as_of for r in fx_rows), *(h.price_as_of for h in holdings)),
    )


def get_relevant_news(ctx: ToolContext) -> ToolResult:
    # No news provider is wired in v0.2. When one is, wrap items as untrusted content.
    return ToolResult(
        data={"items": [], "untrusted_external_content": True},
        flags=[quality_flag("news_source_not_configured", Category.INVESTMENT)],
    )


# --- Career ------------------------------------------------------------------------------

ACTIVE_STATUSES = ("interested", "applied", "screening", "interviewing", "offer")


def get_job_applications(ctx: ToolContext) -> ToolResult:
    s = ctx.session
    apps = job_application_handler.get_by_statuses(s, ACTIVE_STATUSES)
    criteria = career_criterion_handler.get_by_weight(s)
    flags = []
    if not apps:
        flags.append(quality_flag("no_active_applications", Category.CAREER))
    if not criteria:
        flags.append(quality_flag("no_career_criteria", Category.CAREER, "ask the user which criteria matter"))
    return ToolResult(
        data={
            "applications": [
                {"ref": f"job_applications:{a.id}", "company": a.company, "role": a.role, "status": a.status,
                 "applied_on": iso_or_none(a.applied_on), "compensation_note": a.compensation_note,
                 "next_step": a.next_step, "jd_excerpt": clip_text(a.jd_text), "notes": clip_text(a.notes, 500)}
                for a in apps
            ],
            "evaluation_criteria": [
                {"name": c.name, "weight": c.weight, "description": c.description} for c in criteria
            ],
            "policy": "no numeric offer probabilities without verifiable statistics",
        },
        refs=[record_ref("job_applications", a) for a in apps] + [record_ref("career_criteria", c) for c in criteria],
        source_updated_at=latest_of(*(r.updated_at for r in [*apps, *criteria])),
        flags=flags,
    )


def get_interview_schedule(ctx: ToolContext, days: int = 30) -> ToolResult:
    rows = interview_handler.get_with_application_between(
        ctx.session, ctx.now, ctx.now + timedelta(days=days))
    return ToolResult(
        data={
            "window_days": days,
            "interviews": [
                {"ref": f"interviews:{i.id}", "company": a.company, "role": a.role, "stage": i.stage,
                 "starts_at": iso_or_none(i.starts_at), "ends_at": iso_or_none(i.ends_at), "location": i.location,
                 "prep_notes": clip_text(i.prep_notes, 500)}
                for i, a in rows
            ],
        },
        refs=[record_ref("interviews", i) for i, _ in rows],
        source_updated_at=latest_of(*(i.updated_at for i, _ in rows)),
        flags=[] if rows else [quality_flag("no_upcoming_interviews", Category.CAREER)],
    )


# --- Calendar ----------------------------------------------------------------------------


def get_calendar_events(ctx: ToolContext, days: int = 14) -> ToolResult:
    # Day/week/month boundaries are the user's local midnights, not UTC ones.
    scope = calendar_scope(ctx.query, ctx.now.astimezone(ZoneInfo(settings.timezone)), days)
    events = calendar_event_handler.get_between(ctx.session, scope.start, scope.end)
    flags = [] if events else [quality_flag("no_events_in_window", Category.CALENDAR)]
    if scope.status == "unresolved":
        flags.append(quality_flag("calendar_time_scope_unresolved", Category.CALENDAR,
                           "requested dates could not be resolved; events cover only the reported default window"))
    return ToolResult(
        data={
            "window_days": (scope.end - scope.start).total_seconds() / 86400,
            "window": scope.as_dict(),
            "now": ctx.now.isoformat(),
            "events": [
                {"ref": f"calendar_events:{e.id}", "title": e.title, "kind": e.kind, "starts_at": iso_or_none(e.starts_at),
                 "ends_at": iso_or_none(e.ends_at), "all_day": e.all_day, "location": e.location}
                for e in events
            ],
            "conflicts": calendar_conflicts(events),
            "computed_by": "backend",
        },
        refs=[record_ref("calendar_events", e) for e in events],
        source_updated_at=latest_of(*(e.updated_at for e in events)),
        flags=flags,
    )


def get_tasks(ctx: ToolContext) -> ToolResult:
    tasks = task_handler.get_open(ctx.session)
    return ToolResult(
        data={"open_tasks": [
            {"ref": f"tasks:{t.id}", "title": t.title, "status": t.status, "priority": t.priority,
             "due_on": iso_or_none(t.due_on), "estimate_minutes": t.estimate_minutes,
             "overdue": bool(t.due_on and t.due_on < ctx.today), "goal_ref": f"goals:{t.goal_id}" if t.goal_id else None}
            for t in tasks
        ]},
        refs=[record_ref("tasks", t) for t in tasks],
        source_updated_at=latest_of(*(t.updated_at for t in tasks)),
    )


# --- Goals / Health / Profile ------------------------------------------------------------


def get_goals(ctx: ToolContext) -> ToolResult:
    goals = goal_handler.get_active(ctx.session)
    rows = []
    for g in goals:
        rows.append({"ref": f"goals:{g.id}", "title": g.title, "category": g.category, "horizon": g.horizon,
                     "target_value": g.target_value, "current_value": g.current_value,
                     "unit": g.unit, "target_date": iso_or_none(g.target_date)})
    return ToolResult(
        data={"active_goals": rows},
        refs=[record_ref("goals", g) for g in goals],
        source_updated_at=latest_of(*(g.updated_at for g in goals)),
        flags=[] if goals else [quality_flag("no_goals", Category.GOALS)],
    )


def get_health_summary(ctx: ToolContext, days: int = 28) -> ToolResult:
    logs = workout_log_handler.get_since(ctx.session, ctx.today - timedelta(days=days))
    total = sum(l.duration_minutes for l in logs)
    return ToolResult(
        data={
            "window_days": days,
            "sessions": len(logs),
            "total_minutes": total,
            "last_session_on": iso_or_none(logs[-1].performed_on) if logs else None,
            "recent": [{"ref": f"workout_logs:{l.id}", "on": l.performed_on.isoformat(), "activity": l.activity,
                        "minutes": l.duration_minutes, "intensity": l.intensity} for l in logs[-10:]],
        },
        refs=[record_ref("workout_logs", l) for l in logs],
        source_updated_at=latest_of(*(l.updated_at for l in logs)),
        flags=[] if logs else [quality_flag("no_workout_logs", Category.HEALTH)],
    )


def get_profile(ctx: ToolContext) -> ToolResult:
    from app.modules.context.memory_selection import relevant_memories
    import re
    from datetime import datetime
    historical_date = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", ctx.query)
    memory_at = ctx.now
    if historical_date:
        try:
            from zoneinfo import ZoneInfo
            from app.config import settings
            memory_at = datetime.fromisoformat(historical_date.group(1)).replace(tzinfo=ZoneInfo(settings.timezone))
        except ValueError:
            pass
    memories = relevant_memories(ctx.session, ctx.query, ctx.allowed, memory_at)
    return ToolResult(
        data={"confirmed_memories": [{"ref": f"personal_memories:{m.id}",
                "revision_id": revision.id if revision else None,
                "kind": (revision or m).kind, "content": (revision or m).content,
                "valid_from": iso_or_none(revision.valid_from) if revision else None,
                "valid_until": iso_or_none(revision.valid_until) if revision else None}
                                     for m, revision in memories]},
        refs=[{"table": "memory_revisions" if revision else "personal_memories",
               "id": revision.id if revision else m.id,
               "updated_at": iso_or_none((revision or m).confirmed_at)} for m, revision in memories],
        source_updated_at=latest_of(*((revision or m).confirmed_at for m, revision in memories)),
    )


Tool = Callable[[ToolContext], ToolResult]

# Which read-only tools serve each context category.
CATEGORY_TOOLS: dict[Category, tuple[tuple[str, Tool], ...]] = {
    Category.FINANCIAL: (("get_accounts_summary", get_accounts_summary), ("get_cashflow_summary", get_cashflow_summary),
                         ("get_monthly_asset_history", get_monthly_asset_history)),
    Category.INVESTMENT: (("get_portfolio_summary", get_portfolio_summary), ("get_market_data", get_market_data),
                          ("get_relevant_news", get_relevant_news)),
    Category.CAREER: (("get_job_applications", get_job_applications), ("get_interview_schedule", get_interview_schedule),
                      ("get_career_records", get_career_records)),
    Category.CALENDAR: (("get_calendar_events", get_calendar_events), ("get_tasks", get_tasks)),
    Category.HEALTH: (("get_health_summary", get_health_summary),),
    Category.GOALS: (("get_goals", get_goals),),
    Category.PROFILE: (("get_profile", get_profile),),
}
