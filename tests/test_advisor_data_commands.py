from datetime import date, datetime, UTC
from decimal import Decimal

from sqlalchemy import select

from app.modules.database.model import (Account, AdvisorConversation, AdvisorMessage, AuditLog,
    ContextSnapshot, Holding, LocalPosition, ManualValueChange, WorkoutLog)


def execute(session, commands, excluded=()):
    from app.modules.advisor.data_commands import execute_commands
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
    from app.modules.advisor.data_commands import execute_commands

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


def test_sharing_blocks_read_update_and_cached_receipts(session):
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.advisor.data_commands import execute_commands
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
    from app.modules.advisor.data_commands import execute_commands
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
    from app.modules.advisor.data_commands import execute_commands

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
