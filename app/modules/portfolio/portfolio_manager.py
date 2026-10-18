"""Sheets sync, stored imports and append-only month-end snapshots."""
from datetime import date, timedelta

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.modules.database.model.base import utcnow
from app.modules.database.model.portfolio import MonthlySnapshot, PortfolioImport, PortfolioSettings
from app.modules.portfolio.sheets import SheetsClient
from app.modules.portfolio.snapshots import history_view, month_end, snapshot_dict
from app.modules.portfolio.valuation import TABS, coverage_kinds, enrich_rows, value_positions


def _source(session):
    from app.modules.auth.google_oauth_manager import google_oauth_manager
    identity = google_oauth_manager.source_identity(session)
    status = google_oauth_manager.status(session)
    return identity, status.get("status") not in (None, "not_connected", "connected", "unconfigured")


def get_settings(session):
    return session.get(PortfolioSettings, 1)


def _gateway(session, client):
    gateway = client or SheetsClient(session=session)
    identity = getattr(gateway, "source_identity", None)
    return gateway, identity if isinstance(identity, str) else _source(session)[0]


def _confirm_source(session, identity, spreadsheet_id):
    # A network read must not become proof for a concurrently selected sheet/user.
    session.expire_all()
    current_settings = session.scalar(select(PortfolioSettings).where(PortfolioSettings.id == 1)
                                      .with_for_update().execution_options(populate_existing=True))
    current_identity, unavailable = _source(session)
    if unavailable or current_identity != identity or current_settings.spreadsheet_id != spreadsheet_id:
        raise ValueError("Google connection or spreadsheet changed during retrieval; retry")


def settings_dict(session):
    obj = get_settings(session)
    return {k: getattr(obj, k) if obj else None for k in
            ("spreadsheet_id", "verified_at", "last_sync_at", "last_success_at", "last_error")}


def configure(session, spreadsheet_id):
    obj = get_settings(session)
    if not obj:
        obj = PortfolioSettings(id=1, spreadsheet_id=spreadsheet_id)
        session.add(obj)
    elif obj.spreadsheet_id != spreadsheet_id:
        obj.spreadsheet_id = spreadsheet_id
        obj.verified_at = obj.verification = obj.last_success_at = obj.last_sync_at = obj.last_error = None
        obj.verified_identity = None
    session.commit()
    return settings_dict(session)


def _configured(session):
    obj = get_settings(session)
    if not obj:
        raise ValueError("Configure a spreadsheet first")
    return obj


def verify(session, client=None):
    obj = _configured(session)
    spreadsheet_id = obj.spreadsheet_id
    try:
        gateway, identity = _gateway(session, client)
        proof = gateway.verify(spreadsheet_id)
        _confirm_source(session, identity, spreadsheet_id)
        obj.verified_at, obj.verification, obj.last_error = utcnow(), proof, None
        obj.verified_identity = identity
        session.commit()
    except Exception:
        obj.verified_at = obj.verification = None
        obj.verified_identity = None
        obj.last_error = "Current GOOGLEFINANCE verification failed; inspect server configuration and Verification cells."
        session.commit()
        raise ValueError(obj.last_error) from None
    return settings_dict(session)


def sync(session, client=None):
    obj = _configured(session)
    spreadsheet_id = obj.spreadsheet_id
    try:
        gateway, identity = _gateway(session, client)
        tables = gateway.tables(spreadsheet_id)
        _confirm_source(session, identity, spreadsheet_id)
        # Import is atomic: no partial replacement when any tab cannot be fetched.
        if any(tab not in tables for tab in (*TABS, "FX", "Closes", "History", "Coverage")):
            raise ValueError("Missing worksheet")
        session.add(
            PortfolioImport(spreadsheet_id=spreadsheet_id, source_identity=identity, payload=tables))
        obj.last_sync_at = utcnow()
        obj.last_success_at, obj.last_error = utcnow(), None
        session.commit()
    except Exception:
        session.rollback()
        obj = _configured(session)
        obj.last_sync_at = utcnow()
        obj.last_error = "Sheets synchronization failed; previous successful import retained. Check worksheet layout and server access."
        session.commit()
        raise ValueError(obj.last_error) from None
    return imported_portfolio_preview(session)


