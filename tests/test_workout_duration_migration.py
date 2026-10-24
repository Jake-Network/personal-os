import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.modules.database.migration_manager import alembic_config


@pytest.fixture
def workout_postgres_url():
    configured = os.environ.get("TEST_DATABASE_URL", "")
    if not configured or make_url(configured).get_backend_name() != "postgresql":
        pytest.skip("Requires a disposable PostgreSQL TEST_DATABASE_URL")
    schema = "workout_test_" + uuid4().hex
    admin = create_engine(configured)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield make_url(configured).update_query_dict({
            "options": f"-csearch_path={schema},public",
        }).render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_workout_upgrade_preserves_existing_durations(workout_postgres_url):
    config = alembic_config(workout_postgres_url)
    command.upgrade(config, "0016_checkpoint_task_path")
    engine = create_engine(workout_postgres_url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO workout_logs (performed_on, activity, duration_minutes, created_at, updated_at) "
            "VALUES ('2026-10-24', '합성 러닝', 45, '2026-10-24', '2026-10-24'), "
            "('2026-10-24', '합성 긴 기록', 2147483647, '2026-10-24', '2026-10-24')"
        ))
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT duration_seconds FROM workout_logs ORDER BY id")).scalars().all() == [2700, 128849018820]
        assert connection.execute(text("SELECT activity FROM workout_logs ORDER BY id")).scalars().all() == ["합성 러닝", "합성 긴 기록"]
        assert "duration_minutes" not in {column["name"] for column in inspect(connection).get_columns("workout_logs")}
    command.downgrade(config, "0016_checkpoint_task_path")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT duration_minutes FROM workout_logs ORDER BY id")).scalars().all() == [45, 2147483647]
    engine.dispose()


def test_workout_downgrade_refuses_second_precision_loss(workout_postgres_url):
    config = alembic_config(workout_postgres_url)
    command.upgrade(config, "head")
    engine = create_engine(workout_postgres_url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO workout_logs (performed_on, activity, duration_seconds, created_at, updated_at) "
            "VALUES ('2026-10-24', '합성 인터벌', 59, '2026-10-24', '2026-10-24')"
        ))
    with pytest.raises(RuntimeError, match="without losing seconds"):
        command.downgrade(config, "0016_checkpoint_task_path")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT duration_seconds FROM workout_logs")).scalar_one() == 59
    engine.dispose()
