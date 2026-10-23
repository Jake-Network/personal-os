"""Deterministic briefing signals: Hermes' no-agent script mode, with no model call.

Signals are local counts with links. Only categories and counts decide whether a model
briefing is worth running; the briefing itself reads data through the normal context path.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.enums.context_category import Category

LABELS = {
    "expenses": "이번 달 지출이 월평균을 넘었습니다",
    "goals": "2주 안에 목표 기한이 있습니다",
    "interviews": "7일 안에 면접이 있습니다",
    "interviews_soon": "24시간 안에 면접이 있습니다",
    "exercise": "일주일 넘게 운동 기록이 없습니다",
    "decisions_due": "회고할 결정이 있습니다",
    "memories_due": "다시 확인할 기억이 있습니다",
    "stale_data": "오래된 시세·잔고가 있습니다",
    "approvals": "승인을 기다리는 제안이 있습니다",
}
# Which data a model briefing would need for each signal. Signals whose records no context
# tool provides (decision journal, memory review dates, approvals) stay local-only: they never
# wake the model, because a briefing about them would have no evidence to work from.
CATEGORIES = {
    "expenses": {Category.FINANCIAL}, "goals": {Category.GOALS}, "interviews": {Category.CAREER, Category.CALENDAR},
    "interviews_soon": {Category.CAREER, Category.CALENDAR}, "exercise": {Category.HEALTH},
    "decisions_due": set(), "memories_due": set(),
    "stale_data": {Category.FINANCIAL, Category.INVESTMENT}, "approvals": set(),
}
LINKS = {"expenses": "/finance", "goals": "/plan", "interviews": "/career", "interviews_soon": "/career",
         "exercise": "/plan", "decisions_due": "/reflect", "memories_due": "/reflect/memory",
         "stale_data": "/finance", "approvals": "/approvals"}


def collect(session: Session, now: datetime | None = None) -> list[dict]:
    from app.modules.dashboard.dashboard_manager import dashboard_manager
    from app.modules.database.model import DecisionJournalEntry, MemoryRevision, PersonalMemory, PlaybookRevision, ProposedAction
    now = now or datetime.now(UTC)
    summary = dashboard_manager.summary(session, now)
    signals = [{"kind": item["kind"], "count": item["count"]} for item in summary["signals"]]
    interviews = summary["data"].get("get_interview_schedule", {}).get("interviews", [])
    soon = [i for i in interviews if now <= datetime.fromisoformat(i["starts_at"]) < now + timedelta(hours=24)]
    if soon:
        signals.append({"kind": "interviews_soon", "count": len(soon)})
    decisions = session.scalar(select(func.count()).select_from(DecisionJournalEntry).where(
        DecisionJournalEntry.review_on.is_not(None), DecisionJournalEntry.review_on <= now,
        or_(DecisionJournalEntry.reviewed_at.is_(None), DecisionJournalEntry.reviewed_at < DecisionJournalEntry.review_on))) or 0
    if decisions:
        signals.append({"kind": "decisions_due", "count": decisions})
    latest = select(MemoryRevision.memory_id, func.max(MemoryRevision.revision).label("revision")).group_by(
        MemoryRevision.memory_id).subquery()
    memories = session.scalar(select(func.count()).select_from(MemoryRevision).join(
        latest, (latest.c.memory_id == MemoryRevision.memory_id) & (latest.c.revision == MemoryRevision.revision)).join(
        PersonalMemory, PersonalMemory.id == MemoryRevision.memory_id).where(
        PersonalMemory.status == "confirmed", MemoryRevision.review_on.is_not(None), MemoryRevision.review_on <= now)) or 0
    if memories:
        signals.append({"kind": "memories_due", "count": memories})
    stale = sum(1 for flag in summary["data_quality_flags"] if str(flag.get("code", "")).startswith("stale"))
    if stale:
        signals.append({"kind": "stale_data", "count": stale})
    pending = sum(session.scalar(select(func.count()).where(condition)) or 0 for condition in (
        ProposedAction.status == "pending", PersonalMemory.status == "proposed", PlaybookRevision.status == "proposed"))
    if pending:
        signals.append({"kind": "approvals", "count": pending})
    return [{**signal, "title": LABELS.get(signal["kind"], signal["kind"]), "link": LINKS.get(signal["kind"])}
            for signal in signals]
