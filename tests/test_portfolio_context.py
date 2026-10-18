"""The authoritative source switch must preserve category privacy and null values."""
from datetime import UTC, datetime

from app.enums.context_category import Category as C
from app.modules.context import portfolio_tools as tools
from app.modules.context.context_routing_manager import context_routing_manager
from app.schema.context_schema import ToolContext


def sample():
    return {"lines": [
        {"kind": "cash", "id": "cash", "label": "Cash", "currency": "KRW", "balance": "10", "value_krw": "10"},
        {"kind": "holding", "id": "stock", "label": "Private stock", "currency": "USD", "ticker": "SECRET",
         "quantity": "3", "price": None, "fx_rate": "1400", "value_krw": None, "issues": ["missing_price"]},
    ], "total_assets": None, "total_liabilities": "0", "net_worth": None, "cash": "10", "investments": None,
        "complete": False, "issues": ["missing_price SECRET"], "stale": True, "synced_at": "2026-10-01T00:00:00+00:00"}


def test_sheets_accounts_do_not_leak_excluded_investment(session, monkeypatch):
    monkeypatch.setattr(tools, "_portfolio", lambda ctx: sample())
    result = tools.sheets_accounts(ToolContext(session, datetime.now(UTC), frozenset({C.FINANCIAL})))
    assert "SECRET" not in str(result)
    assert "stock" not in str(result)
    assert result.data["computed"]["net_worth"]["net_worth"] is None
    assert result.data["computed"]["net_worth"]["spendable_liquidity"] is None


def test_missing_sheets_price_is_not_a_zero_valuation(session, monkeypatch):
    monkeypatch.setattr(tools, "_portfolio", lambda ctx: sample())
    result = tools.sheets_portfolio(ToolContext(session, datetime.now(UTC), frozenset({C.INVESTMENT})))
    assert result.data["computed"]["total_value_base"] is None
    assert result.data["holdings"][0]["last_price"] is None
    assert result.data["holdings"][0]["value_base"] is None
    assert result.flags


def test_history_is_withheld_before_querying_when_investments_excluded(session):
    result = tools.get_monthly_asset_history(ToolContext(session, datetime.now(UTC), frozenset({C.FINANCIAL})))
    assert result.data == {"snapshots": [], "withheld": True}
    assert result.refs == []


def test_asset_history_questions_select_required_categories():
    for question in ("How has my net worth changed over the past six months?",
                     "What proportion of my wealth is invested in stocks?",
                     "Did my assets actually increase last month?"):
        assert {C.FINANCIAL, C.INVESTMENT} <= context_routing_manager.route(question).selected


def test_stock_share_does_not_reveal_excluded_financial_totals(session, monkeypatch):
    p = sample()
    p.update(total_assets="1000", stock_value="100")
    monkeypatch.setattr(tools, "_portfolio", lambda ctx: p)
    ctx = ToolContext(session, datetime.now(UTC), frozenset({C.INVESTMENT}))
    assert tools.sheets_portfolio(ctx).data["computed"]["stock_share_of_assets_pct"] is None
    ctx.allowed = frozenset({C.INVESTMENT, C.FINANCIAL})
    assert tools.sheets_portfolio(ctx).data["computed"]["stock_share_of_assets_pct"] == "10.00"
