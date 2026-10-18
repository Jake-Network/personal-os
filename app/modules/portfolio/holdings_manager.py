"""Local holdings writes; Google receives public symbols only through market_data."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.database.model import (
    Account,
    AuditLog,
    Holding,
    HoldingWriteReceipt,
    LocalPosition,
    MarketObservation,
)
from app.modules.finance.value_history import capture
from app.modules.finance.formatting import quantity_text
from app.modules.finance.value_history_manager import value_history_manager
from app.modules.portfolio import portfolio_manager as manager


def version(obj):
    def stable(value):
        return (
            format(value.normalize(), "f") if isinstance(value, Decimal) else str(value)
        )

    data = {
        k: stable(getattr(obj, k))
        for k in (
            "symbol",
            "name",
            "currency",
            "quantity",
            "avg_cost",
            "asset_class",
            "last_price",
            "price_as_of",
            "updated_at",
        )
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def listing(session, client=None, cached=False):
    mappings = {p.holding_id: p for p in session.scalars(select(LocalPosition))}
    states = {}
    for observation in session.scalars(
        select(MarketObservation)
        .where(MarketObservation.provider == "googlefinance_status")
        .order_by(MarketObservation.id)
    ):
        states[(observation.symbol, observation.currency)] = observation.payload.get(
            "state", "ready"
        )
    rows = []
    for obj in session.scalars(select(Holding).order_by(Holding.id)):
        p = mappings.get(obj.id)
        rows.append(
            dict(
                position_id=p.position_id if p else str(obj.id),
                id=p.position_id if p else str(obj.id),
                quote_status=states.get((obj.symbol, obj.currency), "pending")
                if p and p.quote_mode == "auto"
                else "ready"
                if obj.last_price is not None
                else "pending",
                record_id=obj.id,
                account_id=obj.account_id,
                expected_version=version(obj),
                ticker=obj.symbol,
                label=obj.name or obj.symbol,
                currency=obj.currency,
                quantity=quantity_text(obj.quantity),
                avg_cost=str(obj.avg_cost) if obj.avg_cost is not None else None,
                asset_class=obj.asset_class,
                quote_mode=p.quote_mode if p else "manual",
                manual_price=str(obj.last_price)
                if obj.last_price is not None
                else None,
                price_as_of=obj.price_as_of.date().isoformat()
                if obj.price_as_of
                else None,
            )
        )
    return dict(
        rows=rows,
        portfolio=manager.portfolio(session),
        settings=manager.settings_dict(session),
        can_write=True,
        initialized=True,
        warning=None,
        source="local",
    )


def save(session, body, client=None):
    if body.account_id is not None and session.get(Account, body.account_id) is None:
        raise ValueError("Account not found")
    data = body.model_dump(mode="json")
    if body.request_id:
        receipt = session.get(HoldingWriteReceipt, body.request_id)
        if receipt:
            if receipt.payload != data:
                raise ValueError(
                    "Request ID already used for a different holding change"
                )
            return dict(
                listing(session),
                saved=True,
                position_id=body.position_id,
                replayed=True,
                quote_status="pending",
            )
    mapping = session.scalar(
        select(LocalPosition)
        .where(LocalPosition.position_id == body.position_id)
        .with_for_update()
    )
    obj = (
        session.scalar(
            select(Holding)
            .where(Holding.id == mapping.holding_id)
            .execution_options(populate_existing=True)
        )
        if mapping
        else None
    )
    if obj is None and body.position_id.isdigit():
        obj = session.get(Holding, int(body.position_id))
    if obj is not None:
        current = version(obj)
        if not body.expected_version or body.expected_version != current:
            raise RuntimeError("Holding changed; reload before saving")
        # Atomic compare-and-swap also protects SQLite, where FOR UPDATE is ignored.
        from sqlalchemy import update

        prior_time = obj.updated_at
        changed = session.execute(
            update(Holding)
            .where(Holding.id == obj.id, Holding.updated_at == prior_time)
            .values(updated_at=datetime.now(UTC))
        )
        if changed.rowcount != 1:
            session.rollback()
            raise RuntimeError("Concurrent holding update; reload")
        before = capture("holdings", obj)
    else:
        if body.expected_version:
            raise RuntimeError("Holding no longer exists; reload")
        obj = Holding()
        before = None
    if body.request_id:
        session.add(HoldingWriteReceipt(request_id=body.request_id, payload=data))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            receipt = session.get(HoldingWriteReceipt, body.request_id)
            if receipt and receipt.payload == data:
                return dict(
                    listing(session),
                    saved=True,
                    position_id=body.position_id,
                    replayed=True,
                    quote_status="pending",
                )
            raise RuntimeError("Concurrent request ID collision; reload") from None
    invalidate_price = (
        obj.symbol != body.ticker
        or obj.currency != body.currency
        or (mapping.quote_mode if mapping else "manual") != body.quote_mode
    )
    obj.symbol, obj.name, obj.currency = body.ticker, body.label, body.currency
    if "account_id" in body.model_fields_set:
        obj.account_id = body.account_id
    obj.quantity, obj.avg_cost, obj.asset_class = (
        body.quantity,
        body.avg_cost,
        body.asset_class,
    )
    # Switching the symbol or quote mode must not retain an unrelated old price.
    if body.quote_mode == "manual":
        obj.last_price = body.manual_price
        obj.price_as_of = datetime.combine(
            body.price_as_of, datetime.min.time(), UTC
        )
    elif invalidate_price:
        obj.last_price, obj.price_as_of = None, None
    session.add(obj)
    session.flush()
    if mapping is None:
        mapping = LocalPosition(
            position_id=body.position_id, holding_id=obj.id, version=version(obj)
        )
        session.add(mapping)
    mapping.quote_mode, mapping.version = body.quote_mode, version(obj)
    value_history_manager.record(
        session,
        "holdings",
        obj,
        before,
        "update" if before else "create",
        trade_date=body.trade_date,
    )
    if body.quote_mode == "manual":
        from app.modules.portfolio.market_data_manager import _observation

        _observation(
            session,
            obj.symbol,
            obj.currency,
            "manual",
            {
                "price": str(body.manual_price),
                "trade_time": obj.price_as_of.isoformat(),
                "source": body.price_source or "user-entered",
                "holding_id": obj.id,
            },
        )
    session.add(
        AuditLog(
            actor="user",
            action="local_holding_upsert",
            target=f"holdings:{obj.id}",
            detail={"request_id": body.request_id, "input": data},
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RuntimeError(
            "Concurrent holding save; reload or retry the same request"
        ) from None
    return dict(
        listing(session),
        saved=True,
        position_id=body.position_id,
        quote_status="ready" if obj.last_price is not None else "pending",
    )


def initialize(session, client=None):
    return listing(session)


def refresh(session, client=None):
    from app.modules.portfolio.market_data_manager import refresh as refresh_market

    result = refresh_market(session, client)
    return dict(
        listing(session),
        warning=result.get("warning"),
        refresh_after_seconds=result.get("refresh_after_seconds", 300),
    )
