"""Public quote observations and explicit migration from preserved legacy imports."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy import select, update

from app.modules.database.model import (
    FxRate,
    Holding,
    LocalPosition,
    MarketObservation,
    MarketSettings,
    PortfolioImport,
)
from app.modules.database.model.base import utcnow
from app.modules.portfolio.quotes_sheet import QuotesSheet, quote_rows
from app.modules.portfolio.valuation import parse_decimal


def _account_key(identity):
    return hashlib.sha256(identity.encode()).hexdigest()


def status(session):
    from app.modules.portfolio.portfolio_manager import _source

    identity = _source(session)[0]
    obj = session.get(MarketSettings, 1)
    return {
        "source": "local",
        "configured": obj is not None,
        "account_matches": obj.source_identity == identity if obj else False,
        "current_account_key": _account_key(identity),
        "spreadsheet_id": obj.spreadsheet_id if obj else None,
        "last_attempt_at": obj.last_attempt_at.isoformat()
        if obj and obj.last_attempt_at
        else None,
        "last_success_at": obj.last_success_at.isoformat()
        if obj and obj.last_success_at
        else None,
        "last_error": obj.last_error if obj else None,
        "external_data": "Only exchange-qualified tickers, currency pairs and quote formulas are sent to Google. Google can retain this ticker list.",
        "refresh_seconds": 300,
    }


def initialize(session, client=None):
    gateway = client or QuotesSheet(session)
    existing = session.get(MarketSettings, 1)
    if existing:
        if existing.source_identity != gateway.source_identity:
            raise ValueError("Google account changed; explicitly replace the quotes connection")
        return status(session)
    obj = MarketSettings(
        id=1, spreadsheet_id=gateway.create(), source_identity=gateway.source_identity
    )
    session.add(obj)
    session.commit()
    return status(session)


def replace(session, body, client=None):
    from app.modules.portfolio.portfolio_manager import _source

    principal = _source(session)[0]
    if body.expected_account_key != _account_key(principal):
        raise RuntimeError("Google account changed; reload before replacing the quotes connection")
    existing = session.get(MarketSettings, 1)
    if existing is None or existing.spreadsheet_id != body.expected_spreadsheet_id:
        raise RuntimeError("Quotes connection changed; reload before replacing it")
    old_identity = existing.source_identity
    gateway = client or QuotesSheet(session)
    if gateway.source_identity != principal:
        raise RuntimeError("Google account changed before quotes file creation")
    spreadsheet_id = gateway.create()
    session.expire_all()
    if _source(session)[0] != principal:
        raise RuntimeError("Google account changed during quotes file creation; connection retained")
    changed = session.execute(
        update(MarketSettings)
        .where(
            MarketSettings.id == 1,
            MarketSettings.spreadsheet_id == body.expected_spreadsheet_id,
            MarketSettings.source_identity == old_identity,
        )
        .values(
            spreadsheet_id=spreadsheet_id,
            source_identity=principal,
            last_attempt_at=None,
            last_success_at=None,
            last_error=None,
        )
    )
    if changed.rowcount != 1:
        session.rollback()
        raise RuntimeError("Quotes connection changed during file creation; reload before replacing it")
    session.commit()
    return status(session)


def _observation(session, symbol, currency, provider, payload):
    fingerprint = hashlib.sha256(
        json.dumps([symbol, currency, provider, payload], sort_keys=True).encode()
    ).hexdigest()
    if session.scalar(
        select(MarketObservation.id).where(MarketObservation.fingerprint == fingerprint)
    ):
        return False
    session.add(
        MarketObservation(
            symbol=symbol,
            currency=currency,
            provider=provider,
            payload=payload,
            fingerprint=fingerprint,
        )
    )
    return True


def _trade_time(value):
    # Sheets exposes spreadsheet serial dates. GOOGLEFINANCE trade times have no
    # timezone; force the dedicated file to UTC when created, then interpret as UTC.
    if isinstance(value, (int, float)) and 1 < value < 100000:
        return datetime(1899, 12, 30, tzinfo=UTC) + timedelta(days=float(value))
    raise ValueError("Missing market trade time")


def _lock_refresh_result(session, principal, identity, spreadsheet_id, attempt_at):
    from app.modules.portfolio.portfolio_manager import _source

    session.expire_all()
    if _source(session)[0] != principal:
        raise ValueError("Google connection changed during retrieval")
    claimed = session.execute(
        update(MarketSettings)
        .where(
            MarketSettings.id == 1,
            MarketSettings.source_identity == identity,
            MarketSettings.spreadsheet_id == spreadsheet_id,
            MarketSettings.last_attempt_at == attempt_at,
        )
        .values(last_attempt_at=attempt_at)
    )
    if claimed.rowcount != 1:
        raise ValueError("Quotes connection changed during retrieval")


def refresh(session, client=None):
    settings = session.get(MarketSettings, 1)
    if settings is None:
        return {
            "refresh_state": "not_connected",
            "warning": "시세 전용 Google 파일을 연결하세요. 로컬 보유 내역은 계속 편집할 수 있습니다."
        }
    now = utcnow()
    if settings.last_attempt_at and now - settings.last_attempt_at < timedelta(
        seconds=300
    ):
        remaining = max(
            1, ceil((settings.last_attempt_at + timedelta(seconds=300) - now).total_seconds())
        )
        message = f"시세를 새로 갱신하지 않았습니다. 조회 간격 제한으로 {remaining}초 후 다시 조회할 수 있습니다."
        if settings.last_error:
            message += f" 이전 조회: {settings.last_error}"
        return {"refresh_state": "cooldown", "refresh_after_seconds": remaining, "warning": message}
    from app.modules.portfolio.portfolio_manager import _source

    principal = _source(session)[0]
    gateway = client or QuotesSheet(
        session
    )  # credential refresh commits before taking job lock
    if gateway.source_identity != settings.source_identity:
        raise ValueError(
            "Google account changed; reconnect a new dedicated quotes file"
        )
    prior = settings.last_attempt_at
    spreadsheet_id = settings.spreadsheet_id
    claimed = session.execute(
        update(MarketSettings)
        .where(
            MarketSettings.id == 1,
            MarketSettings.last_attempt_at == prior,
            MarketSettings.spreadsheet_id == spreadsheet_id,
            MarketSettings.source_identity == gateway.source_identity,
        )
        .values(last_attempt_at=now)
    )
    if claimed.rowcount != 1:
        session.rollback()
        return {
            "refresh_state": "cooldown", "refresh_after_seconds": 300,
            "warning": "다른 시세 조회가 진행 중입니다. 잠시 후 다시 확인하세요.",
        }
    session.commit()  # claim survives network failure/restart and enforces common cooldown
    try:
        positions = session.scalars(
            select(Holding)
            .join(LocalPosition, LocalPosition.holding_id == Holding.id)
            .where(LocalPosition.quote_mode == "auto")
        ).all()
        # Keep immutable input versions across retrieval, even if ORM objects expire.
        position_versions = {h.id: h.updated_at for h in positions}
        symbols = {h.symbol for h in positions}
        currencies = {h.currency for h in positions}
        position_currencies = {
            symbol: {h.currency for h in positions if h.symbol == symbol}
            for symbol in symbols
        }
        expected = {r[0] for r in quote_rows(symbols)}
        quotes, fx = gateway.read(spreadsheet_id)
        session.expire_all()
        current_settings = session.get(MarketSettings, 1)
        if (
            _source(session)[0] != principal
            or current_settings is None
            or current_settings.source_identity != gateway.source_identity
            or current_settings.spreadsheet_id != spreadsheet_id
            or current_settings.last_attempt_at != now
        ):
            raise ValueError("Google connection changed during retrieval")
        existing = [r[0] for r in quotes if r]
        if len(set(existing)) != len(existing):
            raise ValueError("Duplicate quote rows")
        fx_keys = [row[0] for row in fx if row]
        if len(set(fx_keys)) != len(fx_keys):
            raise ValueError("Duplicate FX rows")
        if set(existing) != expected or {r[0] for r in fx if r} != {
            c + "KRW" for c in currencies if c != "KRW"
        }:
            gateway.provision(spreadsheet_id, symbols, currencies)
            _lock_refresh_result(session, principal, gateway.source_identity, spreadsheet_id, now)
            settings.last_error = (
                "시세 수식 계산 대기 중입니다. 다음 갱신에서 확인합니다."
            )
            session.commit()
            return {"refresh_state": "waiting", "warning": settings.last_error, "refresh_after_seconds": 300}
        # Serialize the result commit with replacement, after all network calls.
        _lock_refresh_result(session, principal, gateway.source_identity, spreadsheet_id, now)
        by_symbol = {r[0]: r for r in quotes if r}
        failures = []
        valid_count = 0
        for symbol in sorted(symbols):
            row = by_symbol.get(symbol, [])
            if (
                len(row) < 5
                or parse_decimal(row[1]) is None
                or parse_decimal(row[1]) <= 0
            ):
                raw = [str(v) for v in row]
                state = (
                    "unsupported"
                    if any(v.startswith("#N/A") for v in raw)
                    else "provider_error"
                    if any(v.startswith("#") for v in raw)
                    else "pending"
                )
                for currency in position_currencies[symbol]:
                    _observation(
                        session,
                        symbol,
                        currency,
                        "googlefinance_status",
                        {"state": state, "attempt_at": now.isoformat()},
                    )
                failures.append(
                    f"{symbol}: "
                    + (
                        "미지원 또는 조회 오류"
                        if any(str(v).startswith("#N/A") for v in row)
                        else "시세 계산 대기 또는 조회 오류"
                    )
                )
                continue  # calculation/error/unsupported: never overwrite a prior valid price
            invalid_reason = None
            trade = None
            try:
                trade = _trade_time(row[3])
            except ValueError:
                invalid_reason = "거래 시각을 확인할 수 없습니다"
            price = parse_decimal(row[1])
            currency = row[2]
            if currency not in position_currencies[symbol]:
                invalid_reason = "종목 통화와 시세 통화가 다릅니다"
            delay = parse_decimal(row[4])
            if delay is None:
                invalid_reason = "시세 지연 정보를 확인할 수 없습니다"
            if trade is not None and trade > now + timedelta(minutes=5):
                invalid_reason = "거래 시각이 미래입니다"
            if invalid_reason:
                failures.append(f"{symbol}: {invalid_reason}")
                for expected_currency in position_currencies[symbol]:
                    _observation(
                        session, symbol, expected_currency, "googlefinance_status",
                        {"state": "provider_error", "attempt_at": now.isoformat()},
                    )
                continue
            payload = {
                "state": "ready",
                "price": str(price),
                "trade_time": trade.isoformat(),
                "delay_minutes": str(delay),
            }
            valid_count += 1
            _observation(
                session,
                symbol,
                currency,
                "googlefinance_status",
                {"state": "ready", "attempt_at": now.isoformat()},
            )
            _observation(session, symbol, currency, "googlefinance", payload)
            # Recheck eligibility in the write itself: local edits made while Google
            # was responding must win, including switching to manual and back.
            for holding_id, input_version in position_versions.items():
                session.execute(
                    update(Holding)
                    .where(
                        Holding.id == holding_id,
                        Holding.updated_at == input_version,
                        Holding.symbol == symbol,
                        Holding.currency == currency,
                        (Holding.price_as_of.is_(None) | (Holding.price_as_of < trade)),
                        select(LocalPosition.holding_id)
                        .where(
                            LocalPosition.holding_id == Holding.id,
                            LocalPosition.quote_mode == "auto",
                        )
                        .exists(),
                    )
                    .values(last_price=price, price_as_of=trade)
                    .execution_options(synchronize_session=False)
                )
        for row in fx:
            if (
                len(row) != 2
                or not isinstance(row[0], str)
                or row[0] not in {c + "KRW" for c in currencies if c != "KRW"}
            ):
                continue
            rate = parse_decimal(row[1])
            if rate is None or rate <= 0:
                continue
            currency = row[0][:3]
            if _observation(
                session, row[0], "KRW", "googlefinance_fx", {"rate": str(rate)}
            ):
                session.add(FxRate(base=currency, quote="KRW", rate=rate, as_of=now))
        if valid_count:
            settings.last_success_at = now
        settings.last_error = "; ".join(failures) if failures else None
        session.commit()
    except Exception:
        session.rollback()
        warning = (
            "시세 조회 실패: 이전 관측값을 보존했습니다. 연결과 시트 상태를 확인하세요."
        )
        session.execute(
            update(MarketSettings)
            .where(
                MarketSettings.id == 1,
                MarketSettings.spreadsheet_id == spreadsheet_id,
                MarketSettings.source_identity == gateway.source_identity,
                MarketSettings.last_attempt_at == now,
            )
            .values(last_error=warning)
        )
        session.commit()
        return {"refresh_state": "failed", "warning": warning, "refresh_after_seconds": 300}
    missing = sorted(symbols - expected)
    return {
        "refresh_state": "failed" if failures or missing else "updated",
        "warning": f"자동 시세 미지원: {', '.join(missing)}. 날짜와 출처가 있는 수동 가격을 입력하세요."
        if missing
        else settings.last_error,
        "refresh_after_seconds": 300,
    }


def observations(session, symbol=None):
    query = select(MarketObservation).order_by(MarketObservation.id.desc()).limit(100)
    if symbol:
        query = query.where(MarketObservation.symbol == symbol)
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "currency": r.currency,
            "provider": r.provider,
            "observed_at": r.observed_at.isoformat(),
            **r.payload,
        }
        for r in session.scalars(query)
    ]


def import_preview(session, import_id):

    obj = session.get(PortfolioImport, import_id)
    if not obj:
        raise LookupError("Import not found")
    return _preview_import(session, obj, import_id)


def source_ref(obj, tab, row_id):
    return (
        "legacy:"
        + hashlib.sha256(
            json.dumps(
                [obj.spreadsheet_id, obj.source_identity, tab, row_id], sort_keys=True
            ).encode()
        ).hexdigest()
    )


def _preview_import(session, obj, import_id=None):
    from app.modules.database.model import FinanceImportMapping
    from app.modules.portfolio.valuation import parse_date

    result = []
    for tab, kind in (
        ("Cash", "cash"),
        ("Holdings", "holding"),
        ("Liabilities", "liability"),
        ("OtherAssets", "other"),
    ):
        seen = set()
        for row in obj.payload.get(tab, []):
            ref = source_ref(obj, tab, row.get("id"))
            errors = []
            if not row.get("id") or row.get("id") in seen:
                errors.append("Missing or duplicate position ID")
            seen.add(row.get("id"))
            amount = parse_decimal(
                row.get("quantity" if kind == "holding" else "balance")
            )
            if amount is None:
                errors.append("Missing or invalid quantity/balance")
            elif kind == "holding" and (
                amount < 0 or amount >= 10**20 or amount != amount.to_integral_value()
            ):
                errors.append("Quantity must be a nonnegative whole number below 1e20")
            if (
                not isinstance(row.get("currency"), str)
                or len(row["currency"]) != 3
                or not row["currency"].isalpha()
                or not row["currency"].isupper()
            ):
                errors.append("Invalid currency")
            if kind != "holding" and parse_date(row.get("as_of")) is None:
                errors.append("Missing balance date")
            if len(str(row.get("label") or row.get("id") or "")) > 120:
                errors.append("Label exceeds local storage limit of 120 characters")
            if kind == "holding" and len(str(row.get("ticker") or "")) > 32:
                errors.append("Ticker exceeds local storage limit of 32 characters")
            if kind == "holding" and not row.get("ticker"):
                errors.append("Missing ticker")
            if (
                kind == "holding"
                and row.get("account_id")
                and not any(
                    str(a.get("id")) == str(row["account_id"])
                    for a in obj.payload.get("Cash", [])
                )
            ):
                errors.append(
                    "Referenced source account is absent; include its row or remove the reference explicitly"
                )
            if (
                kind != "holding"
                and parse_decimal(row.get("balance")) is not None
                and parse_decimal(row["balance"]).as_tuple().exponent < -4
            ):
                errors.append(
                    "Balance exceeds local storage precision of 4 decimal places"
                )
            existing = session.get(FinanceImportMapping, ref)
            result.append(
                {
                    "kind": kind,
                    "row": row,
                    "source_ref": ref,
                    "existing_position_id": str(existing.record_id)
                    if existing
                    else None,
                    "issues": errors,
                }
            )
    return {
        "import_id": import_id,
        "rows": result,
        "preserved_history": True,
        "remote_data_remaining": True,
    }


def import_holdings(session, import_id):
    from app.modules.database.model import (
        Account,
        FinanceImportMapping,
        Liability,
        OtherAsset,
    )
    from app.modules.finance.value_history_manager import value_history_manager
    from app.modules.portfolio.holdings_manager import version
    from app.modules.portfolio.valuation import parse_date

    preview = import_preview(session, import_id)
    if any(r["issues"] for r in preview["rows"]):
        raise ValueError("Resolve import preview issues first")
    count = 0
    for entry in preview["rows"]:
        if entry["existing_position_id"]:
            continue
        row, kind = entry["row"], entry["kind"]
        common = dict(name=row.get("label") or row["id"], currency=row["currency"])
        if kind == "holding":
            obj = Holding(
                symbol=row["ticker"],
                quantity=parse_decimal(row["quantity"]),
                avg_cost=parse_decimal(row.get("avg_cost")),
                asset_class=row.get("asset_class") or "equity",
                **common,
            )
            if row.get("account_id"):
                original = session.get(PortfolioImport, import_id)
                account_mapping = session.get(
                    FinanceImportMapping,
                    source_ref(original, "Cash", str(row["account_id"])),
                )
                if account_mapping:
                    obj.account_id = account_mapping.record_id
            price, price_date = (
                parse_decimal(row.get("price")),
                parse_date(row.get("price_as_of")),
            )
            if (
                row.get("source") != "googlefinance"
                and price is not None
                and price_date is not None
            ):
                obj.last_price = price
                obj.price_as_of = datetime.combine(price_date, datetime.min.time(), UTC)
            table = "holdings"
        elif kind == "cash":
            obj = Account(
                kind="other",
                balance=parse_decimal(row["balance"]),
                balance_as_of=parse_date(row["as_of"]),
                is_liquid=False,
                **common,
            )
            table = "accounts"  # unknown liquidity must be explicitly classified later
        elif kind == "liability":
            obj = Liability(
                kind="other",
                balance=parse_decimal(row["balance"]),
                balance_as_of=parse_date(row["as_of"]),
                **common,
            )
            table = "liabilities"
        else:
            obj = OtherAsset(
                kind="other",
                value=parse_decimal(row["balance"]),
                value_as_of=parse_date(row["as_of"]),
                is_liquid=False,
                **common,
            )
            table = "other_assets"
        session.add(obj)
        session.flush()
        session.add(
            FinanceImportMapping(
                source_ref=entry["source_ref"], table_name=table, record_id=obj.id
            )
        )
        if kind == "holding":
            identifier = (
                "import-"
                + hashlib.sha256(entry["source_ref"].encode()).hexdigest()[:32]
            )
            session.add(
                LocalPosition(
                    position_id=identifier,
                    holding_id=obj.id,
                    quote_mode="auto"
                    if row.get("source") == "googlefinance"
                    else "manual",
                    version=version(obj),
                    source_ref=entry["source_ref"],
                )
            )
        if table in {"accounts", "holdings"}:
            value_history_manager.record(session, table, obj, None, "create")
        count += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise RuntimeError("Import conflict; reload preview and retry") from None
    return {
        "imported": count,
        "import_id": import_id,
        "preserved_history": True,
        "remote_data_remaining": True,
    }


def _csv_import(body):
    import csv
    import io

    reader = csv.DictReader(io.StringIO(body.csv_text))
    allowed = {
        "kind",
        "id",
        "label",
        "currency",
        "quantity",
        "avg_cost",
        "ticker",
        "as_of",
        "balance",
        "price",
        "price_as_of",
        "source",
        "asset_class",
        "account_id",
        "account_label",
    }
    if (
        not reader.fieldnames
        or len(reader.fieldnames) != len(set(reader.fieldnames))
        or set(reader.fieldnames) - allowed
        or not {"kind", "id", "currency"} <= set(reader.fieldnames)
    ):
        raise ValueError(
            "CSV requires unique kind,id,currency headers and supported financial fields"
        )
    tabs = {
        "cash": "Cash",
        "holding": "Holdings",
        "liability": "Liabilities",
        "other": "OtherAssets",
    }
    tables = {tab: [] for tab in tabs.values()}
    for index, row in enumerate(reader):
        if index >= 10000:
            raise ValueError("CSV import is limited to 10000 rows")
        if None in row or row.get("kind") not in tabs:
            raise ValueError(f"Invalid CSV row {index + 2}")
        tables[tabs[row.pop("kind")]].append(row)
    return PortfolioImport(
        spreadsheet_id="csv:" + body.source_id,
        source_identity="local_csv",
        payload=tables,
    )


def csv_preview(session, body):
    obj = _csv_import(body)
    result = _preview_import(session, obj)
    return {**result, "source_id": body.source_id, "remote_data_remaining": False}


def csv_import(session, body):
    obj = _csv_import(body)
    preview = _preview_import(session, obj)
    if any(r["issues"] for r in preview["rows"]):
        raise ValueError("Resolve CSV preview issues before importing")
    existing = session.scalar(
        select(PortfolioImport)
        .where(
            PortfolioImport.spreadsheet_id == obj.spreadsheet_id,
            PortfolioImport.source_identity == "local_csv",
        )
        .order_by(PortfolioImport.id)
    )
    if existing:
        if existing.payload != obj.payload:
            raise RuntimeError(
                "CSV source ID already used for different data; use a new source ID for a separate import"
            )
        obj = existing
    else:
        session.add(obj)
        session.flush()
    result = import_holdings(session, obj.id)
    return {**result, "remote_data_remaining": False}
