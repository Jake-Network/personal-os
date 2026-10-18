"""FinancialCalculator: deterministic Decimal arithmetic for advisor scenarios (PRD §5.1).

The LLM never does this math. Every function returns explicit `unavailable` reasons
instead of guessing when an input is missing.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.modules.finance.liquidity_policy import BUCKETS, POLICY_SUMMARY
from app.modules.finance.types import ZERO, ExcludedPosition, FxTable, NetWorth, Position, q2


def _month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


class FinancialCalculator:
    def net_worth(self, fx: FxTable, assets: list[Position], liabilities: list[Position]) -> NetWorth:
        total_a = total_l = spendable = ZERO
        by_bucket = {b: ZERO for b in BUCKETS}
        excluded: list[ExcludedPosition] = []
        for pos, is_liability in [(p, False) for p in assets] + [(p, True) for p in liabilities]:
            reason = None
            converted = None
            if pos.value is None:
                reason = pos.unavailable_reason or "no_value"
            else:
                converted = fx.to_base(pos.value, pos.currency)
                if converted is None:
                    reason = f"missing_fx_{pos.currency}_{fx.base}"
            if converted is None:
                excluded.append({"ref": pos.ref, "label": pos.label, "reason": reason,
                                 **({"spendable": True} if pos.spendable else {})})
                continue
            if is_liability:
                total_l += converted
            else:
                total_a += converted
                by_bucket[pos.bucket if pos.bucket in by_bucket else "other"] += converted
                if pos.spendable:
                    spendable += converted
        return NetWorth(fx.base, total_a, total_l, by_bucket, spendable, excluded)

    @staticmethod
    def monthly_average(entries: list[tuple[date, Decimal]], today: date, months: int = 3) -> dict:
        """Average per full calendar month over the last `months` months before `today`'s month.

        A month with no entries is *unrecorded*, not a zero-spend month: averaging it in would turn
        one recorded month into an artificially low average. So the average is only `available`
        when every month in the window has entries. With partial coverage the result is
        unavailable and carries an explicitly labelled estimate (recorded months only) that
        callers must present as an assumption and that the runway never uses.
        """
        empty = {"available": False, "months_considered": months, "months_with_data": 0}
        if not entries:
            return {**empty, "reason": "no_entries"}
        start_index = today.year * 12 + (today.month - 1) - months  # today's month is excluded
        buckets = {start_index + i: ZERO for i in range(months)}
        recorded: set[int] = set()
        for day, amount in entries:
            idx = day.year * 12 + (day.month - 1)
            if idx in buckets:
                buckets[idx] += amount
                recorded.add(idx)
        if not recorded:
            return {**empty, "reason": f"no_entries_in_last_{months}_full_months"}
        coverage = {
            "months_considered": months,
            "months_with_data": len(recorded),
            "recorded_months": [_month_label(i) for i in sorted(recorded)],
            "missing_months": [_month_label(i) for i in sorted(buckets) if i not in recorded],
        }
        if len(recorded) < months:
            observed = sum((buckets[i] for i in recorded), ZERO) / len(recorded)
            return {
                "available": False,
                "reason": "insufficient_coverage",
                **coverage,
                "estimate": {
                    "monthly_average": str(q2(observed)),
                    "basis": "recorded_months_only",
                    "assumption": "unrecorded months are assumed to resemble recorded months; "
                                  "label as an assumption, never as an observed average",
                },
            }
        return {"available": True, "monthly_average": str(q2(sum(buckets.values(), ZERO) / months)), **coverage}

    @staticmethod
    def runway(
        spendable_cash: Decimal,
        monthly_expense: Decimal,
        monthly_income: Decimal = ZERO,
        one_off_outflows: Decimal = ZERO,
        one_off_inflows: Decimal = ZERO,
        emergency_reserve: Decimal = ZERO,
    ) -> dict:
        """Months until spendable cash (minus a reserve) is exhausted at a constant burn."""
        usable = spendable_cash + one_off_inflows - one_off_outflows - emergency_reserve
        burn = monthly_expense - monthly_income
        result = {
            "usable_cash": str(q2(usable)),
            "monthly_net_burn": str(q2(burn)),
            "assumptions": {
                "monthly_expense": str(q2(monthly_expense)),
                "monthly_income": str(q2(monthly_income)),
                "one_off_outflows": str(q2(one_off_outflows)),
                "one_off_inflows": str(q2(one_off_inflows)),
                "emergency_reserve": str(q2(emergency_reserve)),
                "constant_burn": True,
            },
        }
        if usable <= ZERO:
            result["months"] = "0"
        elif burn <= ZERO:
            result["months"] = None
            result["note"] = "non_positive_burn_cash_does_not_deplete"
        else:
            result["months"] = str((usable / burn).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        return result

    def cash_runway(self, worth: dict | None, expense: dict | None) -> dict:
        """Runway from spendable liquidity only, at the observed monthly expense, assuming no income.

        `worth` is NetWorth.as_dict(); `expense` is monthly_average(). Unavailable (with a reason)
        rather than guessed when either input is missing or the expense history is incomplete.
        """
        base = {"policy": POLICY_SUMMARY, "income_assumed": "none"}
        if not worth or worth.get("spendable_liquidity") is None:
            return {"available": False, "months": None, "reason": "spendable_liquidity_unknown", **base}
        if not expense or not expense.get("available"):
            reason = (expense or {}).get("reason") or "unavailable"
            return {"available": False, "months": None, "reason": f"monthly_expense_{reason}", **base}
        result = self.runway(Decimal(worth["spendable_liquidity"]), Decimal(expense["monthly_average"]))
        return {
            "available": True, **result, **base,
            "spendable_liquidity": worth["spendable_liquidity"],
            # Missing FX on a cash account leaves it out, so the runway is understated, never overstated.
            "understated": not worth.get("spendable_liquidity_complete", True),
        }

    @staticmethod
    def months_to_target(
        current: Decimal, target: Decimal, monthly_saving: Decimal, annual_return: Decimal = ZERO, max_months: int = 600
    ) -> dict:
        if current >= target:
            return {"months": 0, "reached": True}
        r = annual_return / Decimal(12)
        value = current
        for month in range(1, max_months + 1):
            value = value * (1 + r) + monthly_saving
            if value >= target:
                return {"months": month, "reached": True, "final_value": str(q2(value))}
        return {"months": None, "reached": False, "reason": f"not_reached_within_{max_months}_months"}

    def stress_test(self, worth: NetWorth, risky_value_base: Decimal, shocks: list[Decimal]) -> list[dict]:
        """Net worth after an instantaneous drop in risky-asset value (e.g. -0.2 = -20%)."""
        out = []
        for shock in shocks:
            loss = risky_value_base * -shock
            out.append({
                "shock": str(shock),
                "loss": str(q2(loss)),
                "net_worth_after": str(q2(worth.net_worth - loss)),
            })
        return out


financial_calculator = FinancialCalculator()
