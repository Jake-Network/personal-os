from datetime import UTC, date, datetime

from app.enums.context_category import Category
from app.modules.context.context_tool_manager import get_health_summary
from app.modules.context.types import ToolContext
from app.modules.database.model import WorkoutLog


def test_workout_seconds_round_trip_and_update(client, session):
    body = {"performed_on": "2026-10-24", "activity": "합성 러닝", "duration_seconds": 2731}
    created = client.post("/api/data/workout-logs", json=body)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["duration_seconds"] == 2731
    assert session.get(WorkoutLog, record["id"]).duration_seconds == 2731
    updated = client.put(f"/api/data/workout-logs/{record['id']}", json={**body, "duration_seconds": 59})
    assert updated.status_code == 200, updated.text
    assert updated.json()["duration_seconds"] == 59
    assert client.get("/api/data/workout-logs").json()[0]["duration_seconds"] == 59


def test_workout_legacy_minutes_are_converted_and_conflicts_rejected(client):
    body = {"performed_on": "2026-10-24", "activity": "합성 걷기", "duration_minutes": 45}
    created = client.post("/api/data/workout-logs", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["duration_seconds"] == 2700
    for invalid in ({"duration_seconds": 0}, {"duration_seconds": -1}, {"duration_seconds": 1.5},
                    {"duration_seconds": True}, {"duration_seconds": 2731, "duration_minutes": 45},
                    {"duration_minutes": 1.5}, {"duration_minutes": True}):
        invalid_body = {key: value for key, value in body.items() if key != "duration_minutes"}
        assert client.post("/api/data/workout-logs", json={**invalid_body, **invalid}).status_code == 422


def test_health_summary_preserves_subminute_duration(session):
    session.add(WorkoutLog(performed_on=date(2026, 10, 24), activity="합성 인터벌", duration_seconds=59))
    session.flush()
    summary = get_health_summary(ToolContext(session, datetime(2026, 10, 24, tzinfo=UTC), frozenset({Category.HEALTH})))
    assert summary.data["total_seconds"] == 59
    assert summary.data["recent"][0]["seconds"] == 59
    assert 0 < summary.data["total_minutes"] < 1
