from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AppSetting


class AppSettingHandler(BaseCRUDHandler[AppSetting]):
    def __init__(self):
        super().__init__(AppSetting)

    def get_value(self, session: Session, key: str) -> dict | None:
        row = self.get(session, key)
        return row.value if row else None

    def set_value(self, session: Session, key: str, value: dict) -> AppSetting:
        row = self.get(session, key)
        if row is None:
            row = AppSetting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
        session.flush()
        return row


app_setting_handler = AppSettingHandler()
