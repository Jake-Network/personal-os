from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import FxRate
from app.modules.database.model.base import utcnow

# Tolerate small clock skew between the browser and the server, but never store a rate valuation cannot use yet.
_FUTURE_SKEW = timedelta(minutes=5)


def _entered_as_of(value: datetime) -> datetime:
    now = utcnow()
    if value.tzinfo is None:  # Same rule as UTCDateTime: naive input is UTC.
        value = value.replace(tzinfo=now.tzinfo)
    if value > now + _FUTURE_SKEW:
        raise ValueError("환율 기준 시각은 현재보다 미래일 수 없습니다")
    return min(value, now)


class FxRateHandler(BaseCRUDHandler[FxRate]):
    def __init__(self):
        super().__init__(FxRate)

    def get_latest_first(self, session: Session) -> list[FxRate]:
        return self.get_multiple_with_filters(session, order_by=[FxRate.as_of.desc()])

    def set_rate(self, session: Session, base: str, quote: str, rate: Decimal, as_of: datetime,
                 only_if_newer: bool = False) -> FxRate | None:
        """Keep one row per pair. `only_if_newer` lets automatic refreshes yield to a later manual value.

        A stored rate dated in the future is invisible to valuation, so a refresh replaces it instead of yielding.
        """
        stmt = insert(FxRate).values(base=base, quote=quote, rate=rate, as_of=as_of)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_fx_rates_pair",
            set_={"rate": stmt.excluded.rate, "as_of": stmt.excluded.as_of},
            where=or_(FxRate.as_of <= stmt.excluded.as_of, FxRate.as_of > utcnow()) if only_if_newer else None,
        ).returning(FxRate.id)
        row_id = session.execute(stmt).scalar_one_or_none()
        return None if row_id is None else session.get(FxRate, row_id, populate_existing=True)

    def create(self, session: Session, obj_in: BaseModel | dict[str, Any]) -> FxRate:
        # Entering a pair that already exists replaces its current rate instead of adding history,
        # but never with an older observation. `replaced_existing` lets the caller audit it as an update.
        data = obj_in.model_dump() if isinstance(obj_in, BaseModel) else dict(obj_in)
        as_of = _entered_as_of(data["as_of"])
        current = self.get_first_with_filters(session, [FxRate.base == data["base"], FxRate.quote == data["quote"]])
        if current is not None and current.as_of > as_of:
            raise ValueError(
                f"{data['base']}/{data['quote']}의 더 최근 환율({current.as_of.date().isoformat()} 기준)이 이미 있습니다")
        obj = self.set_rate(session, data["base"], data["quote"], data["rate"], as_of)
        obj.replaced_existing = current is not None
        return obj

    def update(self, session: Session, obj: FxRate, obj_in: BaseModel | dict[str, Any]) -> FxRate:
        data = obj_in.model_dump(exclude_unset=True) if isinstance(obj_in, BaseModel) else dict(obj_in)
        if "as_of" in data:
            data["as_of"] = _entered_as_of(data["as_of"])
        pair = (data.get("base", obj.base), data.get("quote", obj.quote))
        if self.get_first_with_filters(session, [FxRate.base == pair[0], FxRate.quote == pair[1], FxRate.id != obj.id]):
            raise ValueError(f"{pair[0]}/{pair[1]} 환율이 이미 있습니다. 해당 항목의 값을 수정하세요")
        return super().update(session, obj, data)


fx_rate_handler = FxRateHandler()
