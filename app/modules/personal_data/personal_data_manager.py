"""User-entered personal data (v0.1 foundation subset). Every change is audit-logged.

These endpoints are the user's own edits. The advisor has no path to them: its only write
channel is proposal_manager, which cannot touch financial tables (AC-18).
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.crud import (
    account_handler,
    audit_log_handler,
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
    planned_expense_handler,
    task_handler,
    workout_log_handler,
)
from app.modules.finance.value_history import capture, split_history_fields, tracks
from app.modules.finance.value_history_manager import value_history_manager
from app.modules.personal_data.types import Resource
from app.schema import domain_schema as s


RESOURCES: dict[str, Resource] = {
    "accounts": Resource(account_handler, s.AccountCreate, s.AccountItem, True),
    "other-assets": Resource(other_asset_handler, s.OtherAssetCreate, s.OtherAssetItem, True),
    "liabilities": Resource(liability_handler, s.LiabilityCreate, s.LiabilityItem, True),
    "holdings": Resource(holding_handler, s.HoldingCreate, s.HoldingItem, True),
    "fx-rates": Resource(fx_rate_handler, s.FxRateCreate, s.FxRateItem, True),
    "cashflow-entries": Resource(cashflow_entry_handler, s.CashflowEntryCreate, s.CashflowEntryItem, True),
    "planned-expenses": Resource(planned_expense_handler, s.PlannedExpenseCreate, s.PlannedExpenseItem, True),
    "job-applications": Resource(job_application_handler, s.JobApplicationCreate, s.JobApplicationItem),
    "interviews": Resource(interview_handler, s.InterviewCreate, s.InterviewItem),
    "career-criteria": Resource(career_criterion_handler, s.CareerCriterionCreate, s.CareerCriterionItem),
    "calendar-events": Resource(calendar_event_handler, s.CalendarEventCreate, s.CalendarEventItem),
    "goals": Resource(goal_handler, s.GoalCreate, s.GoalItem),
    "tasks": Resource(task_handler, s.TaskCreate, s.TaskItem),
    "workout-logs": Resource(workout_log_handler, s.WorkoutLogCreate, s.WorkoutLogItem),
}


class PersonalDataManager:
    def list(self, session: Session, resource: Resource) -> list:
        model = resource.handler.model
        return resource.handler.get_multiple_with_filters(session, order_by=[model.id])

    def get(self, session: Session, resource: Resource, item_id: int):
        obj = resource.handler.get(session, item_id)
        if obj is None:
            raise LookupError("not found")
        return obj

    def create(self, session: Session, name: str, resource: Resource, body: BaseModel):
        data, trade_date = split_history_fields(name, body)
        obj = resource.handler.create(session, data)
        if tracks(name):
            value_history_manager.record(session, name, obj, None, "create", trade_date=trade_date)
        self._audit(session, name, resource, "create", obj.id)
        session.commit()
        return obj

    def update(self, session: Session, name: str, resource: Resource, item_id: int, body: BaseModel):
        obj = self.get(session, resource, item_id)
        before = capture(name, obj) if tracks(name) else None
        data, trade_date = split_history_fields(name, body, exclude_unset=True)
        resource.handler.update(session, obj, data)
        if before is not None:
            value_history_manager.record(session, name, obj, before, "update", trade_date=trade_date)
        self._audit(session, name, resource, "update", obj.id)
        session.commit()
        return obj

    def delete(self, session: Session, name: str, resource: Resource, item_id: int) -> None:
        obj = self.get(session, resource, item_id)
        if tracks(name):
            value_history_manager.record(session, name, obj, capture(name, obj), "delete")
        resource.handler.delete(session, obj)
        self._audit(session, name, resource, "delete", item_id)
        session.commit()

    @staticmethod
    def _audit(session: Session, name: str, resource: Resource, verb: str, item_id: int) -> None:
        audit_log_handler.record(session, "user", f"data.{verb}", f"{name}:{item_id}",
                                 {"financial": resource.financial})


personal_data_manager = PersonalDataManager()
