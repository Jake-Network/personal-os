from datetime import date, datetime, UTC
from decimal import Decimal

from sqlalchemy import select

from app.modules.database.model import (Account, AdvisorConversation, AdvisorMessage, AuditLog,
    ContextSnapshot, Holding, LocalPosition, ManualValueChange, WorkoutLog)


def execute(session, commands, excluded=()):
    from app.modules.advisor.commands.execution import execute_commands
    conversation_id, message_id = source(session)
    return execute_commands(session, commands=commands, conversation_id=conversation_id,
                            message_id=message_id, excluded=set(excluded))


def source(session):
    conversation = AdvisorConversation(title="합성 상담")
    session.add(conversation)
    session.flush()
    message = AdvisorMessage(conversation_id=conversation.id, role="user", content="오늘 러닝 45분 37초 기록해줘")
    session.add(message)
    session.flush()
    return conversation.id, message.id


def test_workout_create_replay_and_rollback_share_the_callers_transaction(session):
    from app.modules.advisor.commands.execution import execute_commands

    conversation_id, message_id = source(session)
    command = {"operation": "create", "resource": "workout-logs", "selector": {},
               "values": {"performed_on": "2026-10-24", "activity": "합성 러닝", "duration_seconds": 2737},
               "source_quote": "오늘 러닝 45분 37초 기록해줘"}
    args = dict(commands=[command], conversation_id=conversation_id, message_id=message_id, excluded=set())
    first = execute_commands(session, **args)
    assert first[0]["status"] == "saved"
    assert first[0]["record"]["duration_seconds"] == 2737
    assert execute_commands(session, **args)[0]["record_id"] == first[0]["record_id"]
    assert len(list(session.scalars(select(WorkoutLog)))) == 1
    assert len(list(session.scalars(select(AuditLog).where(AuditLog.action == "advisor.data_command")))) == 1
    session.rollback()
    assert not list(session.scalars(select(WorkoutLog)))


def test_account_patch_keeps_other_fields_and_exact_value_history(session):
    account = Account(name="합성 통장", kind="deposit", currency="USD", balance=Decimal("1000.1234"),
                      balance_as_of=date(2026, 10, 20), is_liquid=False)
    session.add(account)
    session.flush()
    result = execute(session, [{"operation": "update", "resource": "accounts", "selector": {"name": "합성 통장"},
        "values": {"balance": "3000.4321", "balance_as_of": "2026-10-24"}}])[0]
    assert result["status"] == "saved"
    assert account.balance == Decimal("3000.4321")
    assert account.currency == "USD" and account.is_liquid is False
    history = list(session.scalars(select(ManualValueChange).where(ManualValueChange.record_id == account.id)))
    assert [(row.change_kind, row.new_value) for row in history] == [("baseline", Decimal("1000.1234")), ("update", Decimal("3000.4321"))]


def test_ambiguous_update_broad_delete_and_unknown_fields_do_not_change_rows(session):
    for _ in range(2):
        session.add(Account(name="같은 통장", kind="cash", currency="KRW", balance=Decimal(1), balance_as_of=date(2026, 10, 24)))
    session.flush()
    commands = [
        {"operation": "update", "resource": "accounts", "selector": {"name": "같은 통장"}, "values": {"balance": "9"}},
        {"operation": "delete", "resource": "accounts", "selector": {}},
        {"operation": "create", "resource": "workout-logs", "values": {"performed_on": "2026-10-24", "activity": "test", "duration_seconds": 3, "commit": True}},
        {"operation": "create", "resource": "accounts", "values": {"name": "새 통장", "kind": "cash", "balance": "10", "balance_as_of": "2026-10-24"}},
    ]
    results = execute(session, commands)
    assert all(row["status"] == "needs_input" for row in results)
    assert len(results[0]["candidates"]) == 2
    assert [row.balance for row in session.scalars(select(Account))] == [Decimal(1), Decimal(1)]
    assert not list(session.scalars(select(WorkoutLog)))


