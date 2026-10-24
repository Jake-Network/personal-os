"""ORM access for playbooks, their revisions, usage and inbox items; callers own transactions."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import InboxItem, Playbook, PlaybookRevision, PlaybookUsage


class PlaybookHandler(BaseCRUDHandler[Playbook]):
    def __init__(self):
        super().__init__(Playbook)

    def by_slug(self, session: Session, slug: str) -> Playbook | None:
        return session.scalar(select(Playbook).where(Playbook.slug == slug))

    def listed(self, session: Session, include_archived: bool = False) -> list[Playbook]:
        statuses = ["active", "proposed", *(["archived", "rejected"] if include_archived else [])]
        return list(session.scalars(select(Playbook).where(Playbook.status.in_(statuses)).order_by(Playbook.slug)))

    def active_revision(self, session: Session, playbook_id: int) -> PlaybookRevision | None:
        return session.scalar(select(PlaybookRevision).where(
            PlaybookRevision.playbook_id == playbook_id, PlaybookRevision.status == "active"))

    def revisions(self, session: Session, playbook_id: int) -> list[PlaybookRevision]:
        return list(session.scalars(select(PlaybookRevision).where(PlaybookRevision.playbook_id == playbook_id)
                                    .order_by(PlaybookRevision.revision.desc())))

    def next_revision(self, session: Session, playbook_id: int) -> int:
        return (session.scalar(select(func.max(PlaybookRevision.revision)).where(
            PlaybookRevision.playbook_id == playbook_id)) or 0) + 1

    def pending(self, session: Session) -> list[PlaybookRevision]:
        return list(session.scalars(select(PlaybookRevision).where(PlaybookRevision.status == "proposed")
                                    .order_by(PlaybookRevision.created_at, PlaybookRevision.id)))

    def pending_counts(self, session: Session) -> dict[int, int]:
        return dict(session.execute(select(PlaybookRevision.playbook_id, func.count()).where(
            PlaybookRevision.status == "proposed").group_by(PlaybookRevision.playbook_id)).all())

    def usage_counts(self, session: Session) -> dict[int, int]:
        return dict(session.execute(select(PlaybookRevision.playbook_id, func.count(PlaybookUsage.id))
            .join(PlaybookUsage, PlaybookUsage.revision_id == PlaybookRevision.id)
            .group_by(PlaybookRevision.playbook_id)).all())


class InboxHandler(BaseCRUDHandler[InboxItem]):
    def __init__(self):
        super().__init__(InboxItem)

    def by_key(self, session: Session, dedupe_key: str) -> InboxItem | None:
        return session.scalar(select(InboxItem).where(InboxItem.dedupe_key == dedupe_key))

    def listed(self, session: Session, status: str | None, limit: int, offset: int) -> list[InboxItem]:
        statement = select(InboxItem)
        statement = statement.where(InboxItem.status == status) if status else statement.where(InboxItem.status != "dismissed")
        return list(session.scalars(statement.order_by(InboxItem.created_at.desc(), InboxItem.id.desc())
                                    .limit(limit).offset(offset)))

    def unread(self, session: Session) -> int:
        return session.scalar(select(func.count()).select_from(InboxItem).where(InboxItem.status == "unread")) or 0


playbook_handler = PlaybookHandler()
inbox_handler = InboxHandler()
