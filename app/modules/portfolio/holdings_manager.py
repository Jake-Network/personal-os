"""Explicit user writes to Sheets; live cached quotes never become history."""
from datetime import timedelta

from sqlalchemy import select

from app.modules.auth.errors import GoogleOAuthError
from app.modules.auth.google_oauth_manager import google_oauth_manager
from app.modules.database.model.advisor import AuditLog
from app.modules.database.model.base import utcnow
from app.modules.database.model.portfolio import PortfolioSettings
from app.modules.portfolio import portfolio_manager as manager
from app.modules.portfolio.holdings import editable_row
from app.modules.portfolio.sheets import SheetsClient, TABS


def listing(session, client=None, cached=False):
    settings = manager.get_settings(session)
    result = {"rows": [], "portfolio": manager.portfolio(session), "settings": manager.settings_dict(session),
              "can_write": google_oauth_manager.status(session).get("can_write", False),
              "initialized": False, "warning": None}
    if not settings:
        return result
    if cached:
        imported = manager._latest(session)
        if imported:
            result["initialized"] = True
            records = imported.payload.get("Holdings", [])
            result["rows"] = [editable_row(row) for row in records]
        return result
    try:
        gateway = client or SheetsClient(session=session)
        layout = gateway.layout(settings.spreadsheet_id)
        result["initialized"] = all(tab in layout for tab in (*TABS, "Verification"))
        if result["initialized"]:
            records = gateway.holding_rows(settings.spreadsheet_id)
            result["rows"] = [editable_row(row) for row in records]
    except Exception:
        result["warning"] = "Unable to read current Sheets rows. Check Google connection and spreadsheet access."
    return result


def _writer(session, client):
    # Credential refresh may commit, so obtain it BEFORE acquiring the write lock.
    try:
        gateway = client or SheetsClient(session=session, require_write=True)
    except GoogleOAuthError as exc:
        raise RuntimeError(exc.code) from None
    identity = getattr(gateway, "source_identity", None)
    if not isinstance(identity, str):
        identity = manager._source(session)[0]
    settings = session.scalar(select(PortfolioSettings).where(PortfolioSettings.id == 1)
                              .with_for_update().execution_options(populate_existing=True))
    if settings is None:
        raise ValueError("Configure a spreadsheet first")
    current_identity, unavailable = manager._source(session)
    if current_identity != identity or unavailable:
        raise ValueError("Google connection changed; reconnect and retry")
    return gateway, settings, identity


def _record(session, settings, action, detail, identity):
    session.add(AuditLog(actor="user", action=action, target="sheets-holdings",
                         detail={"spreadsheet_id": settings.spreadsheet_id, "source_identity": identity, **detail}))
    session.commit()


def initialize(session, client=None):
    gateway, settings, identity = _writer(session, client)
    spreadsheet_id = settings.spreadsheet_id
    try:
        gateway.initialize(settings.spreadsheet_id)
        _record(session, settings, "sheets_initialize", {}, identity)
    except Exception as exc:
        session.rollback()
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Worksheet setup did not complete; inspect the spreadsheet and retry safely") from None
    try:
        if manager._source(session)[0] != identity or manager.get_settings(session).spreadsheet_id != spreadsheet_id:
            raise ValueError("Connection changed after initialization")
        warning = _synchronize(session, gateway)
    except Exception:
        session.rollback()
        warning = "Worksheets initialized; formula verification is pending. Retry refresh."
    result = listing(session, gateway)
    result["warning"] = warning or result["warning"]
    return result


def _synchronize(session, gateway):
    warning = None
    settings = manager.get_settings(session)
    identity = getattr(gateway, "source_identity", None) or manager._source(session)[0]
    if not settings.verified_at or settings.verified_identity != identity:
        try:
            manager.verify(session, gateway)
        except ValueError:
            warning = "Current GOOGLEFINANCE values are pending verification; automatic prices remain unavailable."
    try:
        manager.sync(session, gateway)
    except ValueError:
        warning = "Saved data could not yet synchronize; the previous import is retained. Retry refresh."
    return warning


def save(session, body, client=None):
    gateway, settings, identity = _writer(session, client)
    spreadsheet_id = settings.spreadsheet_id
    if body.request_id:
        receipts = session.scalars(select(AuditLog).where(AuditLog.action == "sheets_holding_upsert",
                                                        AuditLog.detail["request_id"].as_string() == body.request_id).order_by(AuditLog.id.desc()))
        for receipt in receipts:
            detail = receipt.detail
            if (detail.get("request_id") == body.request_id and detail.get("spreadsheet_id") == settings.spreadsheet_id
                    and detail.get("source_identity") == identity):
                if detail.get("input") != body.model_dump(mode="json"):
                    session.rollback()
                    raise ValueError("Request ID already used for a different holding change")
                session.rollback()
                result = listing(session, gateway)
                result.update(saved=True, position_id=body.position_id, quote_status="pending", replayed=True)
                return result
    try:
        gateway.upsert_holding(settings.spreadsheet_id, body)
    except Exception as exc:
        session.rollback()
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Sheets write was not confirmed. Retry with the same position ID; do not create a new position.") from None
    # Keep app writers serialized through FX provisioning, then persist successful
    # save independently from quote recalculation and verification failures.
    warning = None
    try:
        gateway.ensure_current_fx(settings.spreadsheet_id, body.currency)
    except Exception:
        warning = "Holding saved; automatic FX setup is pending. Check the FX worksheet."
    try:
        _record(session, settings, "sheets_holding_upsert", {"position_id": body.position_id,
                                                          "request_id": body.request_id,
                                                          "input": body.model_dump(mode="json")}, identity)
    except Exception:
        session.rollback()
        warning = "Holding saved in Sheets but local audit recording failed. Retry with the same position ID."
    try:
        current_settings = manager.get_settings(session)
        if manager._source(session)[0] != identity or current_settings.spreadsheet_id != spreadsheet_id:
            raise ValueError("Connection changed after save")
        sync_warning = _synchronize(session, gateway)
    except Exception:
        session.rollback()
        sync_warning = "Holding saved; quote synchronization is pending. Retry refresh."
    result = listing(session, gateway)
    line = next((row for row in result["portfolio"]["lines"]
                 if row.get("kind") == "holding" and row.get("id") == body.position_id), None)
    pending = bool(sync_warning or warning) or line is None or line.get("value_krw") is None
    result.update(saved=True, position_id=body.position_id, quote_status="pending" if pending else "ready",
                  warning=warning or sync_warning or result["warning"])
    return result


def refresh(session, client=None):
    gateway, identity = manager._gateway(session, client)
    settings = manager._configured(session)
    manager._confirm_source(session, identity, settings.spreadsheet_id)
    if settings.last_sync_at and utcnow() - settings.last_sync_at < timedelta(seconds=60):
        session.rollback()
        result = listing(session, gateway, cached=True)
        result["refresh_after_seconds"] = 60
        return result
    warning = _synchronize(session, gateway)
    result = listing(session, gateway)
    result["warning"] = warning or result["warning"]
    return result
