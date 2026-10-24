"""Natural-language data commands cross the real worker, persistence and outbound boundary."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.database.model import Account, ContextSnapshot, Goal, Holding, Task, WorkoutLog
from app.modules.finance.clock import local_today
from test_advisor_runtime_execution import FINAL, finish, runtime_env  # noqa: F401


def command(operation, resource, query, *, selector=None, values=None):
    return {
        "operation": operation,
        "resource": resource,
        "selector": selector or {},
        "values": values or {},
        "source_quote": query,
    }


def consult(env, request_id, query, commands, **options):
    client, database, provider = env
    offset = len(provider.requests)
    provider.replies.extend([{"commands": commands}, FINAL])
    created = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": request_id, "message": query, "depth": "auto", **options,
    })
    assert created.status_code == 201, created.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{created.json()['id']}").json()
    assert run["status"] == "completed", run
    return run, provider.requests[offset:]


def package(request):
    context = next(item["content"] for item in request.input
                   if item["role"] == "developer" and item["content"].startswith("Context Package"))
    return json.loads(context.split("\n", 1)[1])


def test_explicit_workout_command_persists_seconds_before_answer_and_replays_once(runtime_env):
    client, database, provider = runtime_env
    query = "나 오늘 10km 대회에서 45분 37초 뛰었어. 운동 기록해줘"
    run, requests = consult(runtime_env, "workout-create", query, [command(
        "create", "workout-logs", query,
        values={"performed_on": local_today().isoformat(), "activity": "합성 10km 대회", "duration_seconds": 2737},
    )])
    with database.session() as session:
        record = session.scalar(select(WorkoutLog))
        assert record is not None, "The consultation must create a real workout record"
        assert record.duration_seconds == 2737
        record_id = record.id
    assert run["result"]["data_operations"][0]["status"] == "saved"
    final_package = package(requests[-1])
    assert final_package["data"]["get_health_summary"]["recent"][0]["seconds"] == 2737
    assert final_package["data"]["advisor_data_operations"][0]["status"] == "saved"
    with database.session() as session:
        snapshot = session.get(ContextSnapshot, run["result"]["context_snapshot_id"])
        assert "health" in snapshot.context_categories
        assert any(ref.get("table") == "workout_logs" and ref.get("id") == record_id
                   for ref in snapshot.record_references)

    offset = len(provider.requests)
    replay = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "workout-create", "message": query, "depth": "auto",
    })
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == run["id"]
    assert len(provider.requests) == offset
    with database.session() as session:
        assert session.scalars(select(WorkoutLog.id)).all() == [record_id]

    # A later sharing restriction also blocks receipts and old conversation text.
    provider.replies.append(FINAL)
    restricted = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "workout-after-sharing-exclusion", "message": "달리기 조언 부탁해", "exclude": ["health"],
    })
    assert restricted.status_code == 201, restricted.text
    finish(database)
    assert client.get(f"/api/advisor/runs/{restricted.json()['id']}").json()["status"] == "completed"
    outbound = json.dumps([provider.requests[-1].instructions, provider.requests[-1].input], ensure_ascii=False)
    assert "합성 10km 대회" not in outbound
    assert "get_health_summary" not in outbound


def test_workout_read_update_and_delete_use_the_same_real_record(runtime_env):
    _, database, _ = runtime_env
    today = local_today()
    with database.session() as session:
        row = WorkoutLog(performed_on=today, activity="합성 인터벌", duration_seconds=2700)
        session.add(row)
        session.commit()
        record_id = row.id
    selector = {"activity": "합성 인터벌", "performed_on": today.isoformat()}

    query = "오늘 합성 인터벌 운동 기록 조회해줘"
    read, _ = consult(runtime_env, "workout-read", query, [command("read", "workout-logs", query, selector=selector)])
    operation = read["result"]["data_operations"][0]
    assert operation["status"] == "read"
    assert "2700" in json.dumps(operation)

    query = "오늘 합성 인터벌 운동 시간을 45분 37초로 수정해줘"
    updated, requests = consult(runtime_env, "workout-update", query, [command(
        "update", "workout-logs", query, selector=selector, values={"duration_seconds": 2737},
    )])
    assert updated["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        row = session.get(WorkoutLog, record_id)
        assert (row.activity, row.performed_on, row.duration_seconds) == ("합성 인터벌", today, 2737)
    assert package(requests[-1])["data"]["get_health_summary"]["recent"][0]["seconds"] == 2737

    query = "오늘 합성 인터벌 운동 기록 삭제해줘"
    deleted, _ = consult(runtime_env, "workout-delete", query, [command("delete", "workout-logs", query, selector=selector)])
    assert deleted["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        assert session.get(WorkoutLog, record_id) is None


def test_account_balance_update_keeps_decimal_and_other_fields(runtime_env):
    _, database, _ = runtime_env
    today = local_today()
    with database.session() as session:
        row = Account(name="합성 생활비 통장", institution="합성 은행", kind="checking", currency="KRW",
                      balance=Decimal("1000000"), balance_as_of=today, is_liquid=True)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "합성 생활비 통장 잔액을 3000000.12원으로 수정해줘"
    updated, requests = consult(runtime_env, "account-balance-update", query, [command(
        "update", "accounts", query, selector={"name": "합성 생활비 통장"},
        values={"balance": "3000000.12", "balance_as_of": today.isoformat()},
    )])
    assert updated["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        row = session.get(Account, record_id)
        assert row.balance == Decimal("3000000.12")
        assert (row.name, row.institution, row.currency, row.is_liquid) == ("합성 생활비 통장", "합성 은행", "KRW", True)
    assert "3000000.12" in json.dumps(package(requests[-1]))


def test_ambiguous_account_update_does_not_choose_a_record(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        for amount in ("1000000", "2000000"):
            session.add(Account(name="합성 중복 통장", kind="checking", currency="KRW", balance=Decimal(amount),
                                balance_as_of=local_today(), is_liquid=True))
        session.commit()
    query = "합성 중복 통장 잔액을 3000000원으로 수정해줘"
    run, _ = consult(runtime_env, "ambiguous-account", query, [command(
        "update", "accounts", query, selector={"name": "합성 중복 통장"}, values={"balance": "3000000"},
    )])
    assert run["result"]["data_operations"][0]["status"] == "needs_input"
    with database.session() as session:
        assert sorted(session.scalars(select(Account.balance)).all()) == [Decimal("1000000"), Decimal("2000000")]


def test_holding_quantity_update_preserves_cost_and_quote(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = Holding(symbol="NASDAQ:AAPL", name="합성 주식", market="NASDAQ", currency="USD", quantity=Decimal("2"),
                      avg_cost=Decimal("100.50"), last_price=Decimal("120.25"), price_as_of=datetime.now(UTC))
        session.add(row)
        session.commit()
        record_id = row.id
    query = "NASDAQ:AAPL 보유량을 10주로 수정해줘"
    run, requests = consult(runtime_env, "holding-quantity", query, [command(
        "update", "holdings", query, selector={"symbol": "NASDAQ:AAPL"}, values={"quantity": 10},
    )])
    assert run["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        row = session.get(Holding, record_id)
        assert row.quantity == Decimal("10")
        assert (row.name, row.avg_cost, row.last_price) == ("합성 주식", Decimal("100.50"), Decimal("120.25"))
    assert "NASDAQ:AAPL" in json.dumps(package(requests[-1]))


def test_excluded_health_commands_do_not_read_or_change_private_records(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = WorkoutLog(performed_on=local_today(), activity="합성 공유 제외 운동", duration_seconds=59)
        session.add(row)
        session.commit()
    query = "오늘 운동 기록 조회해줘"
    run, requests = consult(runtime_env, "private-workout", query,
                            [command("read", "workout-logs", query)], exclude=["health"])
    assert all(operation["status"] != "read" for operation in run["result"].get("data_operations", []))
    for request in requests:
        outbound = json.dumps([request.instructions, request.input], ensure_ascii=False)
        assert "합성 공유 제외 운동" not in outbound
        assert "get_health_summary" not in outbound


def test_model_command_without_current_user_evidence_cannot_write(runtime_env):
    _, database, _ = runtime_env
    query = "오늘 운동 시간을 조회해줘"
    invented = command("create", "workout-logs", "운동 기록을 저장해줘", values={
        "performed_on": local_today().isoformat(), "activity": "합성 없는 지시", "duration_seconds": 2737,
    })
    run, _ = consult(runtime_env, "invented-write-command", query, [invented])
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.id)) is None


def test_quoted_account_command_cannot_borrow_authority_from_workout_request(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = Account(name="합성 통장", kind="checking", currency="KRW", balance=Decimal("1000000"),
                      balance_as_of=local_today(), is_liquid=True)
        session.add(row)
        session.commit()
        record_id = row.id
    quoted = "합성 통장 잔액 999만원으로 바꿔줘"
    query = f"친구가 '{quoted}'라고 말했어. 오늘 합성 운동 45분 기록해줘"
    run, _ = consult(runtime_env, "quoted-account-command", query, [command(
        "update", "accounts", quoted, selector={"name": "합성 통장"}, values={"balance": "9990000"},
    )])
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.get(Account, record_id).balance == Decimal("1000000")


def test_saved_receipt_survives_answer_failure_and_retry_does_not_reextract(runtime_env):
    client, database, provider = runtime_env
    query = "오늘 합성 러닝 45분 37초 운동 기록해줘"
    create_command = command("create", "workout-logs", query, values={
        "performed_on": local_today().isoformat(), "activity": "합성 러닝", "duration_seconds": 2737,
    })
    provider.replies.extend([{"commands": [create_command]}, RuntimeError("synthetic answer outage")])
    created = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "saved-answer-outage", "message": query, "depth": "auto",
    })
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    finish(database)
    failed = client.get(f"/api/advisor/runs/{run_id}").json()
    assert failed["status"] in {"failed", "blocked"}, failed
    assert failed["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        record_id = session.scalar(select(WorkoutLog.id))
        assert record_id is not None

    offset = len(provider.requests)
    retried = client.post(f"/api/advisor/runs/{run_id}/retry")
    assert retried.status_code == 200, retried.text
    provider.replies.append(FINAL)
    finish(database)
    completed = client.get(f"/api/advisor/runs/{run_id}").json()
    assert completed["status"] == "completed", completed
    assert completed["result"]["data_operations"][0]["status"] == "saved"
    assert len(provider.requests) == offset + 1, "Retry must reuse committed operations and only regenerate the answer"
    with database.session() as session:
        assert session.scalars(select(WorkoutLog.id)).all() == [record_id]


def test_completed_fact_is_recorded_only_after_opt_in(runtime_env):
    client, database, provider = runtime_env
    query = "나 오늘 10km 45분 나왔어"
    provider.replies.append(FINAL)
    created = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "fact-default-off", "message": query,
    })
    assert created.status_code == 201, created.text
    finish(database)
    assert client.get(f"/api/advisor/runs/{created.json()['id']}").json()["status"] == "completed"
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.id)) is None
    assert len(provider.requests) == 1

    recorded, _ = consult(runtime_env, "fact-opt-in", query, [command("create", "workout-logs", query, values={
        "performed_on": local_today().isoformat(), "activity": "달리기", "duration_seconds": 2700,
        "notes": query,
    })], allow_data_recording=True)
    assert recorded["result"]["data_operations"][0]["status"] == "saved"
    with database.session() as session:
        row = session.scalar(select(WorkoutLog))
        assert row.duration_seconds == 2700
        assert row.notes == query


@pytest.mark.parametrize("query", [
    "나 내일 10km를 45분에 뛰려고 해",
    "친구가 오늘 10km를 45분에 뛰었어",
])
def test_auto_recording_does_not_record_future_or_other_person(runtime_env, query):
    client, database, provider = runtime_env
    provider.replies.append(FINAL)
    created = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "non-observation", "message": query, "allow_data_recording": True,
    })
    assert created.status_code == 201, created.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{created.json()['id']}").json()
    assert run["status"] == "completed", run
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.id)) is None
    assert len(provider.requests) == 1


def test_auto_recording_does_not_authorize_implicit_delete(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = WorkoutLog(performed_on=local_today(), activity="합성 달리기", duration_seconds=2700)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "나 오늘 운동 45분 뛰었어"
    run, _ = consult(runtime_env, "fact-delete-not-authorized", query, [command(
        "delete", "workout-logs", query, selector={"id": record_id},
    )], allow_data_recording=True)
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.get(WorkoutLog, record_id) is not None


def test_automatic_observation_does_not_authorize_task_or_goal_creation(runtime_env):
    _, database, _ = runtime_env
    query = "나 오늘 10km 45분 나왔어"
    run, _ = consult(runtime_env, "fact-unrelated-resource-not-authorized", query, [
        command("create", "tasks", query, values={"title": "합성 요청하지 않은 작업"}),
        command("create", "goals", query, values={"title": "합성 요청하지 않은 목표", "category": "health"}),
    ], allow_data_recording=True)
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(Task.id)) is None
        assert session.scalar(select(Goal.id)) is None


@pytest.mark.parametrize("query", [
    "친구가 오늘 합성 운동 45분 뛰었어. 운동 기록해줘",
    "나 내일 합성 운동 45분 뛸 예정이야. 운동 기록해줘",
])
def test_explicit_write_cannot_turn_other_person_or_future_plan_into_completed_workout(runtime_env, query):
    _, database, _ = runtime_env
    run, _ = consult(runtime_env, "invalid-completed-workout", query, [command(
        "create", "workout-logs", query, values={
            "performed_on": local_today().isoformat(), "activity": "합성 운동", "duration_seconds": 2700,
        },
    )])
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.id)) is None


def test_balance_command_cannot_silently_reverse_the_user_amount_sign(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        row = Account(name="합성 부호 통장", kind="checking", currency="KRW", balance=Decimal("1000000"),
                      balance_as_of=local_today(), is_liquid=True)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "합성 부호 통장 잔액을 -500원으로 바꿔줘"
    run, _ = consult(runtime_env, "incorrect-positive-balance", query, [command(
        "update", "accounts", query, selector={"name": "합성 부호 통장"}, values={"balance": "500"},
    )])
    assert not any(operation["status"] == "saved" for operation in run["result"].get("data_operations", []))
    with database.session() as session:
        assert session.get(Account, record_id).balance == Decimal("1000000")
