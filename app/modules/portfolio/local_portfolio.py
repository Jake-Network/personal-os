"""Assemble local current-state valuation without any Google dependency."""

from sqlalchemy import select

from app.modules.database.model import (
    Account,
    FxRate,
    Holding,
    Liability,
    LocalFinanceCoverage,
    LocalPosition,
    OtherAsset,
)
from app.modules.database.model.base import utcnow
from app.modules.finance.clock import local_today
from app.modules.finance.formatting import quantity_text
from app.modules.finance.liquidity_policy import account_spendable
from app.modules.portfolio.valuation import enrich_rows, parse_decimal, value_positions


def confirm_coverage(session, kinds):
    from app.modules.database.model.base import utcnow
    obj = session.get(LocalFinanceCoverage, 1)
    if obj is None:
        obj = LocalFinanceCoverage(id=1, kinds=[])
        session.add(obj)
    obj.kinds, obj.confirmed_at = sorted(set(kinds)), utcnow()
    session.commit()
    return {"kinds": obj.kinds, "confirmed_at": obj.confirmed_at.isoformat()}


def rows(session, kinds=None):
    kinds = set(kinds or ("holding", "cash", "liability", "other"))
    result = []
    positions = {p.holding_id: p for p in session.scalars(select(LocalPosition))}
    for obj in session.scalars(select(Holding)) if "holding" in kinds else []:
        p = positions.get(obj.id)
        result.append(
            dict(
                kind="holding",
                id=p.position_id if p else str(obj.id),
                label=obj.name or obj.symbol,
                ticker=obj.symbol,
                currency=obj.currency,
                quantity=quantity_text(obj.quantity),
                avg_cost=str(obj.avg_cost) if obj.avg_cost is not None else None,
                price=str(obj.last_price) if obj.last_price is not None else None,
                price_as_of=obj.price_as_of.date().isoformat()
                if obj.price_as_of
                else None,
                as_of=obj.updated_at.date().isoformat(),
                asset_class=obj.asset_class,
                source="local_observation",
            )
        )
    for model, kind, amount, when in (
        (Account, "cash", "balance", "balance_as_of"),
        (Liability, "liability", "balance", "balance_as_of"),
        (OtherAsset, "other", "value", "value_as_of"),
    ):
        if kind not in kinds:
            continue
        for obj in session.scalars(select(model)):
            result.append(
                dict(
                    kind=kind,
                    id=str(obj.id),
                    label=obj.name,
                    currency=obj.currency,
                    balance=str(getattr(obj, amount)),
                    as_of=getattr(obj, when).isoformat(),
                    **(
                        {"spendable": account_spendable(obj.kind, obj.is_liquid)}
                        if kind == "cash" else {}
                    ),
                )
            )
    # Select by timestamp before reducing to dates: intraday updates are not conflicts.
    latest_rates = {}
    for rate in session.scalars(
        select(FxRate)
        .where(FxRate.quote == "KRW", FxRate.as_of <= utcnow())
        .order_by(FxRate.as_of.desc(), FxRate.id.desc())
    ):
        amount = parse_decimal(rate.rate)
        if amount is not None and amount > 0:
            latest_rates.setdefault(rate.base, rate)
    rates = [
        dict(
            currency=r.base,
            rate=str(r.rate),
            as_of=r.as_of.date().isoformat(),
            source="local",
        )
        for r in latest_rates.values()
    ]
    return enrich_rows(result, {"FX": rates}, local_today(), False)


def portfolio(session, kinds=None):
    positions = rows(session, kinds=kinds)
    coverage = session.get(LocalFinanceCoverage, 1)
    confirmed = coverage.kinds if coverage else []
    result = value_positions(
        positions,
        sorted(set(confirmed) | {row["kind"] for row in positions}),
        local_today(),
        True,
    )
    return dict(
        result,
        synced_at=None,
        stale=bool(result["issues"]),
        import_id=None,
        source="local",
        coverage=confirmed,
    )
