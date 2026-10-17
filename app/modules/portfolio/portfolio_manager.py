"""Deterministic Decimal valuations and append-only month-end evidence."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.modules.database.model.base import utcnow
from app.modules.database.model.portfolio import MonthlySnapshot, PortfolioImport, PortfolioSettings
from app.modules.portfolio.sheets import SheetsClient

KINDS = ("cash", "holding", "liability", "other")
TABS = {"Cash": "cash", "Holdings": "holding", "Liabilities": "liability", "OtherAssets": "other"}


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
    return portfolio(session)


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


def _decimal(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 <= result < Decimal(
            "1e20") and result.as_tuple().exponent >= -12 else None
    except InvalidOperation:
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _coverage(tables, month):
    rows = [r for r in tables.get("Coverage", []) if r.get("month") == month]
    if len(rows) != 1:
        return []
    return [k for k in KINDS if str(rows[0].get(k, "")).lower() == "true"]


def _string(value):
    with localcontext() as context:
        context.prec = 100
        return str(value.quantize(Decimal("0.01"))) if value is not None else None


def _value(rows, coverage, end, verified, historical=False):
    with localcontext() as context:
        context.prec = 100  # capped operands (<1e20), products and up to 10k rows
        return _calculate(rows, coverage, end, verified, historical)


def _calculate(rows, coverage, end, verified, historical=False):
    sums = {kind: Decimal(0) for kind in KINDS}
    complete = {kind: kind in coverage for kind in KINDS}
    issues = [f"Missing explicit {kind} coverage" for kind in KINDS if kind not in coverage]
    lines = []
    classes = {}
    seen = set()
    for row in rows:
        line = dict(row)
        line.setdefault("id", "")
        line.setdefault("label", row.get("id", "Unnamed position"))
        line.setdefault("currency", "")
        for field in ("balance", "quantity", "avg_cost", "price"):
            parsed = _decimal(row.get(field))
            line[field] = format(parsed, "f") if parsed is not None else None
        kind = row.get("kind")
        problems = []
        if kind not in KINDS:
            issues.append("Unknown position kind")
            complete = {k: False for k in KINDS}
            continue
        key = (kind, row.get("id"))
        if not row.get("id") or key in seen:
            problems.append("Missing or duplicate position ID")
        seen.add(key)
        currency = row.get("currency", "")
        if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
            problems.append("Invalid currency")
        as_of = _date(row.get("as_of"))
        if as_of is None or as_of > end or (historical and as_of != end):
            problems.append(
                "Missing month-end balance/quantity evidence" if historical else "Missing or future balance date")
        elif not historical and (end - as_of).days > 3:
            problems.append("Stale balance/quantity")
        fx = Decimal(1) if currency == "KRW" else _decimal(row.get("fx_rate"))
        fx_date = end if currency == "KRW" else _date(row.get("fx_as_of"))
        if fx is None or fx <= 0 or fx_date is None or fx_date > end:
            problems.append("Missing or invalid FX evidence")
            fx = None
        elif (end - fx_date).days > 7:
            problems.append("Stale FX rate")
        native = _decimal(row.get("balance"))
        gain = None
        if kind == "holding":
            quantity = _decimal(row.get("quantity"))
            price = _decimal(row.get("price"))
            price_date = _date(row.get("price_as_of"))
            if quantity is None:
                problems.append("Missing quantity")
            if price is None or price_date is None or price_date > end:
                problems.append("Missing applicable close/price")
                price = None
            elif not historical and (end - price_date).days > 7:
                problems.append("Stale price; latest valid market close unconfirmed")
            if historical and (_date(row.get("close_valid_through")) is None
                               or _date(row.get("close_valid_through")) < end or not row.get("source")):
                problems.append("Last valid month-end market close unconfirmed")
            if row.get("source") == "googlefinance" and (historical or not verified):
                problems.append("GOOGLEFINANCE API values have not been verified")
                price = None
            native = quantity * price if quantity is not None and price is not None else None
            cost = _decimal(row.get("avg_cost"))
            if native is not None and cost is not None and fx is not None:
                gain = (native - quantity * cost) * fx
        if row.get("fx_source") == "googlefinance" and (historical or not verified):
            problems.append("GOOGLEFINANCE FX values have not been verified")
            fx = None
        value = native * fx if native is not None and fx is not None else None
        if value is None:
            problems.append("Valuation unavailable")
        # Invalid identity/date evidence must never contribute a confirmed total.
        if problems:
            complete[kind] = False
            issues.extend(f"{row.get('label') or row.get('id')}: {problem}" for problem in problems)
        if value is not None:
            sums[kind] += value
            if kind == "holding":
                asset_class = row.get("asset_class") or "unknown"
                if asset_class not in ("equity", "etf", "bond", "crypto", "other"):
                    asset_class = "unknown"
                classes[asset_class] = classes.get(asset_class, Decimal(0)) + value
        line.update(value_krw=_string(value), unrealized_gain_krw=_string(gain),
                    fx_rate=format(fx, "f") if fx is not None else None,
                    fx_as_of=fx_date.isoformat() if fx_date else None, issues=problems)
        lines.append(line)
    assets_complete = all(complete[k] for k in ("cash", "holding", "other"))
    assets = sum((sums[k] for k in ("cash", "holding", "other")), Decimal(0)) if assets_complete else None
    liabilities = sums["liability"] if complete["liability"] else None
    return {"lines": lines, "complete": all(complete.values()), "issues": issues,
            "total_assets": _string(assets), "total_liabilities": _string(liabilities),
            "net_worth": _string(assets - liabilities) if assets is not None and liabilities is not None else None,
            "cash": _string(sums["cash"]) if complete["cash"] else None,
            "investments": _string(sums["holding"]) if complete["holding"] else None,
            "allocation": {"cash": _string(sums["cash"]) if complete["cash"] else None,
                           "investments": _string(sums["holding"]) if complete["holding"] else None,
                           "other": _string(sums["other"]) if complete["other"] else None},
            "by_asset_class": {k: _string(v) for k, v in classes.items()} if complete["holding"] else {},
            "stock_value": _string(classes.get("equity", Decimal(0))) if complete[
                                                                             "holding"] and "unknown" not in classes else None,
            "rows": rows, "coverage": coverage}


def _latest_evidence(rows, key, value, end, amount_key="rate"):
    eligible = [r for r in rows if r.get(key) == value and _date(r.get("as_of")) is not None
                and _date(r.get("as_of")) <= end and _decimal(r.get(amount_key)) is not None
                and _decimal(r.get(amount_key)) > 0]
    if not eligible:
        return {}
    latest = max(eligible, key=lambda r: _date(r["as_of"]))
    same_date = [r for r in eligible if _date(r["as_of"]) == _date(latest["as_of"])]
    if any(r != latest for r in same_date):
        return {}  # Conflicting records must never silently choose a value.
    return latest


def _enrich(rows, tables, end, historical):
    result = []
    for original in rows:
        row = dict(original)
        rates = tables.get("FX", [])
        if historical:
            # Current formula rates are observations, never historical close evidence.
            rates = [rate for rate in rates if rate.get("source") != "googlefinance"]
        fx = _latest_evidence(rates, "currency", row.get("currency"), end)
        row.update(fx_rate=fx.get("rate"), fx_as_of=fx.get("as_of"), fx_source=fx.get("source"))
        if historical and row.get("kind") == "holding":
            closes = [c for c in tables.get("Closes", []) if c.get("currency") == row.get("currency")]
            close = _latest_evidence(closes, "ticker", row.get("ticker"), end, "price")
            # Historical GOOGLEFINANCE API arrays cannot supply close evidence.
            if close.get("source") == "googlefinance":
                close = {}
            row.update(price=close.get("price"), price_as_of=close.get("as_of"), source=close.get("source"),
                       close_valid_through=close.get("valid_through"))
        result.append(row)
    return result


def portfolio(session):
    imported = _latest(session)
    obj = get_settings(session)
    if not imported:
        result = _value([], [], date.today(), False)
        return dict(result, synced_at=None, stale=True, import_id=None)
    tables = imported.payload
    rows = [dict(row, kind=kind) for tab, kind in TABS.items() for row in tables.get(tab, [])]
    rows = _enrich(rows, tables, date.today(), False)
    identity, disconnected = _source(session)
    verified = bool(obj.verified_at) and (obj.verified_identity or "adc") == identity and not disconnected
    result = _value(rows, _coverage(tables, "current"), date.today(), verified)
    stale = utcnow() - imported.created_at > timedelta(hours=24) or any(line["issues"] for line in result["lines"])
    return dict(result, synced_at=imported.created_at.isoformat(), stale=bool(stale or obj.last_error or disconnected),
                import_id=imported.id)


def _month_end(month):
    if month.day != 1:
        raise ValueError("month must be the first day of a calendar month")
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if end >= date.today():
        raise ValueError("Only completed calendar months can be snapshotted")
    return end


def snapshot_dict(obj):
    return dict(obj.payload, id=obj.id, month=obj.month.isoformat(), revision=obj.revision,
                supersedes_id=obj.supersedes_id, created_at=obj.created_at.isoformat(), reason=obj.reason,
                import_id=obj.import_id)


def create_snapshot(session, month):
    end = _month_end(month)
    existing = session.scalar(select(MonthlySnapshot).where(MonthlySnapshot.month == month)
                              .order_by(MonthlySnapshot.revision.desc()).limit(1))
    if existing:
        return snapshot_dict(existing)
    imported = _latest(session)
    if not imported:
        raise ValueError("Sync explicit historical evidence first")
    rows = [r for r in imported.payload.get("History", []) if r.get("month") == month.strftime("%Y-%m")]
    rows = _enrich(rows, imported.payload, end, True)
    payload = _value(rows, _coverage(imported.payload, month.strftime("%Y-%m")), end, False, True)
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
    end = _month_end(prior.month)
    rows = [r.model_dump(mode="json") for r in body.rows]
    payload = _value(rows, body.coverage, end, True, True)
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
    with localcontext() as context:
        context.prec = 100
        return _history(session, period)


def _history(session, period="all"):
    if period not in ("all", "6m", "1y"):
        raise ValueError("Unknown history period")
    records = session.scalars(select(MonthlySnapshot).order_by(MonthlySnapshot.month, MonthlySnapshot.revision)).all()
    latest = {s.month: s for s in records}
    today = date.today().replace(day=1)
    cutoff = None
    if period != "all":
        months = 6 if period == "6m" else 12
        n = today.year * 12 + today.month - 1 - months
        cutoff = date(n // 12, n % 12 + 1, 1)
    snapshots = []
    previous = None
    for month, obj in sorted(latest.items()):
        data = snapshot_dict(obj)
        try:
            curr = Decimal(data["net_worth"]) if data.get("net_worth") is not None else None
        except InvalidOperation:
            curr = None
        prev = Decimal(previous["net_worth"]) if previous and previous.get("net_worth") is not None else None
        adjacent = previous and (month.year * 12 + month.month - (
                    previous["month_date"].year * 12 + previous["month_date"].month)) == 1
        change = curr - prev if adjacent and curr is not None and prev is not None else None
        data["change_krw"] = _string(change)
        data["change_pct"] = _string(change / prev * 100) if change is not None and prev > 0 else None
        previous = dict(data, month_date=month)
        if cutoff is None or month >= cutoff:
            snapshots.append(data)
    start = cutoff or min(latest, default=today)
    missing = []
    while start < today:
        if start not in latest:
            missing.append(start.isoformat())
        n = start.year * 12 + start.month
        start = date(n // 12, n % 12 + 1, 1)
    return {"snapshots": snapshots, "missing_months": missing}
