"""Proactive briefings: Hermes cron, with the deterministic pre-check deciding to wake the model.

Each due occurrence first refreshes local signals in the inbox. Without signals the tick
ends silently. With signals and the user's explicit model opt-in, a consultation run is
queued in a fresh `origin=schedule` conversation (no earlier briefing history is replayed)
under the authority pinned when the user enabled it. Any change to that authority pauses
the schedule; nothing is silently re-authorized or sent with another account or model.
Missed occurrences are not replayed one by one: only the latest due occurrence runs.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.agent import signals as briefing_signals
from app.modules.agent.inbox_manager import notify
from app.modules.database.model import AdvisorConversation
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import JobSchedule

KINDS = {"daily_briefing": "day", "weekly_briefing": "week"}
# These tools provide the evidence behind each dashboard signal. Local-only rows
# block the same aggregate here as in the consultation context builder.
SIGNAL_TOOLS = {
    "expenses": ("get_cashflow_summary",), "goals": ("get_goals",),
    "interviews": ("get_interview_schedule",), "interviews_soon": ("get_interview_schedule",),
    "exercise": ("get_health_summary",),
    "stale_data": ("get_accounts_summary", "get_portfolio_summary", "get_market_data"),
}


def occurrences(now: datetime, local_time: str, cadence: str, weekday: int | None, timezone: str):
    """(latest occurrence at or before now, next occurrence after now), as UTC-aware datetimes."""
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    hour, minute = (int(part) for part in local_time.split(":"))
    candidate = datetime.combine(local.date(), time(hour, minute), zone)
    step = timedelta(days=7 if cadence == "week" else 1)
    if cadence == "week":
        candidate -= timedelta(days=(candidate.weekday() - (weekday or 0)) % 7)
    if candidate > local:
        candidate -= step
    # Re-anchor through the wall clock so DST transitions keep the user's local time.
    following = datetime.combine((candidate + step).date(), time(hour, minute), zone)
    return candidate, following


def first_run_at(now: datetime, schedule: JobSchedule) -> datetime:
    return occurrences(now, schedule.local_time, KINDS[schedule.kind], schedule.options.get("weekday"),
                       settings.timezone)[1]


def due(session: Session, now: datetime | None = None) -> None:
    now = now or utcnow()
    for schedule in list(session.scalars(select(JobSchedule).where(
            JobSchedule.kind.in_(list(KINDS)), JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now))):
        latest, following = occurrences(now, schedule.local_time, KINDS[schedule.kind],
                                         schedule.options.get("weekday"), settings.timezone)
        # One atomic advance per tick; replaying the tick after a crash re-runs nothing twice.
        changed = session.execute(update(JobSchedule).where(
            JobSchedule.id == schedule.id, JobSchedule.enabled.is_(True),
            JobSchedule.next_run_at == schedule.next_run_at).values(next_run_at=following))
        if changed.rowcount != 1:
            continue
        key = f"briefing:{schedule.id}:{latest.date().isoformat()}"
        try:
            with session.begin_nested():
                run(session, schedule, latest.date(), key=key, now=now)
        except Exception as exc:
            # The occurrence stays consumed: a broken briefing must not retry every tick.
            notify(session, "job_failed", f"{schedule.name}을(를) 준비하지 못했습니다", f"briefing-failed:{key}",
                   summary=f"오류 종류: {type(exc).__name__}. 다음 예약 시각에 다시 시도합니다.",
                   severity="warning", links={"schedule_id": schedule.id})


def run(session: Session, schedule: JobSchedule, local_date: date, *, key: str, now: datetime | None = None) -> dict:
    """Caller commits. Returns what happened, for run-now responses and tests."""
    now = now or utcnow()
    found = briefing_signals.collect(session, now)
    if not found:
        return {"state": "silent"}
    lines = [f"- {signal['title']}: {signal['count']}건" for signal in found]
    notify(session, "signal", f"{schedule.name}: 확인할 항목 {sum(s['count'] for s in found)}건", f"signals:{key}",
           summary="\n".join(lines), links={"signals": found, "schedule_id": schedule.id})
    if not schedule.options.get("llm_enabled"):
        return {"state": "signals", "signals": found}
    shared_signals = _shared_signals(session, schedule, found)
    categories = sorted({str(c) for signal in shared_signals
                         for c in briefing_signals.CATEGORIES[signal["kind"]]})
    if not categories:
        return {"state": "signals", "signals": found, "model": "no_shared_category"}
    if not _authorized(session, schedule):
        return {"state": "paused", "signals": found}
    if session.scalar(select(AdvisorRun.id).where(AdvisorRun.request_id == key).limit(1)):
        return {"state": "queued", "signals": found}
    from app.modules.advisor.runtime.persistence import RunRepository
    from app.schema.advisor_runtime_schema import RunCreate
    conversation = AdvisorConversation(title=f"{schedule.name} {local_date.isoformat()}"[:200], origin="schedule")
    session.add(conversation)
    session.flush()
    body = RunCreate(request_id=key, message=_message(), categories=categories,
                     playbook_ids=list(schedule.options.get("playbook_ids") or [])[:2], document_search=False)
    created = RunRepository(session).create(conversation.id, body)
    auth = schedule.authorization
    created.provider, created.model, created.account_binding = auth["provider"], schedule.options.get("model"), auth["account_binding"]
    created.authorization = auth
    created.runtime_metadata = {**(created.runtime_metadata or {}), "single_response": False, "schedule_id": schedule.id,
                                "schedule_options": deepcopy(schedule.options), "signal_categories": categories,
                                "signal_kinds": sorted({signal["kind"] for signal in shared_signals})}
    notify(session, "briefing_ready", f"{schedule.name}을(를) 준비하고 있습니다", f"briefing:{key}",
           summary="상담 화면에서 진행 상황과 결과를 볼 수 있습니다. 제안은 승인하기 전에는 적용되지 않습니다.",
           links={"conversation_id": conversation.id, "run_id": created.id, "schedule_id": schedule.id})
    return {"state": "queued", "signals": found, "conversation_id": conversation.id, "run_id": created.id}


def _shared_signals(session: Session, schedule: JobSchedule, signals: list[dict]) -> list[dict]:
    from app.enums.context_category import ALL_CATEGORIES
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.context.record_privacy import tool_blocked
    allowed = {str(c) for c in schedule.options.get("categories") or ALL_CATEGORIES}
    allowed -= {str(c) for c in privacy_manager.get_excluded(session)}
    return [signal for signal in signals
            if (required := briefing_signals.CATEGORIES.get(signal["kind"], set()))
            and {str(c) for c in required} <= allowed
            and signal["kind"] in SIGNAL_TOOLS
            and not any(tool_blocked(session, tool) for tool in SIGNAL_TOOLS[signal["kind"]])]


def require_run_authorized(session: Session, run: AdvisorRun) -> None:
    """Revalidate schedule consent at every model boundary, including queued old runs."""
    metadata = run.runtime_metadata or {}
    schedule_id = metadata.get("schedule_id")
    if not schedule_id:
        return
    schedule = session.get(JobSchedule, schedule_id, populate_existing=True)
    kinds = metadata.get("signal_kinds") or []
    shared = _shared_signals(session, schedule, [{"kind": kind} for kind in kinds]) if schedule else []
    current_categories = sorted({str(c) for signal in shared for c in briefing_signals.CATEGORIES[signal["kind"]]})
    if (schedule is None or schedule.kind not in KINDS or not schedule.enabled
            or not schedule.options.get("llm_enabled") or not schedule.authorization
            or schedule.authorization != run.authorization
            or metadata.get("schedule_options") != schedule.options
            or schedule.options.get("model") != run.model
            or not kinds or len(shared) != len(kinds)
            or metadata.get("signal_categories") != current_categories):
        from app.modules.llm.errors import AdvisorError
        raise AdvisorError("브리핑 예약의 실행 동의나 공유 범위가 변경되었습니다. 예약 설정을 다시 확인하세요.",
                           provider_code="run_authorization_changed")


def _authorized(session: Session, schedule: JobSchedule) -> bool:
    from app.modules.llm import run_policy
    try:
        current = run_policy.capture(session)
    except Exception:
        current = None
    if schedule.authorization and current == schedule.authorization and schedule.options.get("model"):
        return True
    schedule.enabled, schedule.paused_reason = False, "authorization_changed"
    notify(session, "schedule_paused", f"{schedule.name} 예약 상담을 멈췄습니다",
           f"schedule-paused:{schedule.id}:{utcnow().date().isoformat()}",
           summary="앱 잠금, 연결 계정, 모델 또는 전송 정책 확인이 바뀌었습니다. 설정에서 확인한 뒤 다시 켜면 그때의 연결로 실행합니다.",
           severity="warning", links={"schedule_id": schedule.id})
    return False


def _message() -> str:
    # Dashboard predicates stay local. The fresh, source-checked Context Package
    # is the only place model-facing facts may come from, including after a delay.
    return ("예약된 브리핑입니다. 공유가 허용된 현재 기록을 확인해 짧게 정리하고, 오늘 할 일을 우선순위대로 제안하세요. "
            "확인할 근거가 없는 항목은 없다고 밝히고, 실제 변경은 승인 대기 제안으로만 만드세요.")


def after_run(session: Session, run: AdvisorRun) -> None:
    """Persist a briefing's actionable or terminal state; repeated hooks are idempotent."""
    schedule_id = (run.runtime_metadata or {}).get("schedule_id")
    notices = {
        "completed": ("briefing_ready", "브리핑이 준비되었습니다", "결과와 제안을 상담 화면에서 확인하세요.", "info"),
        "waiting_input": ("briefing_ready", "브리핑에 확인할 내용이 있습니다", "상담 화면에서 질문에 답하면 브리핑을 이어갑니다.", "info"),
        "blocked": ("job_failed", "브리핑에 확인이 필요합니다", "연결과 공유 범위를 확인한 뒤 상담 화면에서 다시 시도하세요.", "warning"),
        "failed": ("job_failed", "브리핑을 마치지 못했습니다", "상담 화면에서 상태를 확인하고 다시 시도하세요.", "warning"),
        "cancelled": ("briefing_ready", "브리핑을 중지했습니다", "예약 설정이 바뀌었거나 사용자가 실행을 중지했습니다.", "info"),
    }
    if not schedule_id or run.status not in notices:
        return
    kind, title, summary, severity = notices[run.status]
    notify(session, kind, title, f"briefing:{run.request_id}", summary=summary, severity=severity,
           links={"conversation_id": run.conversation_id, "run_id": run.id, "schedule_id": schedule_id,
                  "run_status": run.status}, reopen_on_change=True)


