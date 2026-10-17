from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AuditLog


class AuditLogHandler(BaseCRUDHandler[AuditLog]):
    def __init__(self):
        super().__init__(AuditLog)

    def record(self, session: Session, actor: str, action: str, target: str | None = None,
               detail: dict | None = None) -> None:
        session.add(AuditLog(actor=actor, action=action, target=target, detail=detail or {}))


audit_log_handler = AuditLogHandler()
