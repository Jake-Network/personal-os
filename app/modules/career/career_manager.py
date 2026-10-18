from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.crud.career_record_handler import career_record_handler as records
from app.modules.database.model.career import CareerRecord
from app.modules.database.model.advisor import AdvisorMessage, DecisionJournalEntry
from app.modules.database.model.domain import Goal, ManualValueChange
from app.modules.database.model.document import DocumentVersion
from app.modules.database.model.portfolio import MonthlySnapshot
from app.schema.career_schema import CareerRecordCreate, TimelineItem, TimelinePage, period_bounds

PARENTS = {
    "employment": set(), "role": {"employment"}, "project": {"employment", "role"},
    "contribution": {"project"}, "achievement": {"contribution", "project"},
    "feedback": {"employment", "role", "project", "contribution", "achievement"},
    "evidence": {"project", "contribution", "achievement", "feedback"},
}


class CareerManager:
    def company(self, session, row):
        while row is not None:
            if row.company:
                return row.company
            row = records.get(session, row.parent_id) if row.parent_id else None
        return None

    def list(self, session, kind=None, company=None, project_id=None, skill=None):
        rows = records.list(session)
        if project_id is not None:
            project = records.get(session, project_id)
            if project.kind != "project":
                raise ValueError("프로젝트 기록 ID가 필요합니다")
            descendants = {project_id}
            while True:
                expanded = descendants | {r.id for r in rows if r.parent_id in descendants}
                if expanded == descendants:
                    break
                descendants = expanded
            rows = [r for r in rows if r.id in descendants]
        return [r for r in rows if (kind is None or r.kind == kind)
                and (company is None or self.company(session, r) == company) and (skill is None or skill in r.skills)]

    def _validate(self, session: Session, body: CareerRecordCreate, current_id=None):
        if body.parent_id is not None:
            parent = records.get(session, body.parent_id)
            if parent.kind not in PARENTS[body.kind]:
                raise ValueError("이 종류의 상위 기록에는 연결할 수 없습니다")
            ancestor = parent
            while ancestor is not None:
                if ancestor.id == current_id:
                    raise ValueError("기록 연결에 순환이 생깁니다")
                ancestor = records.get(session, ancestor.parent_id) if ancestor.parent_id else None
        if body.source_message_id is not None and session.get(AdvisorMessage, body.source_message_id) is None:
            raise LookupError("출처 메시지를 찾을 수 없습니다")
        if body.source_document_version_id is not None and session.get(DocumentVersion, body.source_document_version_id) is None:
            raise LookupError("출처 문서 버전을 찾을 수 없습니다")
        if current_id is not None:
            for child in records.list(session):
                if child.parent_id == current_id and body.kind not in PARENTS[child.kind]:
                    raise ValueError("연결된 하위 기록과 종류가 맞지 않습니다")

    def save(self, session, body, record_id=None):
        self._validate(session, body, record_id)
        row = records.get(session, record_id) if record_id else CareerRecord()
        previous_source = row.source if record_id else None
        if record_id and (body.source != row.source or body.source_message_id != row.source_message_id
                          or body.source_document_version_id != row.source_document_version_id):
            raise ValueError("기존 기록의 출처는 변경할 수 없습니다")
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        if not record_id:
            row.source_references = ([{"table": "advisor_messages", "id": body.source_message_id}] if body.source_message_id else [])
            if body.source_document_version_id:
                row.source_references.append({"table": "document_versions", "id": body.source_document_version_id})
        # Any extracted or edited draft needs a separate explicit confirmation.
        if not record_id or body.source != "user" or previous_source != body.source:
            row.status = "confirmed" if body.source == "user" else "draft"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def confirm(self, session, record_id):
        row = records.get(session, record_id)
        row.status = "confirmed"
        session.commit()
        session.refresh(row)
        return row

    def delete(self, session, record_id):
        row = records.get(session, record_id)
        if records.has_children(session, record_id):
            raise ValueError("연결된 하위 기록을 먼저 옮기거나 삭제하세요")
        session.delete(row)
        session.commit()

    def timeline(self, session, *, start=None, end=None, domain=None, company=None, project_id=None, offset=0, limit=100):
        items = []
        if domain in (None, "career"):
            for r in self.list(session, company=company, project_id=project_id):
                items.append(TimelineItem(source_kind=r.kind, source_id=r.id, title=r.title, occurred_on=r.started_on,
                    ended_on=r.ended_on, recorded_at=r.recorded_at, company=self.company(session, r), parent_id=r.parent_id,
                    status=r.status, href=f"/career#record-{r.id}"))
        if company is None and project_id is None:
            if domain in (None, "decisions"):
                for r in session.scalars(select(DecisionJournalEntry)):
                    items.append(TimelineItem(source_kind="decision", source_id=r.id, title=r.title,
                        occurred_on=r.decided_at.astimezone(ZoneInfo(settings.timezone)).date().isoformat(), recorded_at=r.decided_at, href="/memory"))
            if domain in (None, "goals"):
                for r in session.scalars(select(Goal)):
                    items.append(TimelineItem(source_kind="goal", source_id=r.id, title=r.title,
                        occurred_on=r.target_date.isoformat() if r.target_date else None, recorded_at=r.created_at,
                        status=r.status, href="/data/goals"))
            if domain in (None, "finance"):
                for r in session.scalars(select(MonthlySnapshot)):
                    items.append(TimelineItem(source_kind="monthly_snapshot", source_id=r.id,
                        title=f"{r.month:%Y-%m} 월말 기록 · 수정 {r.revision}", occurred_on=r.month.strftime("%Y-%m"),
                        recorded_at=r.created_at, href="/finance/history"))
                for r in session.scalars(select(ManualValueChange)):
                    items.append(TimelineItem(source_kind="financial_change", source_id=r.id,
                        title=f"{r.table_name} #{r.record_id}: {r.field}", occurred_on=r.as_of.isoformat(),
                        recorded_at=r.recorded_at, href="/finance/history"))
        def overlaps(item):
            if item.occurred_on is None:
                return start is None and end is None
            lower, upper = period_bounds(item.occurred_on)
            if item.ended_on:
                upper = period_bounds(item.ended_on)[1]
            elif item.source_kind in {"employment", "role", "project"}:
                upper = date.max
            return (start is None or upper >= start) and (end is None or lower < end)
        items = [item for item in items if overlaps(item)]
        items.sort(key=lambda item: (item.occurred_on or "", item.recorded_at, item.source_id), reverse=True)
        return TimelinePage(items=items[offset:offset + limit], total=len(items), offset=offset, limit=limit)


career_manager = CareerManager()
