"""Value objects for the deterministic financial calculator."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.modules.finance.liquidity_policy import POLICY_ID

ZERO = Decimal("0")


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Position:
    """A valued line item (account, asset, holding, liability) in its native currency.

    `bucket` and `spendable` come from liquidity_policy; liabilities leave them at the defaults.
    """

    ref: str
    label: str
    value: Decimal | None  # None = cannot be valued (e.g. no price)
    currency: str
    bucket: str = "other"  # cash | investment | retirement | other
    spendable: bool = False  # counts toward spendable liquidity (cash runway)
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
    """Net worth plus the liquidity split. Only `spendable_liquidity` may fund living expenses."""

    base_currency: str
    assets: Decimal
    liabilities: Decimal
    by_bucket: dict[str, Decimal]  # cash | investment | retirement | other
    spendable_liquidity: Decimal
    excluded: list[dict]  # positions left out, with reason

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities

    @property
    def complete(self) -> bool:
        return not self.excluded

    @property
    def spendable_complete(self) -> bool:
        """False when a spendable cash position could not be valued, so liquidity is understated."""
        return not any(e.get("spendable") for e in self.excluded)

    def as_dict(self) -> dict:
        bucket = {k: str(q2(v)) for k, v in self.by_bucket.items()}
        return {
            "base_currency": self.base_currency,
            "total_assets": str(q2(self.assets)),
            "total_liabilities": str(q2(self.liabilities)),
            "net_worth": str(q2(self.net_worth)),
            "cash_and_equivalents": bucket["cash"],
            "spendable_liquidity": str(q2(self.spendable_liquidity)),
            "spendable_liquidity_complete": self.spendable_complete,
            "investable_assets": str(q2(self.by_bucket["investment"] + self.by_bucket["retirement"])),
            "restricted_retirement_assets": bucket["retirement"],
            "other_assets": bucket["other"],
            "liquidity_policy": POLICY_ID,
            "complete": self.complete,
            "excluded_positions": self.excluded,
        }
