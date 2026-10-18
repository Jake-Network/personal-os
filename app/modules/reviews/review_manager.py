"""Local evidence-backed drafts. No provider is called and no proposal is applied."""
from datetime import date, datetime, time
import calendar
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.crud import review_jobs_handler as handler
from app.modules.crud import audit_log_handler
from app.modules.database.model.advisor import DecisionJournalEntry
from app.modules.database.model.domain import Goal
from app.modules.database.model.portfolio import MonthlySnapshot
from app.modules.database.model.career import CareerRecord
from app.modules.portfolio.snapshots import history_view
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import DecisionReviewRecord, PeriodReview
from app.schema.review_jobs_schema import OutcomeCreate, PeriodReviewCreate


def add_outcome(session: Session, decision_id: int, body: OutcomeCreate):
    entry = session.get(DecisionJournalEntry, decision_id)
    if entry is None:
        raise LookupError("결정을 찾을 수 없습니다")
    record = DecisionReviewRecord(decision_id=entry.id, **body.model_dump(),
                                  expected_outcome=entry.expected_outcome,
                                  context_snapshot_id=entry.context_snapshot_id)
    session.add(record)
    session.flush()
    # Existing clients retain a latest-outcome projection; the history is append-only.
    # An older concurrent completion must not replace a newer projection.
    session.execute(update(DecisionJournalEntry).where(
        DecisionJournalEntry.id == decision_id,
        or_(DecisionJournalEntry.reviewed_at.is_(None), DecisionJournalEntry.reviewed_at <= record.reviewed_at)
    ).values(actual_outcome=record.actual_outcome, reviewed_at=record.reviewed_at))
    audit_log_handler.record(session, "user", "decision.review.append", f"decision_reviews:{record.id}")
    return record


