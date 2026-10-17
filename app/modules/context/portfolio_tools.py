"""Read-only Sheets context adapters. Credentials and spreadsheet IDs never enter context."""
from datetime import datetime
from decimal import Decimal

from app.enums.context_category import Category
from app.schema.context_schema import ToolContext, ToolResult


def sheets_enabled(ctx: ToolContext) -> bool:
    from app.modules.portfolio.portfolio_manager import settings_dict
    return bool(settings_dict(ctx.session)["spreadsheet_id"])


def _portfolio(ctx: ToolContext) -> dict:
    from app.modules.portfolio.portfolio_manager import portfolio
    return portfolio(ctx.session)


def _result(ctx: ToolContext, data: dict, lines: list[dict], category: Category, issues: list) -> ToolResult:
    timestamp = data.get("synced_at")
    flags = [{"code": "sheets_data_quality", "category": category.value, "detail": str(i)} for i in issues]
    if data.get("stale"):
        flags.append({"code": "stale_price", "category": category.value, "detail": "Google Sheets sync or valuation is stale"})
    return ToolResult(
        data=data,
        refs=[{"table": "portfolio_imports", "id": data.get("import_id"),
               "position_id": f"{line['kind']}:{line['id']}", "updated_at": timestamp} for line in lines],
        source_updated_at=datetime.fromisoformat(timestamp) if timestamp else None,
        flags=flags,
    )


def sheets_accounts(ctx: ToolContext) -> ToolResult:
    p = _portfolio(ctx)
    include_investment = Category.INVESTMENT in ctx.allowed
    lines = [r for r in p["lines"] if include_investment or r["kind"] != "holding"]
    issues = list(p["issues"])
    # Aggregates inherently reveal investment data, so withhold them when that
    # category is excluded rather than sending a misleading partial net worth.
    if not include_investment:
        issues = ["investment_excluded_from_net_worth"]

    def rows(kind):
        return [{"ref": f"sheets:{r['kind']}:{r['id']}", "name": r["label"], "kind": kind,
                 "currency": r["currency"], "balance": r.get("balance"), "value": r.get("balance"),
                 "as_of": r.get("as_of"), "value_krw": r.get("value_krw")} for r in lines if r["kind"] == kind]

    worth = {"base_currency": "KRW", "total_assets": p["total_assets"] if include_investment else None,
             "total_liabilities": p["total_liabilities"], "net_worth": p["net_worth"] if include_investment else None,
             # Sheets rows carry no account kind, so the eligible-cash policy cannot be applied.
             "cash_and_equivalents": None, "spendable_liquidity": None, "spendable_liquidity_complete": False,
             "investable_assets": None, "restricted_retirement_assets": None,
             "complete": p["complete"] and include_investment,
             "excluded_positions": issues}
    data = {"source": "google_sheets", "accounts": rows("cash"), "other_assets": rows("other"),
            "liabilities": rows("liability"), "computed": {"net_worth": worth, "computed_by": "backend"},
            "synced_at": p.get("synced_at"), "import_id": p.get("import_id"), "stale": p.get("stale")}
    result = _result(ctx, data, lines, Category.FINANCIAL, issues)
    if not worth["complete"]:
        result.flags.append({"code": "net_worth_incomplete", "category": Category.FINANCIAL.value})
    return result


def sheets_portfolio(ctx: ToolContext) -> ToolResult:
    p = _portfolio(ctx)
    lines = [r for r in p["lines"] if r["kind"] == "holding"]
    total = p["investments"]
    holdings = [{**r, "ref": f"sheets:holding:{r['id']}", "symbol": r.get("ticker"),
                 "name": r["label"], "last_price": r.get("price"), "value_base": r.get("value_krw")} for r in lines]
    weights = sorted((Decimal(r["value_krw"]) / Decimal(total) * 100 for r in lines
                      if total is not None and Decimal(total) > 0 and r["value_krw"] is not None), reverse=True)
    data = {"source": "google_sheets", "base_currency": "KRW", "holdings": holdings,
            "computed": {"total_value_base": total, "top3_concentration_pct": str(sum(weights[:3], Decimal(0))) if weights else None,
                         "by_asset_class": p.get("by_asset_class", {}),
                         "stock_value": p.get("stock_value"),
                         "stock_share_of_assets_pct": _stock_share(p) if Category.FINANCIAL in ctx.allowed else None,
                         "computed_by": "backend"}, "synced_at": p.get("synced_at"),
            "import_id": p.get("import_id"), "stale": p.get("stale")}
    return _result(ctx, data, lines, Category.INVESTMENT, [i for r in lines for i in r.get("issues", [])])


def _stock_share(valuation: dict) -> str | None:
    assets, stocks = valuation.get("total_assets"), valuation.get("stock_value")
    if assets is None or stocks is None or Decimal(assets) <= 0:
        return None
    return str((Decimal(stocks) / Decimal(assets) * 100).quantize(Decimal("0.01")))


def sheets_market(ctx: ToolContext) -> ToolResult:
    p = _portfolio(ctx)
    lines = [r for r in p["lines"] if r["kind"] == "holding"]
    data = {"source": "google_sheets", "note": "Last synchronized values; prices may be delayed. FX recorded per valuation.",
            "prices": [{"symbol": r.get("ticker"), "price": r.get("price"), "currency": r["currency"],
                        "as_of": r.get("price_as_of"), "fx_rate": r.get("fx_rate"), "fx_as_of": r.get("fx_as_of")} for r in lines],
            "synced_at": p.get("synced_at"), "import_id": p.get("import_id"), "stale": p.get("stale")}
    return _result(ctx, data, lines, Category.INVESTMENT, [i for r in lines for i in r.get("issues", [])])


def get_monthly_asset_history(ctx: ToolContext) -> ToolResult:
    # A total is sensitive to both categories even though served as a Financial tool.
    if not {Category.FINANCIAL, Category.INVESTMENT} <= ctx.allowed:
        return ToolResult(data={"snapshots": [], "withheld": True}, flags=[
            {"code": "monthly_history_withheld", "category": Category.FINANCIAL.value,
             "detail": "Both financial and investment sharing are required for aggregate history"}])
    from app.modules.portfolio.portfolio_manager import history
    result = history(ctx.session, period="all")
    snapshots = result["snapshots"][-13:]
    # A bounded recent history supports six/twelve month comparisons; never expose
    # current account identifiers or the configuration/credentials via this tool.
    safe = [{k: r.get(k) for k in ("id", "month", "revision", "created_at", "total_assets", "total_liabilities",
                                 "net_worth", "cash", "investments", "allocation", "complete", "issues",
                                 "by_asset_class", "stock_value", "change_krw", "change_pct")} for r in snapshots]
    for row in safe:
        row["stock_share_of_assets_pct"] = _stock_share(row)
    flags = [{"code": "monthly_history_incomplete", "category": Category.FINANCIAL.value}]
    if safe and all(r["complete"] for r in safe) and not result["missing_months"]:
        flags = []
    return ToolResult(data={"snapshots": safe, "missing_months": result["missing_months"],
                            "computed_by": "backend", "policy": "Observed changes only; causes require independent evidence."},
                      refs=[{"table": "monthly_snapshots", "id": r["id"]} for r in safe],
                      source_updated_at=max((datetime.fromisoformat(r["created_at"]) for r in safe), default=None), flags=flags)