def _latest(session):
    obj = get_settings(session)
    if not obj:
        return None
    identity, _ = _source(session)
    identity_filter = PortfolioImport.source_identity == identity
    if identity == "adc":
        identity_filter = or_(identity_filter, PortfolioImport.source_identity.is_(None))
    return session.scalar(select(PortfolioImport).where(PortfolioImport.spreadsheet_id == obj.spreadsheet_id)
                          .where(identity_filter)
                          .order_by(PortfolioImport.id.desc()).limit(1))


def portfolio(session):
    from app.modules.portfolio.local_portfolio import portfolio as local_portfolio
    return local_portfolio(session)


def imported_portfolio_preview(session):
    imported = _latest(session)
    obj = get_settings(session)
    if not imported:
        result = value_positions([], [], date.today(), False)
        return dict(result, synced_at=None, stale=True, import_id=None)
    tables = imported.payload
    rows = [dict(row, kind=kind) for tab, kind in TABS.items() for row in tables.get(tab, [])]
    rows = enrich_rows(rows, tables, date.today(), False)
    identity, disconnected = _source(session)
    verified = bool(obj.verified_at) and (obj.verified_identity or "adc") == identity and not disconnected
    result = value_positions(rows, coverage_kinds(tables, "current"), date.today(), verified)
    stale = utcnow() - imported.created_at > timedelta(hours=24) or any(line["issues"] for line in result["lines"])
    return dict(result, synced_at=imported.created_at.isoformat(), stale=bool(stale or obj.last_error or disconnected),
                import_id=imported.id)


def create_snapshot(session, month):
    end = month_end(month, date.today())
    existing = session.scalar(select(MonthlySnapshot).where(MonthlySnapshot.month == month)
                              .order_by(MonthlySnapshot.revision.desc()).limit(1))
    if existing:
        return snapshot_dict(existing)
    imported = _latest(session)
    if not imported:
        raise ValueError("Sync explicit historical evidence first")
    rows = [r for r in imported.payload.get("History", []) if r.get("month") == month.strftime("%Y-%m")]
    rows = enrich_rows(rows, imported.payload, end, True)
    payload = value_positions(rows, coverage_kinds(imported.payload, month.strftime("%Y-%m")), end, False, True)
    obj = MonthlySnapshot(month=month, revision=1, import_id=imported.id, reason="Initial month-end snapshot",
                          payload=payload)
    session.add(obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        obj = session.scalar(select(MonthlySnapshot).where(MonthlySnapshot.month == month)
                             .order_by(MonthlySnapshot.revision.desc()).limit(1))
        if obj is None:
            raise
    return snapshot_dict(obj)


def correct_snapshot(session, snapshot_id, body):
    prior = session.get(MonthlySnapshot, snapshot_id)
    if prior is None:
        raise LookupError("Snapshot not found")
    latest = session.scalar(select(MonthlySnapshot).where(MonthlySnapshot.month == prior.month)
                            .order_by(MonthlySnapshot.revision.desc()).limit(1))
    if latest.id != prior.id:
        raise RuntimeError("Snapshot has a newer revision; reload before correcting")
    end = month_end(prior.month, date.today())
    rows = [r.model_dump(mode="json") for r in body.rows]
    payload = value_positions(rows, body.coverage, end, True, True)
    obj = MonthlySnapshot(month=prior.month, revision=prior.revision + 1, supersedes_id=prior.id,
                          import_id=prior.import_id, reason=body.reason, payload=payload)
    session.add(obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RuntimeError("Concurrent correction detected; reload before correcting") from None
    return snapshot_dict(obj)


def audit(session, snapshot_id):
    obj = session.get(MonthlySnapshot, snapshot_id)
    if obj is None:
        raise LookupError("Snapshot not found")
    return [snapshot_dict(s) for s in session.scalars(select(MonthlySnapshot).where(MonthlySnapshot.month == obj.month)
                                                      .order_by(MonthlySnapshot.revision))]


def history(session, period="all"):
    records = session.scalars(select(MonthlySnapshot).order_by(MonthlySnapshot.month, MonthlySnapshot.revision)).all()
    return history_view(records, date.today(), period)


