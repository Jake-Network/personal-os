"""Local inbox: the app's only delivery target for background work.

Writers dedupe by a stable key so a retried tick never duplicates a notice. Callers own
the transaction. Summaries stay on this machine; no inbox text is sent to a model.
"""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud.playbook_handler import inbox_handler
from app.modules.database.model import InboxItem
from app.modules.database.model.base import utcnow


def notify(session: Session, kind: str, title: str, dedupe_key: str, *, summary: str = "",
           severity: str = "info", links: dict | None = None,
           reopen_on_change: bool = False) -> InboxItem:
    existing = inbox_handler.by_key(session, dedupe_key)
    if existing is not None:
        changed = (existing.kind, existing.title, existing.summary, existing.severity, existing.links) != (
            kind, title[:200], summary, severity, links or {})
        if existing.status == "unread" or reopen_on_change:
            # A terminal transition is new information even if preparation was already read.
            existing.kind, existing.title, existing.summary = kind, title[:200], summary
            existing.severity, existing.links = severity, links or {}
            if reopen_on_change and changed:
                existing.status, existing.read_at = "unread", None
        return existing
    item = InboxItem(kind=kind, title=title[:200], summary=summary, severity=severity,
                     links=links or {}, dedupe_key=dedupe_key[:160])
    try:
        with session.begin_nested():
            session.add(item)
            session.flush()
    except IntegrityError:
        return inbox_handler.by_key(session, dedupe_key)
    return item


def mark(session: Session, item_id: int, status: str) -> InboxItem:
    item = inbox_handler.get(session, item_id)
    if item is None:
        raise LookupError("알림을 찾을 수 없습니다")
    item.status = status
    item.read_at = item.read_at or utcnow()
    session.commit()
    return item


def read_all(session: Session) -> int:
    changed = session.execute(update(InboxItem).where(InboxItem.status == "unread")
                              .values(status="read", read_at=utcnow()))
    session.commit()
    return changed.rowcount
