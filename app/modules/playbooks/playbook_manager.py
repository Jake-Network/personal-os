"""User-approved advisor procedures (Hermes-style skills, stored as local DB revisions).

A user's own edit is active immediately. Anything a model proposes stays `proposed`
until the user approves it against the exact revision it patches. Revision content is
never rewritten; approval only moves status forward and every change is audited.
"""
import difflib

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud import audit_log_handler
from app.modules.crud.playbook_handler import playbook_handler
from app.modules.database.model import Playbook, PlaybookRevision
from app.modules.database.model.base import utcnow
from app.modules.playbooks.validation import validate
from app.schema.playbook_schema import (
    PlaybookCreate, PlaybookDetail, PlaybookItem, PlaybookRevise, PlaybookRevisionItem,
)


class StaleRevision(ValueError):
    """The revision a change was based on is no longer the approved one."""


class PlaybookManager:
    def listed(self, session: Session, include_archived: bool = False) -> list[Playbook]:
        return playbook_handler.listed(session, include_archived)

    def get(self, session: Session, playbook_id: int) -> Playbook:
        playbook = playbook_handler.get(session, playbook_id)
        if playbook is None:
            raise LookupError("플레이북을 찾을 수 없습니다")
        return playbook

    def revision(self, session: Session, revision_id: int) -> PlaybookRevision:
        revision = session.get(PlaybookRevision, revision_id)
        if revision is None:
            raise LookupError("플레이북 버전을 찾을 수 없습니다")
        return revision

    def revision_view(self, session: Session, revision: PlaybookRevision) -> PlaybookRevisionItem:
        return PlaybookRevisionItem.model_validate(revision).model_copy(update={"stale": self.is_stale(session, revision)})

    def describe(self, session: Session, playbooks: list[Playbook], detail: bool = False) -> list:
        pending, usage = playbook_handler.pending_counts(session), playbook_handler.usage_counts(session)
        views = []
        for playbook in playbooks:
            active = playbook_handler.active_revision(session, playbook.id)
            values = {**PlaybookItem.model_validate(playbook).model_dump(),
                      "active_revision": self.revision_view(session, active) if active else None,
                      "pending_count": pending.get(playbook.id, 0), "usage_count": usage.get(playbook.id, 0)}
            if detail:
                values["revisions"] = [self.revision_view(session, r) for r in playbook_handler.revisions(session, playbook.id)]
                views.append(PlaybookDetail.model_validate(values))
            else:
                views.append(PlaybookItem.model_validate(values))
        return views

    def is_stale(self, session: Session, revision: PlaybookRevision) -> bool:
        if revision.status != "proposed":
            return False
        current = playbook_handler.active_revision(session, revision.playbook_id)
        return (current.id if current else None) != revision.base_revision_id

    def create(self, session: Session, body: PlaybookCreate) -> Playbook:
        content, warnings = validate(slug=body.slug, title=body.title, summary=body.summary, body=body.body,
                                     triggers=body.triggers, categories=body.categories, source="user")
        if playbook_handler.by_slug(session, body.slug) is not None:
            raise ValueError("같은 이름의 플레이북이 있습니다")
        playbook = playbook_handler.create(session, {"slug": body.slug, "status": "active", "source": "user"})
        revision = PlaybookRevision(playbook_id=playbook.id, revision=1, status="active", source="user",
                                    warnings=warnings, decided_at=utcnow(), **content)
        session.add(revision)
        session.flush()
        audit_log_handler.record(session, "user", "playbook.create", f"playbook_revisions:{revision.id}")
        session.commit()
        return playbook

    def revise(self, session: Session, playbook_id: int, body: PlaybookRevise) -> PlaybookRevision:
        playbook = self.get(session, playbook_id)
        content, warnings = validate(slug=None, title=body.title, summary=body.summary, body=body.body,
                                     triggers=body.triggers, categories=body.categories, source="user")
        current = playbook_handler.active_revision(session, playbook.id)
        if current is None or current.id != body.base_revision_id:
            raise StaleRevision("다른 곳에서 플레이북이 바뀌었습니다. 최신 버전을 확인한 뒤 다시 수정하세요.")
        revision = PlaybookRevision(playbook_id=playbook.id, revision=playbook_handler.next_revision(session, playbook.id),
                                    status="proposed", source="user", base_revision_id=current.id,
                                    warnings=warnings, **content)
        session.add(revision)
        session.flush()
        self._activate(session, revision, current)
        audit_log_handler.record(session, "user", "playbook.revise", f"playbook_revisions:{revision.id}")
        session.commit()
        return revision

    def propose(self, session: Session, *, slug: str, base_revision_id: int | None, title: str, summary: str,
                body: str, triggers: list[str], categories: list[str], rationale: str,
                source_references: list[dict], job_id: int | None) -> PlaybookRevision:
        """Stage a model-written draft. Raises PlaybookInvalid; never activates."""
        content, _ = validate(slug=slug, title=title, summary=summary, body=body, triggers=triggers,
                              categories=categories, source="advisor")
        playbook = playbook_handler.by_slug(session, slug)
        if playbook is None:
            if base_revision_id is not None:
                raise ValueError("수정할 플레이북을 찾을 수 없습니다")
            playbook = playbook_handler.create(session, {"slug": slug, "status": "proposed", "source": "advisor"})
        elif playbook.status == "archived":
            raise ValueError("보관된 플레이북에는 제안하지 않습니다")
        else:
            current = playbook_handler.active_revision(session, playbook.id)
            if (current.id if current else None) != base_revision_id:
                raise StaleRevision("제안의 기준 버전이 현재 승인된 버전과 다릅니다")
            if playbook.status == "rejected":
                playbook.status = "proposed"
        from app.modules.context.record_privacy import stamp_references
        revision = PlaybookRevision(playbook_id=playbook.id, revision=playbook_handler.next_revision(session, playbook.id),
                                    status="proposed", source="advisor", base_revision_id=base_revision_id,
                                    rationale=rationale[:2000] or None, warnings=[],
                                    source_references=stamp_references(session, source_references),
                                    proposed_by_job_id=job_id, **content)
        session.add(revision)
        session.flush()
        audit_log_handler.record(session, "advisor", "playbook.propose", f"playbook_revisions:{revision.id}")
        return revision

    def approve(self, session: Session, revision_id: int) -> PlaybookRevision:
        revision = self.revision(session, revision_id)
        if revision.status != "proposed":
            raise ValueError(f"이미 처리된 제안입니다 ({revision.status})")
        if revision.source_purged:
            raise ValueError("제안의 근거가 삭제되어 승인할 수 없습니다")
        current = playbook_handler.active_revision(session, revision.playbook_id)
        if (current.id if current else None) != revision.base_revision_id:
            raise StaleRevision("제안 이후 플레이북이 바뀌었습니다. 최신 버전과 비교한 뒤 다시 제안을 받으세요.")
        # Rules may have tightened since the proposal was staged.
        validate(slug=None, title=revision.title, summary=revision.summary, body=revision.body,
                 triggers=revision.triggers, categories=revision.categories, source=revision.source)
        self._activate(session, revision, current)
        audit_log_handler.record(session, "user", "playbook.approve", f"playbook_revisions:{revision.id}")
        session.commit()
        return revision

    def reject(self, session: Session, revision_id: int) -> PlaybookRevision:
        revision = self.revision(session, revision_id)
        changed = session.execute(update(PlaybookRevision).where(
            PlaybookRevision.id == revision.id, PlaybookRevision.status == "proposed").values(
                status="rejected", decided_at=utcnow()))
        if changed.rowcount != 1:
            session.rollback()
            raise ValueError("이미 처리된 제안입니다")
        playbook = self.get(session, revision.playbook_id)
        self._settle_without_active(session, playbook)
        audit_log_handler.record(session, "user", "playbook.reject", f"playbook_revisions:{revision.id}")
        session.commit()
        session.refresh(revision)
        return revision

    def set_status(self, session: Session, playbook_id: int, archived: bool) -> Playbook:
        playbook = self.get(session, playbook_id)
        if archived:
            playbook.status = "archived"
        elif playbook.status == "archived":
            playbook.status = "active" if playbook_handler.active_revision(session, playbook.id) else "proposed"
        audit_log_handler.record(session, "user", "playbook.archive" if archived else "playbook.restore",
                                 f"playbooks:{playbook.id}")
        session.commit()
        return playbook

    def set_sharing(self, session: Session, playbook_id: int, external_allowed: bool) -> Playbook:
        playbook = self.get(session, playbook_id)
        playbook.external_allowed = external_allowed
        audit_log_handler.record(session, "user", "playbook.sharing", f"playbooks:{playbook.id}",
                                 {"external_allowed": external_allowed})
        session.commit()
        return playbook

    def delete(self, session: Session, playbook_id: int) -> None:
        playbook = self.get(session, playbook_id)
        playbook_handler.delete(session, playbook)
        audit_log_handler.record(session, "user", "playbook.delete", f"playbooks:{playbook_id}")
        session.commit()

    def diff(self, session: Session, revision_id: int) -> tuple[PlaybookRevision, str]:
        revision = self.revision(session, revision_id)
        base = session.get(PlaybookRevision, revision.base_revision_id) if revision.base_revision_id else None
        before = _render(base).splitlines(keepends=True) if base else []
        after = _render(revision).splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(before, after, fromfile=f"v{base.revision}" if base else "(새 플레이북)",
                                            tofile=f"v{revision.revision}"))
        return revision, diff

    def _activate(self, session: Session, revision: PlaybookRevision, current: PlaybookRevision | None) -> None:
        """Conditional transitions: of two concurrent approvals exactly one can succeed."""
        now = utcnow()
        try:
            if current is not None:
                superseded = session.execute(update(PlaybookRevision).where(
                    PlaybookRevision.id == current.id, PlaybookRevision.status == "active").values(status="superseded"))
                if superseded.rowcount != 1:
                    raise StaleRevision("플레이북이 동시에 변경되었습니다")
            activated = session.execute(update(PlaybookRevision).where(
                PlaybookRevision.id == revision.id, PlaybookRevision.status == "proposed").values(
                    status="active", decided_at=now))
            if activated.rowcount != 1:
                raise ValueError("이미 처리된 제안입니다")
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise StaleRevision("플레이북이 동시에 변경되었습니다") from exc
        except ValueError:
            session.rollback()
            raise
        playbook = self.get(session, revision.playbook_id)
        if playbook.status != "archived":
            playbook.status = "active"
        session.refresh(revision)

    @staticmethod
    def _settle_without_active(session: Session, playbook: Playbook) -> None:
        if playbook.status != "proposed" or playbook_handler.active_revision(session, playbook.id):
            return
        if not playbook_handler.pending_counts(session).get(playbook.id):
            playbook.status = "rejected"


