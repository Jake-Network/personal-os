from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import CareerCriterion, Interview, JobApplication


class JobApplicationHandler(BaseCRUDHandler[JobApplication]):
    def __init__(self):
        super().__init__(JobApplication)

    def get_by_statuses(self, session: Session, statuses: Sequence[str]) -> list[JobApplication]:
        return self.get_multiple_with_filters(session, [JobApplication.status.in_(statuses)], [JobApplication.id])


class InterviewHandler(BaseCRUDHandler[Interview]):
    def __init__(self):
        super().__init__(Interview)

    def get_with_application_between(
        self, session: Session, start: datetime, end: datetime
    ) -> list[tuple[Interview, JobApplication]]:
        stmt = (
            select(Interview, JobApplication)
            .join(JobApplication, Interview.application_id == JobApplication.id)
            .where(Interview.starts_at >= start, Interview.starts_at <= end)
            .order_by(Interview.starts_at)
        )
        return [(i, a) for i, a in session.execute(stmt)]


class CareerCriterionHandler(BaseCRUDHandler[CareerCriterion]):
    def __init__(self):
        super().__init__(CareerCriterion)

    def get_by_weight(self, session: Session) -> list[CareerCriterion]:
        return self.get_multiple_with_filters(session, order_by=[CareerCriterion.weight.desc(), CareerCriterion.id])


job_application_handler = JobApplicationHandler()
interview_handler = InterviewHandler()
career_criterion_handler = CareerCriterionHandler()
