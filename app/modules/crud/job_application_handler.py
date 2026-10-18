from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import JobApplication


class JobApplicationHandler(BaseCRUDHandler[JobApplication]):
    def __init__(self):
        super().__init__(JobApplication)

    def get_by_statuses(self, session: Session, statuses: Sequence[str]) -> list[JobApplication]:
        return self.get_multiple_with_filters(session, [JobApplication.status.in_(statuses)], [JobApplication.id])


job_application_handler = JobApplicationHandler()
