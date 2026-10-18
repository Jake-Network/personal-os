from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Holding


class HoldingHandler(BaseCRUDHandler[Holding]):
    def __init__(self):
        super().__init__(Holding)

    def get_all(self, session: Session) -> list[Holding]:
        return self.get_multiple_with_filters(session, order_by=[Holding.id])

    def get_priced(self, session: Session) -> list[Holding]:
        return self.get_multiple_with_filters(session, [Holding.last_price.is_not(None)], [Holding.id])


holding_handler = HoldingHandler()
