"""Pending user-authorized CRUD continues across natural clarification replies."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.database.model import Account, Holding, Task, WorkoutLog
from app.modules.finance.clock import local_today
from test_advisor_runtime_execution import FINAL, finish, runtime_env  # noqa: F401


def data_command(operation, resource, source_quote, *, selector=None, values=None, command_index=None):
    command = {"operation": operation, "resource": resource, "source_quote": source_quote,
               "selector": selector or {}, "values": values or {}}
    if command_index is not None:
        command["command_index"] = command_index
    return command


def consult(env, request_id, query, commands, *, answer=FINAL, **options):
    client, database, provider = env
    offset = len(provider.requests)
    provider.replies.extend([{"commands": commands}, answer])
    response = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": request_id, "message": query, "depth": "auto", **options,
    })
    assert response.status_code == 201, response.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run["status"] == "completed", run
    return run, provider.requests[offset:]


def pending_account(env, *, include_workout=False):
    today = local_today().isoformat()
    query = "합성 보류 입출금 통장에 300만원 있어. 새 계좌로 저장해줘"
    account = data_command("create", "accounts", query, values={
        "name": "합성 보류 통장", "kind": "checking", "balance": "3000000", "balance_as_of": today,
    })
    commands = [account]
    if include_workout:
        query = "오늘 합성 달리기 45분 했어. 운동 기록하고 합성 보류 입출금 통장에 300만원 있어. 새 계좌로 저장해줘"
        account["source_quote"] = query
        commands = [data_command("create", "workout-logs", query, values={
            "performed_on": today, "activity": "합성 이어쓰기 달리기", "duration_seconds": 2700,
        }), account]
    answer = {"answer": "합성 보류 통장을 원화(KRW)로 저장할까요?", "proposals": [], "memories": []}
    run, _ = consult(env, "pending-account-with-workout" if include_workout else "pending-account",
                     query, commands, answer=answer)
    assert run["result"]["data_operations"][-1]["status"] == "needs_input"
    return account


def test_short_confirmation_executes_the_previous_pending_command(runtime_env):
    _, database, _ = runtime_env
    account = pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    resumed = {**account, "command_index": 0, "source_quote": reply,
               "values": {**account["values"], "currency": "KRW"}}
    run, requests = consult(runtime_env, "confirm-pending-account", reply, [resumed])
    with database.session() as session:
        rows = list(session.scalars(select(Account)))
        assert len(rows) == 1, "Confirmation must persist the previously pending account"
        assert rows[0].balance == Decimal("3000000")
        assert rows[0].currency == "KRW"
    assert run["result"]["data_operations"][0]["status"] == "saved"
    assert len(requests) == 2


def test_clarification_only_executes_pending_siblings_and_does_not_repeat_saved_workout(runtime_env):
    _, database, _ = runtime_env
    account = pending_account(runtime_env, include_workout=True)
    with database.session() as session:
        workouts = list(session.scalars(select(WorkoutLog)))
        assert len(workouts) == 1
        original_id = workouts[0].id
    reply = "응 원화로 해줘"
    resumed = {**account, "command_index": 1, "source_quote": reply,
               "values": {**account["values"], "currency": "KRW"}}
    run, _ = consult(runtime_env, "complete-only-pending-account", reply, [resumed])
    assert any(operation["status"] == "saved" and operation["resource"] == "accounts"
               for operation in run["result"]["data_operations"])
    with database.session() as session:
        assert session.scalars(select(WorkoutLog.id)).all() == [original_id]
        assert len(session.scalars(select(Account)).all()) == 1


def plain_consult(env, request_id, query, *, conversation_id=1):
    client, database, provider = env
    offset = len(provider.requests)
    provider.replies.append(FINAL)
    response = client.post(f"/api/advisor/conversations/{conversation_id}/runs", json={
        "request_id": request_id, "message": query, "depth": "auto",
    })
    assert response.status_code == 201, response.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run["status"] == "completed", run
    return run, provider.requests[offset:]


def test_another_yes_after_success_does_not_replay_a_completed_command(runtime_env):
    _, database, _ = runtime_env
    account = pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    consult(runtime_env, "complete-before-second-yes", reply, [{
        **account, "command_index": 0, "source_quote": reply,
        "values": {**account["values"], "currency": "KRW"},
    }])
    run, requests = plain_consult(runtime_env, "second-yes-is-not-another-create", "응 그대로 해줘")
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    assert len(requests) == 1
    with database.session() as session:
        assert len(session.scalars(select(Account)).all()) == 1


def test_pending_account_permission_cannot_authorize_an_unrelated_task(runtime_env):
    _, database, _ = runtime_env
    pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "unrelated-command-in-confirmation", reply, [data_command(
        "create", "tasks", reply, command_index=0, values={"title": "합성 승인 범위 밖 작업"},
    )])
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Task.id)) is None
        assert session.scalar(select(Account.id)) is None


def test_a_new_topic_expires_the_previous_pending_command(runtime_env):
    _, database, _ = runtime_env
    pending_account(runtime_env)
    plain_consult(runtime_env, "new-unrelated-topic", "새로운 질문이야. 일반적인 러닝 조언 부탁해")
    run, requests = plain_consult(runtime_env, "old-pending-must-not-resurface", "응 이렇게 해줘")
    assert len(requests) == 1
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None


def test_pending_commands_never_cross_conversations(runtime_env):
    from app.modules.database.model import AdvisorConversation

    _, database, _ = runtime_env
    pending_account(runtime_env)
    with database.session() as session:
        session.add(AdvisorConversation(id=2, title="합성 별도 상담"))
        session.commit()
    run, requests = plain_consult(runtime_env, "confirmation-in-another-conversation", "응 이렇게 해줘", conversation_id=2)
    assert len(requests) == 1
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None


def test_sharing_revocation_blocks_pending_values_before_transmission_or_write(runtime_env):
    client, database, provider = runtime_env
    account = pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    offset = len(provider.requests)
    provider.replies.extend([{"commands": [{**account, "command_index": 0, "source_quote": reply,
        "values": {**account["values"], "currency": "KRW"}}]}, FINAL])
    response = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "excluded-pending-account", "message": reply, "exclude": ["financial"],
    })
    assert response.status_code == 201, response.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run["status"] in {"completed", "blocked"}, run
    assert not any(operation.get("status") == "saved" for operation in (run.get("result") or {}).get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None
    for request in provider.requests[offset:]:
        outbound = json.dumps([request.instructions, request.input], ensure_ascii=False)
        assert "합성 보류 통장" not in outbound
        assert "3000000" not in outbound


def test_confirmation_cannot_change_the_pending_operation_to_delete(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = Account(name="합성 보존 통장", kind="checking", currency="KRW", balance=Decimal("500000"),
                      balance_as_of=local_today())
        session.add(row)
        session.commit()
        record_id = row.id
    pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "pending-create-is-not-delete-consent", reply, [data_command(
        "delete", "accounts", reply, command_index=0, selector={"id": record_id},
    )])
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.get(Account, record_id) is not None


def test_confirmation_cannot_invent_a_new_amount(runtime_env):
    _, database, _ = runtime_env
    account = pending_account(runtime_env)
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "pending-original-amount-must-be-preserved", reply, [{
        **account, "command_index": 0, "source_quote": reply,
        "values": {**account["values"], "currency": "KRW", "balance": "4000000"},
    }])
    assert not any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None


def test_confirmation_cannot_reexecute_an_already_saved_command_index(runtime_env):
    _, database, _ = runtime_env
    pending_account(runtime_env, include_workout=True)
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "saved-index-cannot-be-reopened", reply, [data_command(
        "create", "workout-logs", reply, command_index=0, values={
            "performed_on": local_today().isoformat(), "activity": "합성 이어쓰기 달리기", "duration_seconds": 2700,
        },
    )])
    with database.session() as session:
        assert len(session.scalars(select(WorkoutLog)).all()) == 1
        assert session.scalar(select(Account.id)) is None


def test_confirmation_recovers_a_legacy_pending_run_without_command_metadata(runtime_env):
    from app.modules.database.model.advisor_runtime import AdvisorRun

    _, database, _ = runtime_env
    account = pending_account(runtime_env)
    with database.session() as session:
        previous = session.scalar(select(AdvisorRun).where(AdvisorRun.request_id == "pending-account"))
        previous.runtime_metadata = {key: value for key, value in previous.runtime_metadata.items()
                                     if not key.startswith("data_command_")}
        session.commit()
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "legacy-pending-confirmation", reply, [{
        **account, "command_index": 0, "source_quote": reply,
        "values": {**account["values"], "currency": "KRW"},
    }])
    assert any(operation.get("status") == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        rows = session.scalars(select(Account)).all()
        assert len(rows) == 1
        assert rows[0].balance == Decimal("3000000")


def test_one_confirmation_saves_a_pending_batch_of_holdings_with_average_costs(runtime_env, monkeypatch):
    _, database, _ = runtime_env
    query = "내 주식 QATESTONE $12.34 3주, QATESTTWO $56.78 5주 있어. 가격은 평균 매입가야. 전부 저장해줘"
    commands = [data_command("create", "holdings", query, values={
        "symbol": symbol, "name": label, "quantity": quantity, "avg_cost": cost,
    }) for symbol, label, quantity, cost in [
        ("QATESTONE", "합성 첫 보유 종목", 3, "12.34"),
        ("QATESTTWO", "합성 둘째 보유 종목", 5, "56.78"),
    ]]
    answer = {"answer": "첫 종목 NASDAQ:QATESTONE, 둘째 NYSEARCA:QATESTTWO, 통화 USD, 가격은 평균 매입가로 기록할까요?",
              "proposals": [], "memories": []}
    initial, _ = consult(runtime_env, "pending-holdings-batch", query, commands, answer=answer)
    assert all(operation["status"] == "needs_input" for operation in initial["result"]["data_operations"])
    reply = "응 이렇게 해줘"
    resolved = [{**command, "command_index": index, "source_quote": reply,
                 "values": {**command["values"], "symbol": f"{exchange}:{command['values']['symbol']}", "currency": "USD"}}
                for index, (command, exchange) in enumerate(zip(commands, ["NASDAQ", "NYSEARCA"], strict=True))]
    monkeypatch.setattr('app.modules.portfolio.symbol_directory.symbol_directory.resolve',
        lambda symbol, currency='USD': {'status': 'resolved',
            'symbol': ('NASDAQ:' if symbol == 'QATESTONE' else 'NYSEARCA:') + symbol,
            'source': 'nasdaq_trader', 'as_of': '2026-10-24T00:00:00+00:00', 'candidates': []})
    run, _ = consult(runtime_env, "confirm-holdings-batch", reply, resolved)
    assert all(operation["status"] == "saved" for operation in run["result"]["data_operations"])
    with database.session() as session:
        rows = session.scalars(select(Holding).order_by(Holding.id)).all()
        assert [(row.symbol, row.currency, row.quantity, row.avg_cost) for row in rows] == [
            ("NASDAQ:QATESTONE", "USD", Decimal("3"), Decimal("12.34")),
            ("NYSEARCA:QATESTTWO", "USD", Decimal("5"), Decimal("56.78")),
        ]
        assert all(row.last_price is None for row in rows)


def test_partial_holdings_confirmation_only_adds_pending_quantity_to_existing_position(runtime_env):
    _, database, _ = runtime_env
    quoted_at = datetime.now(UTC)
    with database.session() as session:
        existing = Holding(symbol="NYSEARCA:QAETF", name="합성 기존 ETF", currency="USD",
                           quantity=Decimal("7"), avg_cost=Decimal("100.10"),
                           last_price=Decimal("150.50"), price_as_of=quoted_at)
        session.add(existing)
        session.commit()
        existing_id = existing.id
    query = "내 주식 QASTOCK $25.11 4주, QAETF $132.21 5주 더 있어. 가격은 평균 매입가야. 추가로 저장해줘"
    first = data_command("create", "holdings", query, values={
        "symbol": "QASTOCK", "name": "합성 새 종목", "currency": "USD", "quantity": 4, "avg_cost": "25.11",
    })
    pending = data_command("create", "holdings", query, values={
        "symbol": "QAETF", "currency": "USD", "quantity": 5, "avg_cost": "132.21",
    })
    answer = {"answer": "첫 종목은 저장했습니다. 기존 ETF 7주에 5주를 더해 12주로 기록할까요?",
              "proposals": [], "memories": []}
    initial, _ = consult(runtime_env, "partial-stock-batch", query, [first, pending], answer=answer)
    assert [operation["status"] for operation in initial["result"]["data_operations"]] == ["saved", "needs_input"]
    with database.session() as session:
        saved_new = session.scalar(select(Holding).where(Holding.symbol == "QASTOCK"))
        assert saved_new is not None
        saved_new_id = saved_new.id
        assert session.get(Holding, existing_id).quantity == Decimal("7")
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "confirm-only-existing-etf-addition", reply, [data_command(
        "update", "holdings", reply, selector={"symbol": "QAETF"}, command_index=1,
        values={"delta": 5, "avg_cost": "132.21", "currency": "USD"},
    )])
    assert any(operation["status"] == "saved" and operation.get("command_index") == 1
               for operation in run["result"]["data_operations"])
    with database.session() as session:
        assert session.scalars(select(Holding.id).where(Holding.symbol == "QASTOCK")).all() == [saved_new_id]
        assert session.get(Holding, saved_new_id).quantity == Decimal("4")
        existing = session.get(Holding, existing_id)
        assert existing.quantity == Decimal("12")
        assert existing.avg_cost == Decimal("132.21")
        assert (existing.last_price, existing.price_as_of) == (Decimal("150.50"), quoted_at)


def test_bare_confirmation_cannot_swap_pending_holding_quantity_and_average_cost(runtime_env):
    _, database, _ = runtime_env
    query = "내 합성 보유 종목 QASWAP 10주 있고 평균 매입가는 200이야. 저장해줘"
    pending = data_command("create", "holdings", query, values={
        "symbol": "QASWAP", "quantity": 10, "avg_cost": "200",
    })
    initial, _ = consult(runtime_env, "pending-holding-field-locks", query, [pending], answer={
        "answer": "통화가 빠졌습니다. USD로 기록할까요?", "proposals": [], "memories": [],
    })
    assert initial["result"]["data_operations"][0]["status"] == "needs_input"
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "swapped-fields-are-not-confirmed", reply, [{
        **pending, "command_index": 0, "source_quote": reply,
        "values": {"symbol": "QASWAP", "currency": "USD", "quantity": 200, "avg_cost": "10"},
    }])
    assert not any(operation["status"] == "saved" for operation in run["result"]["data_operations"])
    with database.session() as session:
        assert session.scalar(select(Holding.id)) is None


@pytest.mark.parametrize("legacy_metadata", [False, True], ids=["recorded-plan", "legacy-plan"])
def test_approved_holding_total_is_applied_as_the_original_addition(runtime_env, legacy_metadata):
    from app.modules.database.model.advisor_runtime import AdvisorRun

    _, database, _ = runtime_env
    quoted_at = datetime.now(UTC)
    with database.session() as session:
        row = Holding(symbol="NYSEARCA:QAETF", name="합성 추가 보유 ETF", currency="USD",
                      quantity=Decimal("7"), avg_cost=Decimal("90.12"),
                      last_price=Decimal("150.50"), price_as_of=quoted_at)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "내 QAETF 5주 더 있어. 평균 매입가는 132.21달러야. 추가로 저장해줘"
    pending = data_command("create", "holdings", query, values={
        "symbol": "QAETF", "quantity": 5, "avg_cost": "132.21", "currency": "USD",
    })
    initial, _ = consult(runtime_env, "pending-existing-holding-addition", query, [pending], answer={
        "answer": "QAETF는 기존 7주에 추가 5주를 더해 총 12주로 저장할까요?",
        "proposals": [], "memories": [],
    })
    assert initial["result"]["data_operations"][0]["status"] == "needs_input"
    with database.session() as session:
        assert session.get(Holding, record_id).quantity == Decimal("7")
        if legacy_metadata:
            previous = session.scalar(select(AdvisorRun).where(AdvisorRun.request_id == "pending-existing-holding-addition"))
            previous.runtime_metadata = {key: value for key, value in previous.runtime_metadata.items()
                                         if not key.startswith("data_command_")}
            session.commit()
    reply = "응 이렇게 해줘"
    run, _ = consult(runtime_env, "confirm-proposed-holding-total", reply, [data_command(
        "update", "holdings", reply, selector={"symbol": "QAETF"}, command_index=0,
        values={"quantity": 12, "avg_cost": "132.21", "currency": "USD"},
    )])
    assert run["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        rows = session.scalars(select(Holding)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.id == record_id
        assert row.quantity == Decimal("12")
        assert row.avg_cost == Decimal("132.21")
        assert (row.last_price, row.price_as_of) == (Decimal("150.50"), quoted_at)


def test_source_sharing_revocation_during_extraction_blocks_the_pending_write(runtime_env):
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.database.model.advisor_runtime import AdvisorRun

    client, database, provider = runtime_env
    account = pending_account(runtime_env)
    with database.session() as session:
        previous = session.scalar(select(AdvisorRun).where(AdvisorRun.request_id == "pending-account"))
        original_message_id = previous.user_message_id
    reply = "응 이렇게 해줘"
    revoked = []

    async def revoke_original_message_before_returning_commands():
        with database.session() as session:
            set_record_policy(session, "advisor_messages", original_message_id, False)
        revoked.append(original_message_id)
        return {"commands": [{**account, "command_index": 0, "source_quote": reply,
                               "values": {**account["values"], "currency": "KRW"}}]}

    offset = len(provider.requests)
    provider.replies.extend([revoke_original_message_before_returning_commands, FINAL])
    created = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "source-revoked-during-extraction", "message": reply, "depth": "auto",
    })
    assert created.status_code == 201, created.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{created.json()['id']}").json()
    assert revoked == [original_message_id], "Sharing must change during the model request, not before it"
    assert run["status"] in {"blocked", "failed"}, run
    assert "공유" in (run.get("error") or ""), "The failure must report revoked source authority, not a lock or generic error"
    assert not any(operation.get("status") == "saved" for operation in (run.get("result") or {}).get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None
    assert len(provider.requests) == offset + 1, "A revoked source must not reach another model request"
