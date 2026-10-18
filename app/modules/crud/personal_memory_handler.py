from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import PersonalMemory


class PersonalMemoryHandler(BaseCRUDHandler[PersonalMemory]):
    def __init__(self):
        super().__init__(PersonalMemory)

    def get_by_status(self, session: Session, status: str) -> list[PersonalMemory]:
        return self.get_multiple_with_filters(session, [PersonalMemory.status == status], [PersonalMemory.id])


personal_memory_handler = PersonalMemoryHandler()
