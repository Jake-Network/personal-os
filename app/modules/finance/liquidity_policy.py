"""Which balances can fund living expenses: an explicit policy, not the generic `is_liquid` flag.

Every asset falls into exactly one bucket:

  cash        checking / savings / deposit / cash / brokerage_cash accounts (cash and cash equivalents)
  investment  securities at market value (holdings outside retirement accounts)
  retirement  pension accounts and the holdings inside them, locked until retirement age
  other       other accounts and other assets (real estate, vehicles, severance estimates ...)

Spendable liquidity is the cash bucket restricted to accounts the user also marked liquid.
`is_liquid` can only *narrow* eligibility (e.g. a term deposit with a break penalty); it never
turns equities, pension money or property into spendable cash. Selling securities to cover
expenses is a decision for the user, not an assumption the runway makes on their behalf.
"""

CASH_ACCOUNT_KINDS = frozenset({"checking", "savings", "deposit", "cash", "brokerage_cash"})
RETIREMENT_ACCOUNT_KINDS = frozenset({"pension"})

BUCKETS = ("cash", "investment", "retirement", "other")
POLICY_ID = "eligible_cash_v1"
POLICY_SUMMARY = (
    "spendable_liquidity = cash-kind accounts (checking, savings, deposit, cash, brokerage_cash) marked liquid; "
    "securities, pension and other assets are never counted as spendable"
)


def account_bucket(kind: str) -> str:
    if kind in CASH_ACCOUNT_KINDS:
        return "cash"
    if kind in RETIREMENT_ACCOUNT_KINDS:
        return "retirement"
    return "other"


def account_spendable(kind: str, is_liquid: bool) -> bool:
    return kind in CASH_ACCOUNT_KINDS and bool(is_liquid)


def holding_bucket(account_kind: str | None) -> str:
    """Holdings in a pension account are retirement assets; all others are investments."""
    return "retirement" if account_kind in RETIREMENT_ACCOUNT_KINDS else "investment"