def _render(revision: PlaybookRevision) -> str:
    return (f"제목: {revision.title}\n요약: {revision.summary}\n"
            f"트리거: {', '.join(revision.triggers)}\n범주: {', '.join(revision.categories)}\n\n{revision.body}\n")


def purge_sources(session: Session, identities: set[tuple[str, str]]) -> None:
    """A deleted origin rejects drafts that cite it and stops sending approved revisions."""
    from sqlalchemy import select
    from app.modules.agent.inbox_manager import notify
    for revision in session.scalars(select(PlaybookRevision).where(
            PlaybookRevision.source == "advisor", PlaybookRevision.status.in_(["proposed", "active"]))):
        if not any((ref.get("table"), str(ref.get("id"))) in identities for ref in revision.source_references or []):
            continue
        if revision.status == "proposed":
            revision.status, revision.decided_at = "rejected", utcnow()
        revision.source_purged = True
        if revision.status == "active":
            notify(session, "playbook_source_purged", "근거가 삭제된 플레이북이 있습니다", f"playbook-purged:{revision.id}",
                   summary="학습 근거가 된 대화나 결정이 삭제되어 이 플레이북을 상담에 보내지 않습니다. "
                           "계속 쓰려면 내용을 확인하고 직접 다시 저장하세요.",
                   severity="warning", links={"playbook_id": revision.playbook_id, "playbook_revision_id": revision.id})


playbook_manager = PlaybookManager()
