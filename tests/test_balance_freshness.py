from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.enums.context_category import Category
from app.modules.context.context_tool_manager import get_accounts_summary
from app.modules.context.types import ToolContext
from app.modules.database.model import Account
from app.modules.finance import clock
from app.schema.domain_schema import AccountItem


@pytest.mark.parametrize("age, stale", [(2, False), (3, True)])
def test_account_response_and_advisor_use_the_same_freshness_policy(session, monkeypatch, age, stale):
    today = date(2026, 10, 20)
    monkeypatch.setattr(clock, "STALE_BALANCE_DAYS", 2, raising=False)
    monkeypatch.setattr(clock, "local_today", lambda: today)
    account = Account(name="합성 정책", kind="cash", currency="KRW", balance=Decimal("100"),
                      balance_as_of=today - timedelta(days=age))
    session.add(account)
    session.flush()
    ctx = ToolContext(session, datetime(2026, 10, 20, 12, tzinfo=UTC),
                      frozenset({Category.FINANCIAL, Category.INVESTMENT}))
    result = get_accounts_summary(ctx)
    assert AccountItem.model_validate(account).balance_stale is stale
    assert any(flag["code"] == "stale_balance" for flag in result.flags) is stale


def test_balance_staleness_uses_app_day_at_utc_midnight_boundary(session, monkeypatch):
    from dataclasses import replace
    from app.modules.context import context_tool_manager
    local_day = date(2026, 10, 21)
    monkeypatch.setattr(clock, 'local_today', lambda: local_day)
    monkeypatch.setattr(context_tool_manager, 'settings', replace(context_tool_manager.settings, timezone='Asia/Seoul'))
    account = Account(name='합성 날짜 경계', kind='cash', currency='KRW', balance=Decimal('100'),
                      balance_as_of=local_day - timedelta(days=45 + 1))
    session.add(account)
    session.flush()
    ctx = ToolContext(session, datetime(2026, 10, 20, 15, 30, tzinfo=UTC),
                      frozenset({Category.FINANCIAL, Category.INVESTMENT}))
    assert AccountItem.model_validate(account).balance_stale
    assert any(flag['code'] == 'stale_balance' for flag in get_accounts_summary(ctx).flags)
