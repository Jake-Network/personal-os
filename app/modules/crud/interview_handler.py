from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Interview, JobApplication


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


interview_handler = InterviewHandler()
