"""FinancialCalculator: deterministic Decimal arithmetic for advisor scenarios (PRD §5.1).

The LLM never does this math. Every function returns explicit `unavailable` reasons
instead of guessing when an input is missing.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.schema.finance_schema import ZERO, FxTable, NetWorth, Position, q2


class FinancialCalculator:
    def net_worth(self, fx: FxTable, assets: list[Position], liabilities: list[Position]) -> NetWorth:
        total_a = total_l = liquid = ZERO
        excluded: list[dict] = []
        for pos, is_liability in [(p, False) for p in assets] + [(p, True) for p in liabilities]:
            if pos.value is None:
                excluded.append({"ref": pos.ref, "label": pos.label, "reason": pos.unavailable_reason or "no_value"})
                continue
            converted = fx.to_base(pos.value, pos.currency)
            if converted is None:
                excluded.append({"ref": pos.ref, "label": pos.label, "reason": f"missing_fx_{pos.currency}_{fx.base}"})
                continue
            if is_liability:
                total_l += converted
            else:
                total_a += converted
                if pos.liquid:
                    liquid += converted
        return NetWorth(fx.base, total_a, total_l, liquid, excluded)

    @staticmethod
    def monthly_average(entries: list[tuple[date, Decimal]], today: date, months: int = 3) -> dict:
        """Average per full calendar month over the last `months` months before `today`'s month."""
        if not entries:
            return {"available": False, "reason": "no_entries"}
        end_year, end_month = today.year, today.month  # exclusive
        start_index = end_year * 12 + (end_month - 1) - months
        buckets = {start_index + i: ZERO for i in range(months)}
        for day, amount in entries:
            idx = day.year * 12 + (day.month - 1)
            if idx in buckets:
                buckets[idx] += amount
        months_with_data = sum(1 for v in buckets.values() if v != ZERO)
        if months_with_data == 0:
            return {"available": False, "reason": f"no_entries_in_last_{months}_full_months"}
        total = sum(buckets.values(), ZERO)
        return {
            "available": True,
            "monthly_average": str(q2(total / months)),
            "months_considered": months,
            "months_with_data": months_with_data,
            "partial": months_with_data < months,
        }

    @staticmethod
    def runway(
        liquid_cash: Decimal,
        monthly_expense: Decimal,
        monthly_income: Decimal = ZERO,
        one_off_outflows: Decimal = ZERO,
        one_off_inflows: Decimal = ZERO,
        emergency_reserve: Decimal = ZERO,
    ) -> dict:
        """Months until liquid cash (minus a reserve) is exhausted at a constant burn."""
        usable = liquid_cash + one_off_inflows - one_off_outflows - emergency_reserve
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