def build_draft(session: Session, body: PeriodReviewCreate):
    existing = handler.by_request(session, PeriodReview, body.request_id)
    if existing:
        if (existing.period, existing.start_on, existing.end_on) != (body.period, body.start_on, body.end_on):
            raise ValueError("같은 요청 ID에 다른 기간을 사용할 수 없습니다")
        if existing.evidence.get("linked_goal_ids", []) != body.goal_ids or existing.evidence.get("linked_project_ids", []) != body.project_ids:
            raise ValueError("같은 요청 ID의 연결을 바꿀 수 없습니다")
        return existing
    goals = [session.get(Goal, goal_id) for goal_id in body.goal_ids]
    projects = [session.get(CareerRecord, project_id) for project_id in body.project_ids]
    if any(goal is None for goal in goals) or any(project is None or project.kind != "project" for project in projects):
        raise ValueError("연결할 목표 또는 프로젝트를 찾을 수 없습니다")
    zone = ZoneInfo(settings.timezone)
    start, end = (datetime.combine(day, time.min, zone) for day in (body.start_on, body.end_on))
    decisions = list(session.scalars(select(DecisionJournalEntry).where(
        DecisionJournalEntry.decided_at >= start, DecisionJournalEntry.decided_at < end).order_by(DecisionJournalEntry.id)))
    outcomes = list(session.scalars(select(DecisionReviewRecord).where(
        DecisionReviewRecord.reviewed_at >= start, DecisionReviewRecord.reviewed_at < end).order_by(DecisionReviewRecord.id)))
    career = list(session.scalars(select(CareerRecord).where(CareerRecord.status == "confirmed")))
    # Precision-aware occurrence windows: a year/month-only fact is never rewritten
    # as an exact day. Unknown occurrence dates remain explicitly outside the range.
    def occurs(record):
        value = record.started_on
        if not value:
            return False
        first = value + ("-01-01" if len(value) == 4 else "-01" if len(value) == 7 else "")
        last = record.ended_on or (body.end_on.isoformat() if record.kind in {"employment", "role", "project"} else value)
        last = last + ("-12-31" if len(last) == 4 else "-31" if len(last) == 7 else "")
        return first < body.end_on.isoformat() and last >= body.start_on.isoformat()
    career = [record for record in career if occurs(record)]
    snapshot_records = list(session.scalars(select(MonthlySnapshot).order_by(MonthlySnapshot.month, MonthlySnapshot.revision)))
    historical = history_view(snapshot_records, utcnow().astimezone(zone).date())
    def within_period(month):
        day = date.fromisoformat(month)
        month_end = day.replace(day=calendar.monthrange(day.year, day.month)[1])
        return body.start_on <= month_end < body.end_on
    financial = [row for row in historical["snapshots"] if within_period(row["month"])]
    missing = [month for month in historical["missing_months"] if within_period(month)]
    evidence = {
        "decision_ids": [entry.id for entry in decisions],
        "outcome_ids": [record.id for record in outcomes],
        "decisions": [{"id": entry.id, "title": entry.title, "choice": entry.choice, "expected_outcome": entry.expected_outcome, "context_snapshot_id": entry.context_snapshot_id, "conversation_id": entry.conversation_id, "decided_at": entry.decided_at.isoformat()} for entry in decisions],
        "outcomes": [{"id": record.id, "decision_id": record.decision_id, "expected_outcome": record.expected_outcome, "actual_outcome": record.actual_outcome, "lessons": record.lessons, "next_action": record.next_action, "reviewed_at": record.reviewed_at.isoformat()} for record in outcomes],
        "scope": ["decisions", "decision_reviews", "career", "monthly_financial_snapshots"],
        "linked_goal_ids": body.goal_ids,
        "linked_project_ids": body.project_ids,
        "goals_at_generation": [{"id": goal.id, "title": goal.title, "status": goal.status, "as_of": goal.updated_at.isoformat()} for goal in goals],
        "career_records": [{"id": record.id, "kind": record.kind, "title": record.title, "started_on": record.started_on, "ended_on": record.ended_on, "outcome": record.outcome, "recorded_at": record.recorded_at.isoformat()} for record in career],
        "financial_snapshots": financial,
        "missing_financial_months": missing,
        "data_quality_flags": (["financial_snapshot_coverage_incomplete"] if missing or not financial else []) + ["financial_change_causes_not_inferred", "goal_status_is_generation_time"],
        "generated_at": utcnow().isoformat(),
        "generator": "local_record_index_v1",
    }
    text = (f"{body.start_on} ~ {body.end_on} (종료일 제외)\n"
            f"기록한 결정 {len(decisions)}건, 결과 회고 {len(outcomes)}건.\n"
            f"해당 기간 경력 기록 {len(career)}건, 보존된 재무 월말 스냅샷 {len(financial)}건.\n"
            + "".join(f"결정: {entry.title} · 선택 {entry.choice} · 기대 {entry.expected_outcome or '미기록'}\n" for entry in decisions)
            + "".join(f"결과 회고 #{record.decision_id}: 기대 {record.expected_outcome or '미기록'} / 실제 {record.actual_outcome}\n" for record in outcomes)
            + "".join(f"경력: {record.title} ({record.started_on or '시점 미기록'}) · {record.outcome or '결과 미기록'}\n" for record in career)
            + "".join(f"재무 {row['month'][:7]}: 순자산 {row.get('net_worth') if row.get('net_worth') is not None else '확인 필요'} KRW (보존된 revision {row['revision']})\n" for row in financial)
            + "현재 가격으로 과거를 복원하지 않으며 자산 변화의 원인을 자동 추정하지 않습니다.\n"
            "당시 기대와 실제 결과, 배운 점과 다음 행동을 확인해 작성하세요.")
    review = PeriodReview(**body.model_dump(exclude={"goal_ids", "project_ids"}), status="draft", content=text, evidence=evidence)
    try:
        with session.begin_nested():
            session.add(review)
            session.flush()
    except IntegrityError:
        return build_draft(session, body)
    return review


def confirm(session: Session, review_id: int, content: str):
    changed = session.execute(update(PeriodReview).where(
        PeriodReview.id == review_id, PeriodReview.status == "draft").values(
            status="confirmed", content=content, confirmed_at=utcnow()))
    if changed.rowcount != 1:
        if session.get(PeriodReview, review_id) is None:
            raise LookupError("회고를 찾을 수 없습니다")
        raise ValueError("이미 확정한 회고입니다")
    audit_log_handler.record(session, "user", "period_review.confirm", f"period_reviews:{review_id}")
    session.commit()
    return session.get(PeriodReview, review_id, populate_existing=True)
