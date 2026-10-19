"""Append-only local ledger; it records facts without guessing account balances."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.modules.database.model import (
    Account,
    FinancialTransaction,
    Holding,
    MonthlySnapshot,
)
from app.modules.finance.clock import local_today
from app.modules.finance.ledger import aggregate
from app.modules.portfolio.snapshots import month_end, snapshot_dict
from app.modules.portfolio.valuation import value_positions


def transaction_dict(obj):
    return {
        "id": obj.id,
        "kind": obj.kind,
        "occurred_at": obj.occurred_at.isoformat(),
        "recorded_at": obj.recorded_at.isoformat(),
        **obj.payload,
    }


def record(session, body):
    payload = body.model_dump(mode="json")
    existing = session.scalar(
        select(FinancialTransaction).where(
            FinancialTransaction.request_id == body.request_id
        )
    )
    if existing:
        if existing.payload != payload:
            raise RuntimeError("Request ID already used for a different transaction")
        return transaction_dict(existing)
    for account in (body.account_id, body.counterparty_account_id):
        if account is not None and session.get(Account, account) is None:
            raise ValueError("Account not found")
    if body.holding_id is not None and session.get(Holding, body.holding_id) is None:
        raise ValueError("Holding not found")
    if body.reverses_id:
        original = session.get(FinancialTransaction, body.reverses_id)
        if original is None or original.kind == "reversal":
            raise ValueError("Invalid reversal target")
        if session.scalar(
            select(FinancialTransaction.id).where(
                FinancialTransaction.reverses_id == body.reverses_id
            )
        ):
            raise RuntimeError("Transaction already reversed")
    obj = FinancialTransaction(
        request_id=body.request_id,
        kind=body.kind,
        occurred_at=body.occurred_at,
        payload=payload,
        reverses_id=body.reverses_id,
    )
    session.add(obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RuntimeError(
            "Concurrent transaction or reversal; reload and retry the same request"
        ) from None
    return transaction_dict(obj)


def listing(session, year=None):
    # Status must include reversals outside the filtered year and the listing limit.
    reversed_ids = set(
        session.scalars(
            select(FinancialTransaction.reverses_id).where(
                FinancialTransaction.kind == "reversal",
                FinancialTransaction.reverses_id.is_not(None),
            )
        )
    )
    query = select(FinancialTransaction).order_by(
        FinancialTransaction.occurred_at.desc(), FinancialTransaction.id.desc()
    )
    if year is not None:
        query = query.where(
            FinancialTransaction.occurred_at
            >= datetime(year, 1, 1, tzinfo=ZoneInfo(settings.timezone)),
            FinancialTransaction.occurred_at
            < datetime(year + 1, 1, 1, tzinfo=ZoneInfo(settings.timezone)),
        )
    return [
        dict(transaction_dict(r), is_reversed=r.id in reversed_ids)
        for r in session.scalars(query.limit(1000))
    ]


def trend(session, year):
    # Reversals outside the requested year still invalidate original entries.
    records = [
        transaction_dict(r) for r in session.scalars(select(FinancialTransaction))
    ]
    reversed_ids = {r["reverses_id"] for r in records if r["kind"] == "reversal"}
    selected = [
        r
        for r in records
        if r["id"] not in reversed_ids
        and r["kind"] != "reversal"
        and datetime.fromisoformat(r["occurred_at"])
        .astimezone(ZoneInfo(settings.timezone))
        .year
        == year
    ]
    snapshots = session.scalars(
        select(MonthlySnapshot)
        .where(
            MonthlySnapshot.month >= date(year, 1, 1),
            MonthlySnapshot.month < date(year + 1, 1, 1),
        )
        .order_by(MonthlySnapshot.month, MonthlySnapshot.revision)
    ).all()
    latest = {s.month: s for s in snapshots}
    return {
        "year": year,
        "cashflow_by_currency": aggregate(selected),
        "snapshots": [snapshot_dict(s) for s in latest.values()],
        "complete": False,
        "data_quality_flags": [
            "Ledger coverage is not declared complete; recorded flows only",
            "Asset changes include unexplained differences; ledger entries alone do not establish investment returns",
        ],
        "balance_policy": "Ledger records do not automatically overwrite balances or quantities; confirm updated observations separately.",
    }


def close_month(session, body):
    end = month_end(body.month, local_today())
    if session.scalar(
        select(MonthlySnapshot.id).where(MonthlySnapshot.month == body.month)
    ):
        raise RuntimeError("Month already closed; append a correction revision")
    payload = value_positions(
        [r.model_dump(mode="json") for r in body.rows], body.coverage, end, True, True
    )
    if not payload["complete"]:
        raise ValueError(
            "Month-end evidence incomplete: " + "; ".join(payload["issues"])
        )
    payload["source_kind"] = "local_explicit_evidence"
    obj = MonthlySnapshot(
        month=body.month, revision=1, reason=body.reason, payload=payload
    )
    session.add(obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RuntimeError("Concurrent month close; reload") from None
    return snapshot_dict(obj)


def observe_today(session):
    from app.modules.portfolio.local_portfolio import portfolio
    from app.modules.portfolio.market_data_manager import _observation

    result = portfolio(session)
    payload = {
        "date": local_today().isoformat(),
        "valuation": result,
        "kind": "observed_valuation",
        "month_end_confirmed": False,
    }
    _observation(session, "LOCAL:PORTFOLIO", "KRW", "local_valuation", payload)
    session.commit()
    return payload
