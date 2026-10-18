from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import Account


class AccountHandler(BaseCRUDHandler[Account]):
    def __init__(self):
        super().__init__(Account)

    def get_all(self, session: Session) -> list[Account]:
        return self.get_multiple_with_filters(session, order_by=[Account.id])


account_handler = AccountHandler()
