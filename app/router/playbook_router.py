from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.modules.crud.playbook_handler import playbook_handler
from app.modules.database import get_session
from app.modules.playbooks.playbook_manager import StaleRevision, playbook_manager
from app.modules.playbooks.validation import PlaybookInvalid
from app.schema.playbook_schema import (
    PlaybookCreate, PlaybookDetail, PlaybookDiff, PlaybookItem, PlaybookRevise, PlaybookRevisionItem, PlaybookSharing,
)

router = APIRouter(prefix="/api", tags=["playbooks"])


def _handle(call):
    try:
        return call()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (StaleRevision, PlaybookInvalid) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/playbooks", response_model=list[PlaybookItem])
def list_playbooks(include_archived: bool = False, session: Session = Depends(get_session)):
    return playbook_manager.describe(session, playbook_manager.listed(session, include_archived))


@router.post("/playbooks", response_model=PlaybookDetail, status_code=201)
def create_playbook(body: PlaybookCreate, session: Session = Depends(get_session)):
    playbook = _handle(lambda: playbook_manager.create(session, body))
    return playbook_manager.describe(session, [playbook], detail=True)[0]


@router.get("/playbooks/pending", response_model=list[PlaybookRevisionItem])
def list_pending_playbook_revisions(session: Session = Depends(get_session)):
    return [playbook_manager.revision_view(session, revision) for revision in playbook_handler.pending(session)]


@router.get("/playbooks/{playbook_id}", response_model=PlaybookDetail)
def get_playbook(playbook_id: int, session: Session = Depends(get_session)):
    playbook = _handle(lambda: playbook_manager.get(session, playbook_id))
    return playbook_manager.describe(session, [playbook], detail=True)[0]


@router.post("/playbooks/{playbook_id}/revisions", response_model=PlaybookRevisionItem, status_code=201)
def revise_playbook(playbook_id: int, body: PlaybookRevise, session: Session = Depends(get_session)):
    revision = _handle(lambda: playbook_manager.revise(session, playbook_id, body))
    return playbook_manager.revision_view(session, revision)


@router.patch("/playbooks/{playbook_id}/sharing", response_model=PlaybookItem)
def set_playbook_sharing(playbook_id: int, body: PlaybookSharing, session: Session = Depends(get_session)):
    playbook = _handle(lambda: playbook_manager.set_sharing(session, playbook_id, body.external_allowed))
    return playbook_manager.describe(session, [playbook])[0]


@router.post("/playbooks/{playbook_id}/archive", response_model=PlaybookItem)
def archive_playbook(playbook_id: int, session: Session = Depends(get_session)):
    playbook = _handle(lambda: playbook_manager.set_status(session, playbook_id, True))
    return playbook_manager.describe(session, [playbook])[0]


@router.post("/playbooks/{playbook_id}/restore", response_model=PlaybookItem)
def restore_playbook(playbook_id: int, session: Session = Depends(get_session)):
    playbook = _handle(lambda: playbook_manager.set_status(session, playbook_id, False))
    return playbook_manager.describe(session, [playbook])[0]


@router.delete("/playbooks/{playbook_id}", status_code=204)
def delete_playbook(playbook_id: int, session: Session = Depends(get_session)):
    _handle(lambda: playbook_manager.delete(session, playbook_id))
    return Response(status_code=204)


@router.get("/playbook-revisions/{revision_id}/diff", response_model=PlaybookDiff)
def get_playbook_revision_diff(revision_id: int, session: Session = Depends(get_session)):
    revision, diff = _handle(lambda: playbook_manager.diff(session, revision_id))
    return PlaybookDiff(revision_id=revision.id, base_revision_id=revision.base_revision_id, diff=diff)


@router.post("/playbook-revisions/{revision_id}/approve", response_model=PlaybookRevisionItem)
def approve_playbook_revision(revision_id: int, session: Session = Depends(get_session)):
    revision = _handle(lambda: playbook_manager.approve(session, revision_id))
    return playbook_manager.revision_view(session, revision)


@router.post("/playbook-revisions/{revision_id}/reject", response_model=PlaybookRevisionItem)
def reject_playbook_revision(revision_id: int, session: Session = Depends(get_session)):
    revision = _handle(lambda: playbook_manager.reject(session, revision_id))
    return playbook_manager.revision_view(session, revision)
