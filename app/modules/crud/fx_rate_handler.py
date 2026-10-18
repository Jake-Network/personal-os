from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import FxRate


class FxRateHandler(BaseCRUDHandler[FxRate]):
    def __init__(self):
        super().__init__(FxRate)

    def get_latest_first(self, session: Session) -> list[FxRate]:
        return self.get_multiple_with_filters(session, order_by=[FxRate.as_of.desc()])


fx_rate_handler = FxRateHandler()
