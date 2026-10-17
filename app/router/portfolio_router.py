"""Read-only Sheets source with explicit sync and append-only snapshot review."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.modules.database import get_session
from app.modules.portfolio import portfolio_manager as manager
from app.schema.portfolio_schema import SheetsSettingsInput, SnapshotCorrection, SnapshotInput

router = APIRouter(prefix="/api/finance", tags=["portfolio"])


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/settings")
def settings(session: Session = Depends(get_session)):
    return manager.settings_dict(session)


@router.put("/settings")
def configure(body: SheetsSettingsInput, session: Session = Depends(get_session)):
    return _call(manager.configure, session, body.spreadsheet_id)


@router.post("/verify")
def verify(session: Session = Depends(get_session)):
    return _call(manager.verify, session)


@router.post("/sync")
def sync(session: Session = Depends(get_session)):
    return _call(manager.sync, session)


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)):
    return manager.portfolio(session)


@router.get("/history")
def history(period: str = "all", session: Session = Depends(get_session)):
    return _call(manager.history, session, period)


@router.post("/history", status_code=201)
def create_snapshot(body: SnapshotInput, session: Session = Depends(get_session)):
    return _call(manager.create_snapshot, session, body.month)


@router.post("/history/{snapshot_id}/corrections", status_code=201)
def correct_snapshot(snapshot_id: int, body: SnapshotCorrection, session: Session = Depends(get_session)):
    return _call(manager.correct_snapshot, session, snapshot_id, body)


@router.get("/history/{snapshot_id}/audit")
def audit(snapshot_id: int, session: Session = Depends(get_session)):
    return _call(manager.audit, session, snapshot_id)
