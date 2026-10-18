"""Public quote connection and explicit local import endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.modules.database import get_session
from app.modules.portfolio import market_data_manager as manager
from app.router.portfolio_router import _call

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return manager.status(session)


@router.post("/initialize")
def initialize(session: Session = Depends(get_session)):
    return _call(manager.initialize, session)


@router.post("/refresh")
def refresh(session: Session = Depends(get_session)):
    return _call(manager.refresh, session)


@router.get("/observations")
def observations(symbol: str | None = None, session: Session = Depends(get_session)):
    return manager.observations(session, symbol)


@router.get("/imports/{import_id}/preview")
def import_preview(import_id: int, session: Session = Depends(get_session)):
    return _call(manager.import_preview, session, import_id)


@router.post("/imports/{import_id}")
def import_holdings(import_id: int, session: Session = Depends(get_session)):
    return _call(manager.import_holdings, session, import_id)


from app.schema.market_data_schema import CsvImportInput


@router.post("/csv/preview")
def csv_preview(body: CsvImportInput, session: Session = Depends(get_session)):
    return _call(manager.csv_preview, session, body)


@router.post("/csv/import", status_code=201)
def csv_import(body: CsvImportInput, session: Session = Depends(get_session)):
    return _call(manager.csv_import, session, body)