def test_holdings_create_and_partial_quantity_edit_preserve_quote_identity_and_cost(session):
    created = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "symbol": "NASDAQ:AAPL", "name": "합성 종목", "currency": "USD", "quantity": 10, "avg_cost": "123.456789012345"}}])[0]
    assert created["status"] == "saved"
    obj = session.get(Holding, created["record_id"])
    obj.last_price, obj.price_as_of = Decimal("200.25"), datetime(2026, 10, 24, tzinfo=UTC)
    session.flush()
    mapping = session.scalar(select(LocalPosition).where(LocalPosition.holding_id == obj.id))
    identity = mapping.position_id
    updated = execute(session, [{"operation": "update", "resource": "holdings", "selector": {"symbol": "NASDAQ:AAPL"},
                                "values": {"quantity": 12}}])[0]
    assert updated["status"] == "saved"
    assert obj.quantity == 12 and obj.avg_cost == Decimal("123.456789012345")
    assert obj.last_price == Decimal("200.25") and mapping.position_id == identity
    assert obj.currency == "USD"
    rejected = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "symbol": "AAPL", "quantity": 10, "currency": "USD"}}])[0]
    assert rejected["status"] == "needs_input"


def test_holdings_store_bare_ticker_cost_and_quantity_before_quote_exchange_is_known(session):
    result = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "ticker": "qastock", "label": "합성 보유 종목", "currency": "USD", "quantity": 3,
        "avg_cost": "19.876543210123"}}])[0]
    assert result["status"] == "saved"
    row = session.get(Holding, result["record_id"])
    assert (row.symbol, row.currency, row.quantity, row.avg_cost) == ("QASTOCK", "USD", Decimal(3), Decimal("19.876543210123"))
    assert row.last_price is row.price_as_of is None
    assert result["quote_status"] == "pending"
    assert result["quote_needs_exchange"] is True
    assert "거래소" in result["message"]
    from app.modules.portfolio.quotes_sheet import quote_rows
    assert quote_rows([row.symbol]) == []
    missing_currency = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "symbol": "QAOTHER", "quantity": 4, "avg_cost": "20.25"}}])[0]
    assert missing_currency["status"] == "needs_input"
    assert session.scalar(select(Holding).where(Holding.symbol == "QAOTHER")) is None


def test_bare_holding_selector_uses_unique_local_identity_and_rejects_ambiguous_symbols(session):
    row = Holding(symbol="NYSEARCA:QAETF", currency="USD", quantity=Decimal(7), avg_cost=Decimal("13.5"))
    session.add(row)
    session.flush()
    updated = execute(session, [{"operation": "update", "resource": "holdings", "selector": {"ticker": "qaetf"},
        "values": {"delta": "5", "avg_cost": "14.25"}}])[0]
    assert updated["status"] == "saved"
    assert (row.symbol, row.quantity, row.avg_cost, row.currency) == ("NYSEARCA:QAETF", Decimal(12), Decimal("14.25"), "USD")
    duplicate = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "symbol": "QAETF", "quantity": 5, "avg_cost": "14.25"}}])[0]
    assert duplicate["status"] == "needs_input"
    assert len(list(session.scalars(select(Holding)))) == 1
    session.add(Holding(symbol="NYSE:QAETF", currency="USD", quantity=Decimal(2)))
    session.flush()
    ambiguous = execute(session, [{"operation": "update", "resource": "holdings", "selector": {"symbol": "QAETF"},
        "values": {"quantity": 1}}])[0]
    assert ambiguous["status"] == "needs_input"
    assert row.quantity == Decimal(12)


def test_new_position_reuses_only_shared_unique_local_symbol_and_currency(session):
    from app.modules.context.record_privacy import set_record_policy
    first = Account(name="합성 첫 계좌", kind="cash", currency="USD", balance=Decimal(0), balance_as_of=date(2026, 10, 24))
    second = Account(name="합성 둘째 계좌", kind="cash", currency="USD", balance=Decimal(0), balance_as_of=date(2026, 10, 24))
    session.add_all([first, second])
    session.flush()
    shared = Holding(account_id=first.id, symbol="NYSEARCA:QAETF", currency="USD", quantity=Decimal(7))
    hidden = Holding(account_id=first.id, symbol="NASDAQ:QAHIDDEN", currency="USD", quantity=Decimal(2))
    session.add_all([shared, hidden])
    session.flush()
    set_record_policy(session, "holdings", hidden.id, False)
    result = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "account_id": second.id, "symbol": "QAETF", "quantity": 3}}])[0]
    assert result["status"] == "saved"
    assert (result["record"]["symbol"], result["record"]["currency"]) == ("NYSEARCA:QAETF", "USD")
    private = execute(session, [{"operation": "create", "resource": "holdings", "values": {
        "account_id": second.id, "symbol": "QAHIDDEN", "quantity": 3}}])[0]
    assert private["status"] == "needs_input"
    assert session.scalar(select(Holding).where(Holding.account_id == second.id, Holding.symbol.like("%QAHIDDEN"))) is None


