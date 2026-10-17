"""Value objects for the deterministic financial calculator."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Position:
    """A valued line item (account, asset, holding, liability) in its native currency."""

    ref: str
    label: str
    value: Decimal | None  # None = cannot be valued (e.g. no price)
    currency: str
    liquid: bool = False
    unavailable_reason: str | None = None


@dataclass
class FxTable:
    base: str
    rates: dict[str, Decimal] = field(default_factory=dict)  # currency -> base per 1 unit

    def to_base(self, value: Decimal, currency: str) -> Decimal | None:
        if currency == self.base:
            return value
        rate = self.rates.get(currency)
        return None if rate is None else value * rate


@dataclass
class NetWorth:
    base_currency: str
    assets: Decimal
    liabilities: Decimal
    liquid_assets: Decimal
    excluded: list[dict]  # positions left out, with reason

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities

    @property
    def complete(self) -> bool:
        return not self.excluded

    def as_dict(self) -> dict:
        return {
            "base_currency": self.base_currency,
            "total_assets": str(q2(self.assets)),
            "total_liabilities": str(q2(self.liabilities)),
            "net_worth": str(q2(self.net_worth)),
            "liquid_assets": str(q2(self.liquid_assets)),
            "complete": self.complete,
            "excluded_positions": self.excluded,
        }
