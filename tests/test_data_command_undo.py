"""Undo of one saved consultation write: only unchanged records, once, with append-only history. Synthetic data."""

import json
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.database.model import Account, AuditLog, ManualValueChange, WorkoutLog
from app.modules.finance.clock import local_today
from test_advisor_crud_runtime import command, consult, package
from test_advisor_runtime_execution import runtime_env as _runtime_env  # noqa: F401
import pytest


@pytest.fixture
def runtime_env(_runtime_env):
    """The runtime fixture plus the advisor router that serves messages and undo."""
    from app.router import advisor_router
    client = _runtime_env[0]
    client.app.include_router(advisor_router.router)
    return _runtime_env


def test_undo_created_record_once_and_mark_message(runtime_env):
    client, database, _ = runtime_env
    query = "나 오늘 10km 45분 37초 뛰었어. 기록해줘"
    run, requests = consult(runtime_env, "undo-create", query, [command(
        "create", "workout-logs", query,
        values={"performed_on": local_today().isoformat(), "activity": "합성 달리기", "duration_seconds": 2737},
    )])
    [operation] = run["result"]["data_operations"]
    receipt_id = operation["receipt_id"]
    assert "previous" not in json.dumps(package(requests[-1])["data"]["advisor_data_operations"])

    response = client.post(f"/api/advisor/data-operations/{receipt_id}/undo")
    assert response.status_code == 200, response.text
    assert response.json()["operation"] == "create"
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.id)) is None
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "advisor.data_command_undo")) == 1
    assert client.post(f"/api/advisor/data-operations/{receipt_id}/undo").status_code == 409

    messages = client.get("/api/advisor/conversations/1/messages").json()
    operations = [op for m in messages for op in m["data_operations"]]
    assert [op.get("undone") for op in operations] == [True]


def test_undo_update_restores_previous_value_through_history(runtime_env):
    client, database, _ = runtime_env
    today = local_today()
    with database.session() as session:
        row = Account(name="합성 생활비 통장", kind="checking", currency="KRW", balance=Decimal("1000000.50"),
                      balance_as_of=today, is_liquid=True)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "합성 생활비 통장 잔액을 3000000원으로 수정해줘"
    run, requests = consult(runtime_env, "undo-update", query, [command(
        "update", "accounts", query, selector={"name": "합성 생활비 통장"},
        values={"balance": "3000000", "balance_as_of": today.isoformat()},
    )])
    receipt_id = run["result"]["data_operations"][0]["receipt_id"]
    # The pre-edit balance stays on the receipt; it is not part of what the model received.
    assert "1000000.50" not in json.dumps(package(requests[-1])["data"]["advisor_data_operations"])
    with database.session() as session:
        history_before = session.scalar(select(func.count()).select_from(ManualValueChange))

    assert client.post(f"/api/advisor/data-operations/{receipt_id}/undo").status_code == 200
    with database.session() as session:
        assert session.get(Account, record_id).balance == Decimal("1000000.50")
        # The undo is a new history row; earlier rows are not rewritten.
        assert session.scalar(select(func.count()).select_from(ManualValueChange)) > history_before


def test_record_changed_after_the_consultation_is_not_undone(runtime_env):
    client, database, _ = runtime_env
    query = "오늘 30분 걸었어. 기록해줘"
    run, _ = consult(runtime_env, "undo-changed", query, [command(
        "create", "workout-logs", query,
        values={"performed_on": local_today().isoformat(), "activity": "합성 걷기", "duration_seconds": 1800},
    )])
    receipt_id = run["result"]["data_operations"][0]["receipt_id"]
    with database.session() as session:
        row = session.scalar(select(WorkoutLog))
        row.duration_seconds = 1900
        session.commit()
    response = client.post(f"/api/advisor/data-operations/{receipt_id}/undo")
    assert response.status_code == 409
    with database.session() as session:
        assert session.scalar(select(WorkoutLog.duration_seconds)) == 1900


def test_only_saved_command_receipts_can_be_undone(runtime_env):
    client, database, _ = runtime_env
    with database.session() as session:
        other = AuditLog(actor="user", action="data.create", target="tasks:1", detail={})
        session.add(other)
        session.commit()
        other_id = other.id
    assert client.post(f"/api/advisor/data-operations/{other_id}/undo").status_code == 404
    assert client.post("/api/advisor/data-operations/999999/undo").status_code == 404


def test_undo_restores_long_text_in_full(runtime_env):
    from app.modules.database.model import JobApplication
    client, database, _ = runtime_env
    long_notes = "합성 메모 " * 600  # longer than the 2000-character receipt preview
    with database.session() as session:
        row = JobApplication(company="합성 회사", role="엔지니어", status="applied", notes=long_notes)
        session.add(row)
        session.commit()
        record_id = row.id
    query = "합성 회사 지원 메모를 짧게 바꿔줘"
    run, _ = consult(runtime_env, "undo-long-text", query, [command(
        "update", "job-applications", query, selector={"company": "합성 회사"}, values={"notes": "짧은 메모"},
    )])
    [operation] = run["result"]["data_operations"]
    assert operation["status"] == "saved", operation
    assert client.post(f"/api/advisor/data-operations/{operation['receipt_id']}/undo").status_code == 200
    with database.session() as session:
        assert session.get(JobApplication, record_id).notes == long_notes


def test_undo_created_application_preserves_later_interview(runtime_env):
    from datetime import UTC, datetime
    from app.modules.database.model import Interview, JobApplication

    client, database, _ = runtime_env
    query = "합성 회사 엔지니어 지원 기록을 만들어줘"
    run, _ = consult(runtime_env, "undo-linked-application", query, [command(
        "create", "job-applications", query,
        values={"company": "합성 회사", "role": "엔지니어", "status": "applied"},
    )])
    [operation] = run["result"]["data_operations"]
    assert operation["status"] == "saved", operation
    with database.session() as session:
        interview = Interview(application_id=operation["record_id"], stage="합성 면접",
                              starts_at=datetime(2026, 11, 2, 10, tzinfo=UTC))
        session.add(interview)
        session.commit()
        interview_id = interview.id

    response = client.post(f"/api/advisor/data-operations/{operation['receipt_id']}/undo")
    assert response.status_code == 409, response.text
    with database.session() as session:
        assert session.get(JobApplication, operation["record_id"]) is not None
        assert session.get(Interview, interview_id) is not None
        assert not session.get(AuditLog, operation["receipt_id"]).detail.get("undone_at")
