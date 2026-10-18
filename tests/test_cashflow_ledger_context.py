"""The advisor and dashboard read the same append-only cashflow facts."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.enums.context_category import Category
from app.modules.context.context_builder_manager import context_builder_manager
from app.modules.context.context_tool_manager import get_cashflow_summary
from app.modules.context.types import ToolContext
from app.modules.database.model import CashflowEntry, FinancialTransaction

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


def add_transaction(session, key, kind, when, amount="2000000", **payload):
    row = FinancialTransaction(request_id=key, kind=kind, occurred_at=when,
        reverses_id=payload.get("reverses_id"), payload={"amount": amount, "currency": "KRW", **payload})
    session.add(row)
    session.flush()
    return row


def cashflow(session):
    return get_cashflow_summary(ToolContext(session, NOW, frozenset({Category.FINANCIAL})))


def test_ledger_expenses_and_distinct_legacy_entries_are_additive(session):
    for month in (7, 8, 9):
        session.add(CashflowEntry(occurred_on=NOW.date().replace(month=month, day=5), kind="expense", amount=Decimal("1000000")))
        add_transaction(session, str(month), "expense", NOW.replace(month=month, day=5))
    add_transaction(session, "transfer", "transfer", NOW.replace(month=9), "99999999")
    result = cashflow(session)
    assert result.data["monthly_expense"]["monthly_average"] == "3000000.00"
    assert {r["table"] for r in result.refs} >= {"financial_transactions", "cashflow_entries"}
    assert any(f["code"] == "cashflow_mixed_sources" for f in result.flags)


def test_reversal_outside_window_removes_only_ledger_original(session):
    session.add(CashflowEntry(occurred_on=NOW.date().replace(month=9), kind="expense", amount=Decimal("1000000")))
    original = add_transaction(session, "original", "expense", NOW.replace(month=9))
    add_transaction(session, "reversed", "reversal", NOW, reverses_id=original.id)
    result = cashflow(session)
    assert result.data["monthly_expense"]["estimate"]["monthly_average"] == "1000000.00"
    assert result.data["expense_by_category_12m"] == {"uncategorized": "1000000.00"}


def test_ledger_dates_use_product_timezone_and_ignore_future_entries(session):
    add_transaction(session, "boundary", "expense", datetime(2026, 6, 30, 16, tzinfo=UTC))
    for month in (8, 9):
        add_transaction(session, str(month), "expense", NOW.replace(month=month))
    add_transaction(session, "future", "expense", NOW + timedelta(days=1), "99999999")
    result = cashflow(session)
    assert result.data["monthly_expense"]["monthly_average"] == "2000000.00"
    assert result.data["expense_by_category_12m"] == {"uncategorized": "6000000.00"}


def test_local_only_transaction_blocks_external_summary_but_not_dashboard(session):
    from app.modules.context.record_privacy import set_record_policy
    row = add_transaction(session, "private", "expense", NOW.replace(month=9))
    session.commit()
    set_record_policy(session, "financial_transactions", row.id, False)
    selected = frozenset({Category.FINANCIAL})
    external, _, flags, _ = context_builder_manager.collect(session, selected, NOW)
    assert "get_cashflow_summary" not in external
    assert any(f["code"] == "records_excluded_by_user" for f in flags)
    local, _, _, _ = context_builder_manager.collect(session, selected, NOW, external_sharing=False)
    assert local["get_cashflow_summary"]["monthly_expense"]["months_with_data"] == 1


def test_unrecorded_cash_is_unknown_but_confirmed_empty_cash_is_zero(session):
    from app.modules.context.context_tool_manager import get_accounts_summary
    from app.modules.database.model import LocalFinanceCoverage
    ctx = ToolContext(session, NOW, frozenset({Category.FINANCIAL}))
    worth = get_accounts_summary(ctx).data["computed"]["net_worth"]
    assert worth["spendable_liquidity"] is None
    from app.modules.finance.financial_calculator import financial_calculator
    assert financial_calculator.cash_runway(worth, {"available": True, "monthly_average": "100"})["reason"] == "spendable_liquidity_unknown"
    session.add(LocalFinanceCoverage(id=1, kinds=["cash"]))
    session.commit()
    assert get_accounts_summary(ctx).data["computed"]["net_worth"]["spendable_liquidity"] == "0.00"


def test_upcoming_interviews_exclude_past_interviews(session):
    from app.modules.context.context_tool_manager import get_interview_schedule
    from app.modules.database.model import Interview, JobApplication
    application = JobApplication(company="synthetic", role="engineer", status="interviewing")
    session.add(application)
    session.flush()
    session.add_all([Interview(application_id=application.id, stage="past", starts_at=NOW-timedelta(hours=1)),
                     Interview(application_id=application.id, stage="upcoming", starts_at=NOW+timedelta(hours=1))])
    session.commit()
    result = get_interview_schedule(ToolContext(session, NOW, frozenset({Category.CAREER})))
    assert [row["stage"] for row in result.data["interviews"]] == ["upcoming"]


def test_api_ledger_reaches_model_and_account_privacy_removes_summary_and_history(client, session, fake_provider):
    import json
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.database.model import Account
    from app.modules.context.record_privacy import set_record_policy
    from tests.test_advisor_product_context import ask

    now = datetime.now(UTC)
    account = Account(name="synthetic cash", kind="checking", currency="KRW", balance=Decimal("9000000"), balance_as_of=now.date())
    session.add(account)
    session.commit()
    month = now.date().replace(day=1)
    for n in range(3):
        month = (month - timedelta(days=1)).replace(day=1)
        response = client.post("/api/finance/transactions", json={
            "request_id": f"qa-expense-{n}", "kind": "expense", "amount": "2345678",
            "occurred_at": datetime.combine(month.replace(day=5), datetime.min.time(), UTC).isoformat(),
            "source": "synthetic", "account_id": account.id})
        assert response.status_code == 201, response.text
    conversation = advisor_manager.create_conversation(session, "cashflow")
    fake_provider.reply = "지출 근거 2345678원입니다."
    package = ask(session, conversation, "월평균 지출 알려줘", fake_provider)
    assert package["data"]["get_cashflow_summary"]["monthly_expense"]["monthly_average"] == "2345678.00"
    set_record_policy(session, "accounts", account.id, False)
    package = ask(session, conversation, "월평균 지출 다시 알려줘", fake_provider)
    assert "get_cashflow_summary" not in package["data"]
    assert "2345678" not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_transaction_dependency_rechecks_linked_account_and_record_policy(session):
    from app.modules.context.source_policy import source_allowed
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.database.model import Account
    account = Account(name="synthetic", kind="checking", balance=1, balance_as_of=NOW.date())
    session.add(account)
    session.flush()
    row = add_transaction(session, "linked", "expense", NOW, account_id=account.id)
    session.commit()
    ref = [{"table": "financial_transactions", "id": row.id}]
    assert source_allowed(session, ref)
    set_record_policy(session, "accounts", account.id, False)
    assert not source_allowed(session, ref)


def test_ledger_income_expense_kinds_and_foreign_currency_flags(session):
    for month in (7, 8, 9):
        for kind, amount in (("expense", "100"), ("fee", "20"), ("tax", "30"),
                             ("income", "1000"), ("dividend", "100"), ("interest", "10"),
                             ("repayment", "9000"), ("buy", "9000"), ("sell", "9000")):
            add_transaction(session, f"{month}-{kind}", kind, NOW.replace(month=month), amount)
    add_transaction(session, "foreign", "expense", NOW.replace(month=9), "9999", currency="USD")
    result = cashflow(session)
    assert result.data["monthly_expense"]["monthly_average"] == "150.00"
    assert result.data["monthly_income"]["monthly_average"] == "1110.00"
    assert any(f["code"] == "cashflow_foreign_currency_ignored" for f in result.flags)


def test_monthly_window_uses_local_current_month_at_utc_boundary(session):
    for month in (7, 8, 9):
        add_transaction(session, str(month), "expense", NOW.replace(month=month, day=5), "100")
    local_october = datetime(2026, 9, 30, 16, tzinfo=UTC)
    result = get_cashflow_summary(ToolContext(session, local_october, frozenset({Category.FINANCIAL})))
    assert result.data["monthly_expense"]["recorded_months"] == ["2026-07", "2026-08", "2026-09"]
    assert result.data["monthly_expense"]["monthly_average"] == "100.00"


def test_investment_exclusion_omits_linked_cashflow_before_model_payload(session, fake_provider):
    import json
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.types import AskOptions
    from app.modules.database.model import Holding
    from tests.test_advisor_product_context import ask

    holding = Holding(symbol="SYNTH", name="synthetic", currency="KRW", quantity=1)
    session.add(holding)
    session.flush()
    now = datetime.now(UTC)
    for month_back in (1, 2, 3):
        day = now.date().replace(day=1)
        for _ in range(month_back):
            day = (day-timedelta(days=1)).replace(day=1)
        add_transaction(session, f"dividend-{month_back}", "dividend",
                        datetime.combine(day, datetime.min.time(), UTC), "8765432", holding_id=holding.id)
    session.commit()
    conversation = advisor_manager.create_conversation(session, "limited sharing")
    package = ask(session, conversation, "월평균 수입 알려줘", fake_provider,
        AskOptions(categories=frozenset({Category.FINANCIAL}), exclude=frozenset({Category.INVESTMENT})))
    assert "get_accounts_summary" in package["data"]
    assert "get_cashflow_summary" not in package["data"]
    assert any(f["code"] == "source_sharing_scope_excluded" for f in package["data_quality_flags"])
    assert "8765432" not in json.dumps(fake_provider.requests[-1].input)
    local, _, _, _ = context_builder_manager.collect(session, frozenset({Category.FINANCIAL}), now, external_sharing=False)
    assert local["get_cashflow_summary"]["monthly_income"]["monthly_average"] == "8765432.00"


def test_historical_financial_snapshot_recurses_transaction_investment_dependency(session, fake_provider):
    import json
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.types import AskOptions
    from app.modules.context.source_policy import source_allowed
    from app.modules.database.model import AdvisorMessage, ContextSnapshot, Holding
    from tests.test_advisor_product_context import ask
    conversation = advisor_manager.create_conversation(session, "historical scope")
    holding = Holding(symbol="SYNTH", currency="KRW", quantity=1)
    session.add(holding)
    session.flush()
    transaction = add_transaction(session, "linked-dividend", "dividend", NOW, holding_id=holding.id)
    snapshot = ContextSnapshot(id="old-financial-ledger", generated_at=NOW, conversation_id=conversation.id,
        context_categories=["financial"], excluded_categories=[],
        record_references=[{"table": "financial_transactions", "id": transaction.id}],
        source_updated_at={}, data_quality_flags=[], payload={"data": {}}, content_hash="old")
    session.add(snapshot)
    session.commit()
    refs = [{"table": "context_snapshots", "id": snapshot.id}]
    assert source_allowed(session, refs)
    assert not source_allowed(session, refs, frozenset({Category.INVESTMENT}))
    session.add_all([AdvisorMessage(conversation_id=conversation.id, role="user", content="이전 재무 조회",
                                   context_snapshot_id=snapshot.id),
                     AdvisorMessage(conversation_id=conversation.id, role="assistant", content="이전 배당 7654321원",
                                   context_snapshot_id=snapshot.id)])
    session.commit()
    ask(session, conversation, "월평균 수입 다시 알려줘", fake_provider,
        AskOptions(categories=frozenset({Category.FINANCIAL}), exclude=frozenset({Category.INVESTMENT})))
    assert "7654321" not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