def test_confirmed_holding_total_becomes_original_addition_without_changing_cost(session):
    from app.modules.advisor.commands.execution import confirmed_holding_addition
    row = Holding(symbol="NYSEARCA:QAETF", currency="USD", quantity=Decimal(7), avg_cost=Decimal("11.25"))
    session.add(row)
    session.flush()
    query = "주식이 더 있어. QAETF $14.25 5주. 추가로 저장해줘"
    original = {"operation": "create", "resource": "holdings", "values": {"symbol": "QAETF", "quantity": 5, "avg_cost": "14.25"}}
    candidate = {"operation": "update", "resource": "holdings", "selector": {"symbol": "QAETF"},
                 "values": {"quantity": 12, "avg_cost": "14.25"}, "source_quote": "응"}
    resolved = confirmed_holding_addition(session, candidate, original_query=query, original_command=original,
        clarification="QAETF는 기존 7주에 5주를 더해 총 12주로 기록하면 될까요?", excluded=set())
    assert resolved["values"] == {"delta": "5", "avg_cost": "14.25"}
    assert candidate["values"] == {"quantity": 12, "avg_cost": "14.25"}
    for invalid in [{**original, "values": {**original["values"], "symbol": "QAOTHER"}},
                    {**original, "values": {**original["values"], "quantity": 3}}]:
        assert confirmed_holding_addition(session, candidate, original_query=query, original_command=invalid,
            clarification="QAETF를 12주로 저장할까요?", excluded=set()) is candidate
    saved = execute(session, [resolved])[0]
    assert saved["status"] == "saved" and row.quantity == Decimal(12)
    assert row.avg_cost == Decimal("14.25")


def test_legacy_confirmed_addition_parses_only_its_own_ticker_line_and_total(session):
    from app.modules.advisor.commands.execution import confirmed_holding_addition
    from app.modules.context.record_privacy import set_record_policy
    row = Holding(symbol="NYSEARCA:QAETF", currency="USD", quantity=Decimal(7))
    session.add(row)
    session.flush()
    query = "다른 주식도 더 있어 추가로 저장해줘\nQAONE $23.75 2주\nQAETF $14.25 5주"
    candidate = {"operation": "update", "resource": "holdings", "selector": {"symbol": "QAETF"}, "values": {"quantity": "12"}}
    def resolve(question, **kwargs):
        return confirmed_holding_addition(session, candidate, original_query=query,
            original_command=None, clarification=question, excluded=set(), **kwargs)
    assert resolve("QAETF는 기존 7주에 5주를 더해 총 12주로 저장할까요?")["values"] == {"delta": "5"}
    for question in ["QAETF 거래소와 통화를 확인해 주세요.", "QAONE은 기존 10주에 2주를 더해 총 12주입니다. QAETF도 저장할까요?",
                     "QAETF는 112주로 저장할까요?", "QAETF 7주와 5주가 맞나요?"]:
        assert resolve(question) is candidate
    row.quantity = Decimal(8)
    session.flush()
    assert resolve("QAETF는 기존 7주에 5주를 더해 총 12주로 저장할까요?") is candidate
    row.quantity = Decimal(7)
    session.flush()
    set_record_policy(session, "holdings", row.id, False)
    assert resolve("QAETF는 기존 7주에 5주를 더해 총 12주로 저장할까요?") is candidate


def test_sharing_blocks_read_update_and_cached_receipts(session):
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.advisor.commands.execution import execute_commands
    account = Account(name="비공개 합성 계좌", kind="cash", currency="USD", balance=Decimal(100), balance_as_of=date(2026, 10, 24))
    session.add(account)
    session.flush()
    holding = Holding(account_id=account.id, symbol="NASDAQ:AAPL", currency="USD", quantity=Decimal(10))
    session.add(holding)
    session.flush()
    conversation_id, message_id = source(session)
    command = {"operation": "update", "resource": "accounts", "selector": {"id": account.id}, "values": {"balance": "200"}}
    args = dict(commands=[command], conversation_id=conversation_id, message_id=message_id, excluded=set())
    assert execute_commands(session, **args)[0]["status"] == "saved"
    set_record_policy(session, "accounts", account.id, False)
    replay = execute_commands(session, **args)[0]
    assert "record" not in replay
    results = execute(session, [
        {"operation": "read", "resource": "accounts"},
        {"operation": "read", "resource": "holdings"},
        {"operation": "update", "resource": "accounts", "selector": {"id": account.id}, "values": {"balance": "999"}},
    ])
    assert results[0]["records"] == results[1]["records"] == []
    assert results[2]["status"] == "failed" and account.balance == Decimal(200)
    excluded = execute(session, [{"operation": "read", "resource": "workout-logs"}], excluded={"health"})
    assert excluded[0]["status"] == "failed" and "records" not in excluded[0]