def options_of(body) -> dict:
    return {"weekday": body.weekday, "llm_enabled": body.llm_enabled,
            "categories": sorted(str(c) for c in body.categories), "playbook_ids": body.playbook_ids}


def cancel_unfinished(session: Session, schedule: JobSchedule) -> None:
    """Withdraw every unfinished run whose consent predates this schedule edit."""
    from app.modules.advisor.runtime.persistence import RunRepository
    repository = RunRepository(session)
    for run_id in list(session.scalars(select(AdvisorRun.id).where(
            AdvisorRun.request_id.like(f"briefing:{schedule.id}:%"),
            AdvisorRun.status.not_in(["completed", "cancelled", "failed"])))):
        repository.cancel(run_id)


async def activate(session: Session, schedule: JobSchedule, enabled: bool) -> JobSchedule:
    """Enabling model use pins the current run authority and model; disabling clears it."""
    schedule.enabled = enabled
    schedule.paused_reason = None
    if enabled and schedule.options.get("llm_enabled"):
        from app.modules.llm import run_policy
        from app.modules.llm.llm_gateway_manager import llm_gateway_manager
        schedule.authorization = run_policy.capture(session)
        schedule.options = {**schedule.options, "model": await llm_gateway_manager.resolve_model(session)}
    elif not enabled or not schedule.options.get("llm_enabled"):
        schedule.authorization = None
    if enabled:
        schedule.next_run_at = first_run_at(utcnow(), schedule)
    from app.modules.crud import audit_log_handler
    audit_log_handler.record(session, "user", "schedule.activate" if enabled else "schedule.pause",
                             f"job_schedules:{schedule.id}", {"llm_enabled": bool(schedule.options.get("llm_enabled"))})
    return schedule
