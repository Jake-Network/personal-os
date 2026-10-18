from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Liability


class LiabilityHandler(BaseCRUDHandler[Liability]):
    def __init__(self):
        super().__init__(Liability)

    def get_all(self, session: Session) -> list[Liability]:
        return self.get_multiple_with_filters(session, order_by=[Liability.id])


liability_handler = LiabilityHandler()
