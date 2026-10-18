"""Pure ledger aggregation: internal moves and trades do not become income."""

from decimal import Decimal

INCOME = {"income", "dividend", "interest"}
OUTFLOW = {"expense", "fee", "tax"}


def aggregate(records):
    reversed_ids = {r["reverses_id"] for r in records if r["kind"] == "reversal"}
    buckets = {}
    for row in records:
        if row["id"] in reversed_ids or row["kind"] == "reversal":
            continue
        key = row["currency"]
        entry = buckets.setdefault(
            key,
            {
                "income": Decimal(0),
                "expense": Decimal(0),
                "transfer": Decimal(0),
                "buy": Decimal(0),
                "sell": Decimal(0),
                "repayment": Decimal(0),
            },
        )
        amount = Decimal(row["amount"]) if row.get("amount") is not None else Decimal(0)
        kind = row["kind"]
        if kind in INCOME:
            entry["income"] += amount
        elif kind in OUTFLOW:
            entry["expense"] += amount
        elif kind in entry:
            entry[kind] += amount
    return {
        currency: {
            **{k: str(v) for k, v in values.items()},
            "net_cashflow": str(values["income"] - values["expense"]),
        }
        for currency, values in buckets.items()
    }