def test_delete_invalidates_captured_evidence_and_preserves_receipt(session):
    workout = WorkoutLog(performed_on=date(2026, 10, 24), activity="삭제할 합성 운동", duration_seconds=2737)
    session.add(workout)
    session.flush()
    snapshot = ContextSnapshot(id="synthetic-workout", payload={}, context_categories=["health"],
        record_references=[{"table": "workout_logs", "id": workout.id}], source_updated_at={},
        data_quality_flags=[], content_hash="synthetic")
    session.add(snapshot)
    session.flush()
    result = execute(session, [{"operation": "delete", "resource": "workout-logs", "selector": {"id": workout.id}}])[0]
    assert result["status"] == "saved" and result["record"] == {"id": workout.id}
    assert snapshot.payload["source_purged"] is True
    assert session.get(WorkoutLog, workout.id) is None


def test_read_budget_is_disclosed_and_write_failures_do_not_undo_successful_siblings(session):
    result = execute(session, [
        {"operation": "create", "resource": "workout-logs", "values": {"performed_on": "2026-10-24", "activity": "성공 합성 운동", "duration_seconds": 59}},
        {"operation": "create", "resource": "workout-logs", "values": {"performed_on": "2026-10-24", "activity": "실패 합성 운동", "duration_seconds": 0}},
    ])
    assert [row["status"] for row in result] == ["saved", "needs_input"]
    for index in range(45):
        session.add(WorkoutLog(performed_on=date(2026, 10, 24), activity=f"합성 운동 {index}", duration_seconds=60))
    session.flush()
    read = execute(session, [{"operation": "read", "resource": "workout-logs"}])[0]
    assert read["status"] == "read" and len(read["records"]) == len(read["record_refs"]) == 40
    assert read["truncated"] is True and "생략" in read["message"]


def test_delta_uses_exact_server_arithmetic_and_receipt_replay_is_not_added_twice(session):
    from app.modules.advisor.commands.execution import execute_commands
    account = Account(name="합성 증감 계좌", kind="cash", currency="USD", balance=Decimal("100.0001"), balance_as_of=date(2026, 10, 24))
    holding = Holding(symbol="NASDAQ:AAPL", currency="USD", quantity=Decimal(10), avg_cost=Decimal("150.15"))
    session.add_all([account, holding])
    session.flush()
    conversation_id, message_id = source(session)
    commands = [{"operation": "update", "resource": "accounts", "selector": {"id": account.id}, "values": {"delta": "0.0002"}},
                {"operation": "update", "resource": "holdings", "selector": {"id": holding.id}, "values": {"delta": "2"}}]
    args = dict(commands=commands, conversation_id=conversation_id, message_id=message_id, excluded=set())
    assert all(row["status"] == "saved" for row in execute_commands(session, **args))
    assert all(row["status"] == "saved" for row in execute_commands(session, **args))
    assert account.balance == Decimal("100.0003") and holding.quantity == 12
    assert holding.avg_cost == Decimal("150.15")
    invalid = execute(session, [{"operation": "update", "resource": "holdings", "selector": {"id": holding.id}, "values": {"delta": "-13"}}])
    assert invalid[0]["status"] == "needs_input" and holding.quantity == 12


def test_concurrent_replay_serializes_the_same_message_receipt(session):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from app.modules.advisor.commands.execution import execute_commands

    conversation_id, message_id = source(session)
    session.commit()
    command = {"operation": "create", "resource": "workout-logs", "values": {
        "performed_on": "2026-10-24", "activity": "합성 동시 기록", "duration_seconds": 2737}}

    def attempt():
        with Session(session.bind) as writing:
            result = execute_commands(writing, commands=[command], conversation_id=conversation_id,
                                      message_id=message_id, excluded=set())
            writing.commit()
            return result[0]["record_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: attempt(), range(2)))
    assert ids[0] == ids[1]
    assert len(list(session.scalars(select(WorkoutLog)))) == 1
    assert len(list(session.scalars(select(AuditLog).where(AuditLog.action == "advisor.data_command")))) == 1
