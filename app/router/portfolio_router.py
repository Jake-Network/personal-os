"""Sheets holdings edits, explicit synchronization and append-only snapshot review."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Literal
from sqlalchemy.orm import Session

from app.modules.database import get_session
from app.modules.portfolio import portfolio_manager as manager
from app.modules.portfolio import holdings_manager
from app.schema.holdings_schema import HoldingInput
from app.router.google_oauth_router import _check_origin
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
    raise HTTPException(410, "Personal Sheets ownership is retired. Use /api/market-data/initialize for a new quotes-only file; preserved imports remain available for local migration.")


@router.post("/verify")
def verify(session: Session = Depends(get_session)):
    raise HTTPException(410, "Legacy Sheets verification retired; use quotes-only market data connection")


@router.post("/sync")
def sync(session: Session = Depends(get_session)):
    raise HTTPException(410, "Legacy personal Sheets synchronization retired; import preserved local data")


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


# Holdings edits use an explicit write-authorized Sheets path, never legacy DB CRUD.


@router.get("/holdings")
def holdings(session: Session = Depends(get_session)):
    return _call(holdings_manager.listing, session)


@router.post("/holdings/initialize")
def initialize_holdings(request: Request, session: Session = Depends(get_session)):
    _check_origin(request)
    return _call(holdings_manager.initialize, session)


@router.post("/holdings/refresh")
def refresh_holdings(request: Request, session: Session = Depends(get_session)):
    _check_origin(request)
    return _call(holdings_manager.refresh, session)


@router.post("/holdings")
def save_holding(body: HoldingInput, request: Request, session: Session = Depends(get_session)):
    _check_origin(request)
    return _call(holdings_manager.save, session, body)


from app.modules.finance import ledger_manager
from app.schema.market_data_schema import TransactionInput, MonthCloseInput

@router.get("/transactions")
def transactions(year: int | None = None, session: Session = Depends(get_session)):
    return _call(ledger_manager.listing, session, year)

@router.get("/transactions/{item_id}")
def get_transaction(item_id: int, session: Session = Depends(get_session)):
    return _call(ledger_manager.get_transaction, session, item_id)

@router.post("/transactions", status_code=201)
def transaction(body: TransactionInput, session: Session = Depends(get_session)):
    return _call(ledger_manager.record, session, body)

@router.get("/trends/{year}")
def trend(year: int, session: Session = Depends(get_session)):
    return _call(ledger_manager.trend, session, year)

@router.post("/month-close", status_code=201)
def close_month(body: MonthCloseInput, session: Session = Depends(get_session)):
    return _call(ledger_manager.close_month, session, body)

@router.post("/observed-valuations", status_code=201)
def observe_today(session: Session = Depends(get_session)):
    return _call(ledger_manager.observe_today, session)


from app.schema.market_data_schema import CoverageInput

@router.put("/coverage")
def confirm_coverage(body: CoverageInput, session: Session = Depends(get_session)):
    from app.modules.portfolio.local_portfolio import confirm_coverage as confirm
    return confirm(session, body.kinds)


from app.modules.finance import cashflow
from app.schema.cashflow_schema import CashflowResponse


@router.get("/cashflow", response_model=CashflowResponse)
def household_cashflow(
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    kind: Literal["income", "expense", "transfer", "buy", "sell", "dividend", "interest", "fee", "tax", "repayment", "split", "reversal"] | None = None,
    scope: Literal["household", "all"] = "household",
    transaction_kind: Literal["income", "expense", "transfer", "buy", "sell", "dividend", "interest", "fee", "tax", "repayment", "split", "reversal"] | None = None,
    category: str | None = Query(None, max_length=64),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    return _call(cashflow.report, session, month, kind, category, search, page, page_size, scope, transaction_kind)


from app.modules.finance import cashflow_import
from app.schema.cashflow_import_schema import (
    CashflowCategoryRuleCreate,
    CashflowCategoryRuleItem,
    CashflowImportInput,
    CashflowImportPresets,
    CashflowImportPreview,
    CashflowImportResult,
)


@router.post("/cashflow/import/preview", response_model=CashflowImportPreview)
def cashflow_import_preview(body: CashflowImportInput, session: Session = Depends(get_session)):
    return _call(cashflow_import.public_preview, session, body)


@router.post("/cashflow/import", status_code=201, response_model=CashflowImportResult)
def cashflow_import_commit(body: CashflowImportInput, session: Session = Depends(get_session)):
    return _call(cashflow_import.commit, session, body)


@router.get("/cashflow/import/presets", response_model=CashflowImportPresets)
def cashflow_import_presets(session: Session = Depends(get_session)):
    return cashflow_import.get_presets(session)


@router.put("/cashflow/import/presets", response_model=CashflowImportPresets)
def save_cashflow_import_presets(body: CashflowImportPresets, session: Session = Depends(get_session)):
    return _call(cashflow_import.save_presets, session, body)


@router.get("/cashflow/category-rules", response_model=list[CashflowCategoryRuleItem])
def cashflow_category_rules(session: Session = Depends(get_session)):
    return cashflow_import.list_rules(session)


@router.post("/cashflow/category-rules", status_code=201, response_model=CashflowCategoryRuleItem)
def create_cashflow_category_rule(body: CashflowCategoryRuleCreate, session: Session = Depends(get_session)):
    return _call(cashflow_import.create_rule, session, body)


@router.delete("/cashflow/category-rules/{rule_id}", status_code=204)
def delete_cashflow_category_rule(rule_id: int, session: Session = Depends(get_session)):
    _call(cashflow_import.delete_rule, session, rule_id)


from app.modules.finance import recurring
from app.schema.cashflow_import_schema import (
    RecurringCashflowCreate,
    RecurringCashflowItem,
    RecurringDueItem,
    RecurringRecordInput,
)


@router.get("/recurring", response_model=list[RecurringCashflowItem])
def recurring_cashflows(session: Session = Depends(get_session)):
    return recurring.list_items(session)


@router.post("/recurring", status_code=201, response_model=RecurringCashflowItem)
def create_recurring_cashflow(body: RecurringCashflowCreate, session: Session = Depends(get_session)):
    return _call(recurring.create, session, body)


@router.put("/recurring/{item_id}", response_model=RecurringCashflowItem)
def update_recurring_cashflow(item_id: int, body: RecurringCashflowCreate, session: Session = Depends(get_session)):
    return _call(recurring.update, session, item_id, body)


@router.delete("/recurring/{item_id}", status_code=204)
def delete_recurring_cashflow(item_id: int, session: Session = Depends(get_session)):
    _call(recurring.delete, session, item_id)


@router.get("/recurring/due", response_model=list[RecurringDueItem])
def recurring_due(month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), session: Session = Depends(get_session)):
    return recurring.due(session, month)


@router.post("/recurring/{item_id}/record", status_code=201, response_model=RecurringDueItem)
def record_recurring_cashflow(item_id: int, body: RecurringRecordInput, session: Session = Depends(get_session)):
    return _call(recurring.record, session, item_id, body.month)


from app.modules.finance import check_in
from app.schema.cashflow_import_schema import BalanceCheckInInput, BalanceCheckInResult


@router.post("/balance-check-in", response_model=list[BalanceCheckInResult])
def balance_check_in(body: BalanceCheckInInput, session: Session = Depends(get_session)):
    return _call(check_in.check_in, session, body)
