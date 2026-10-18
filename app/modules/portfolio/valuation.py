"""Deterministic Decimal valuation of imported sheet rows: parsing, FX/close evidence and totals."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

KINDS = ("cash", "holding", "liability", "other")
TABS = {"Cash": "cash", "Holdings": "holding", "Liabilities": "liability", "OtherAssets": "other"}


def parse_decimal(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 <= result < Decimal(
            "1e20") and result.as_tuple().exponent >= -12 else None
    except InvalidOperation:
        return None


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def coverage_kinds(tables, month):
    rows = [r for r in tables.get("Coverage", []) if r.get("month") == month]
    if len(rows) != 1:
        return []
    return [k for k in KINDS if str(rows[0].get(k, "")).lower() == "true"]


def money_string(value):
    with localcontext() as context:
        context.prec = 100
        return str(value.quantize(Decimal("0.01"))) if value is not None else None


def value_positions(rows, coverage, end, verified, historical=False):
    with localcontext() as context:
        context.prec = 100  # capped operands (<1e20), products and up to 10k rows
        return _calculate(rows, coverage, end, verified, historical)


def _calculate(rows, coverage, end, verified, historical=False):
    sums = {kind: Decimal(0) for kind in KINDS}
    complete = {kind: kind in coverage for kind in KINDS}
    issues = [f"Missing explicit {kind} coverage" for kind in KINDS if kind not in coverage]
    lines = []
    classes = {}
    seen = set()
    for row in rows:
        line = dict(row)
        line.setdefault("id", "")
        line.setdefault("label", row.get("id", "Unnamed position"))
        line.setdefault("currency", "")
        for field in ("balance", "quantity", "avg_cost", "price"):
            parsed = parse_decimal(row.get(field))
            line[field] = format(parsed, "f") if parsed is not None else None
        kind = row.get("kind")
        problems = []
        if kind not in KINDS:
            issues.append("Unknown position kind")
            complete = {k: False for k in KINDS}
            continue
        key = (kind, row.get("id"))
        if not row.get("id") or key in seen:
            problems.append("Missing or duplicate position ID")
        seen.add(key)
        currency = row.get("currency", "")
        if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
            problems.append("Invalid currency")
        as_of = parse_date(row.get("as_of"))
        if as_of is None or as_of > end or (historical and as_of != end):
            problems.append(
                "Missing month-end balance/quantity evidence" if historical else "Missing or future balance date")
        elif not historical and (end - as_of).days > 3:
            problems.append("Stale balance/quantity")
        fx = Decimal(1) if currency == "KRW" else parse_decimal(row.get("fx_rate"))
        fx_date = end if currency == "KRW" else parse_date(row.get("fx_as_of"))
        if fx is None or fx <= 0 or fx_date is None or fx_date > end:
            problems.append("Missing or invalid FX evidence")
            fx = None
        elif (end - fx_date).days > 7:
            problems.append("Stale FX rate")
        native = parse_decimal(row.get("balance"))
        gain = None
        if kind == "holding":
            quantity = parse_decimal(row.get("quantity"))
            price = parse_decimal(row.get("price"))
            price_date = parse_date(row.get("price_as_of"))
            if quantity is None:
                problems.append("Missing quantity")
            if price is None or price_date is None or price_date > end:
                problems.append("Missing applicable close/price")
                price = None
            elif not historical and (end - price_date).days > 7:
                problems.append("Stale price; latest valid market close unconfirmed")
            if historical and (parse_date(row.get("close_valid_through")) is None
                               or parse_date(row.get("close_valid_through")) < end or not row.get("source")):
                problems.append("Last valid month-end market close unconfirmed")
            if row.get("source") == "googlefinance" and (historical or not verified):
                problems.append("GOOGLEFINANCE API values have not been verified")
                price = None
            native = quantity * price if quantity is not None and price is not None else None
            cost = parse_decimal(row.get("avg_cost"))
            if native is not None and cost is not None and fx is not None:
                gain = (native - quantity * cost) * fx
        if row.get("fx_source") == "googlefinance" and (historical or not verified):
            problems.append("GOOGLEFINANCE FX values have not been verified")
            fx = None
        value = native * fx if native is not None and fx is not None else None
        if value is None:
            problems.append("Valuation unavailable")
        # Invalid identity/date evidence must never contribute a confirmed total.
        if problems:
            complete[kind] = False
            issues.extend(f"{row.get('label') or row.get('id')}: {problem}" for problem in problems)
        if value is not None:
            sums[kind] += value
            if kind == "holding":
                asset_class = row.get("asset_class") or "unknown"
                if asset_class not in ("equity", "etf", "bond", "crypto", "other"):
                    asset_class = "unknown"
                classes[asset_class] = classes.get(asset_class, Decimal(0)) + value
        line.update(value_krw=money_string(value), unrealized_gain_krw=money_string(gain),
                    fx_rate=format(fx, "f") if fx is not None else None,
                    fx_as_of=fx_date.isoformat() if fx_date else None, issues=problems)
        lines.append(line)
    assets_complete = all(complete[k] for k in ("cash", "holding", "other"))
    assets = sum((sums[k] for k in ("cash", "holding", "other")), Decimal(0)) if assets_complete else None
    liabilities = sums["liability"] if complete["liability"] else None
    return {"lines": lines, "complete": all(complete.values()), "issues": issues,
            "total_assets": money_string(assets), "total_liabilities": money_string(liabilities),
            "net_worth": money_string(assets - liabilities) if assets is not None and liabilities is not None else None,
            "cash": money_string(sums["cash"]) if complete["cash"] else None,
            "investments": money_string(sums["holding"]) if complete["holding"] else None,
            "allocation": {"cash": money_string(sums["cash"]) if complete["cash"] else None,
                           "investments": money_string(sums["holding"]) if complete["holding"] else None,
                           "other": money_string(sums["other"]) if complete["other"] else None},
            "by_asset_class": {k: money_string(v) for k, v in classes.items()} if complete["holding"] else {},
            "stock_value": money_string(classes.get("equity", Decimal(0))) if complete[
                                                                             "holding"] and "unknown" not in classes else None,
            "rows": rows, "coverage": coverage}


def latest_evidence(rows, key, value, end, amount_key="rate"):
    eligible = [r for r in rows if r.get(key) == value and parse_date(r.get("as_of")) is not None
                and parse_date(r.get("as_of")) <= end and parse_decimal(r.get(amount_key)) is not None
                and parse_decimal(r.get(amount_key)) > 0]
    if not eligible:
        return {}
    latest = max(eligible, key=lambda r: parse_date(r["as_of"]))
    same_date = [r for r in eligible if parse_date(r["as_of"]) == parse_date(latest["as_of"])]
    if any(r != latest for r in same_date):
        return {}  # Conflicting records must never silently choose a value.
    return latest


def enrich_rows(rows, tables, end, historical):
    result = []
    for original in rows:
        row = dict(original)
        rates = tables.get("FX", [])
        if historical:
            # Current formula rates are observations, never historical close evidence.
            rates = [rate for rate in rates if rate.get("source") != "googlefinance"]
        fx = latest_evidence(rates, "currency", row.get("currency"), end)
        row.update(fx_rate=fx.get("rate"), fx_as_of=fx.get("as_of"), fx_source=fx.get("source"))
        if historical and row.get("kind") == "holding":
            closes = [c for c in tables.get("Closes", []) if c.get("currency") == row.get("currency")]
            close = latest_evidence(closes, "ticker", row.get("ticker"), end, "price")
            # Historical GOOGLEFINANCE API arrays cannot supply close evidence.
            if close.get("source") == "googlefinance":
                close = {}
            row.update(price=close.get("price"), price_as_of=close.get("as_of"), source=close.get("source"),
                       close_valid_through=close.get("valid_through"))
        result.append(row)
    return result
