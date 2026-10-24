"""Explicit database adoption preserves existing rows and refuses unknown schemas."""
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app.modules.database import migration_manager as mm


def url_for(postgres_database):
    return postgres_database()


def legacy_at(postgres_database, revision: str) -> str:
    """A database whose schema is `revision` but which carries no alembic_version (create_all era)."""
    url = url_for(postgres_database)
    command.upgrade(mm.alembic_config(url), revision)
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
    engine.dispose()
    return url


def test_create_all_database_is_stamped_then_gets_checkpoints_and_triggers(postgres_database):
    # Build the historical ORM-era table shape independently of today's model additions.
    url = legacy_at(postgres_database, "0010_advisor_runtime")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER monthly_snapshots_immutable ON monthly_snapshots"))
        connection.execute(text("DROP TRIGGER manual_value_changes_immutable ON manual_value_changes"))
    plan = mm.plan(url)
    assert plan.action == "stamp" and plan.stamp == "0010_advisor_runtime"
    assert plan.head == "0017_merge_agent_security"
    mm.apply(url, plan)
    assert mm.plan(url).action == "none"
    assert {"checkpoints", "checkpoint_writes", "checkpoint_blobs"}.issubset(inspect(engine).get_table_names(schema=inspect(engine).default_schema_name))
    with engine.begin() as c:
        c.execute(text("""INSERT INTO monthly_snapshots (id, month, revision, created_at, reason, payload)
            VALUES (1, '2026-09-01', 1, '2026-10-01', 'x', '{}')"""))
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as c:
            c.execute(text("DELETE FROM monthly_snapshots"))
    engine.dispose()


def test_older_legacy_database_is_upgraded_with_data(postgres_database):
    url = legacy_at(postgres_database, "0001_baseline")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("""INSERT INTO accounts (id, name, kind, currency, balance, balance_as_of, is_liquid,
            created_at, updated_at) VALUES (7, 'a', 'checking', 'KRW', 1234.5, '2026-09-30', true,
            '2026-09-30', '2026-09-30')"""))
    plan = mm.plan(url)
    assert (plan.action, plan.stamp) == ("stamp", "0001_baseline")
    backup = mm.apply(url, plan)
    assert backup is None
    with engine.begin() as c:
        assert Decimal(str(c.execute(text("SELECT balance FROM accounts WHERE id=7")).scalar_one())) == Decimal("1234.5")
        assert c.execute(text("SELECT change_kind FROM manual_value_changes WHERE record_id=7")).scalar_one() == "baseline"
    assert mm.plan(url).action == "none"
    engine.dispose()


def test_unrecognised_schema_is_refused_and_left_untouched(postgres_database):
    url = legacy_at(postgres_database, "0004_portfolio_identity")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE accounts ADD COLUMN nickname VARCHAR(20)"))
    plan = mm.plan(url)
    assert plan.action == "refuse"
    assert "accounts: unexpected column nickname" in plan.describe()
    with pytest.raises(RuntimeError):
        mm.apply(url, plan)
    assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    engine.dispose()


def test_versioned_and_empty_databases_upgrade(postgres_database):
    url = url_for(postgres_database)
    command.upgrade(mm.alembic_config(url), "0003_google_oauth")
    assert mm.plan(url).action == "upgrade"
    empty = url_for(postgres_database)
    create_engine(empty).connect().close()
    plan = mm.plan(empty)
    assert plan.action == "upgrade" and plan.current is None


def test_dry_run_changes_nothing(postgres_database, capsys):
    url = legacy_at(postgres_database, "0002_portfolio")
    assert mm.main(["--database-url", url]) == 0
    assert "--apply" in capsys.readouterr().out
    engine = create_engine(url)
    try:
        assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    finally:
        engine.dispose()


def test_app_startup_never_migrates_an_existing_database(postgres_database, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main
    from app.config import Settings
    from app.modules.database import db

    url = legacy_at(postgres_database, "0004_portfolio_identity")
    before = mm.schema_of(create_engine(url))
    monkeypatch.setattr(main, "settings", Settings(database_url=url))
    monkeypatch.setattr(db, "engine", None)
    with TestClient(main.app, base_url="http://127.0.0.1:8000") as c:
        assert c.get("/api/health").status_code == 200
        for path in ("/api/security/status", "/api/dashboard", "/auth/callback"):
            response = c.get(path)
            assert response.status_code == 503
            assert response.json()["code"] == "schema_upgrade_required"
    engine = create_engine(url)
    assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    after = mm.schema_of(engine)
    assert {t: after[t] for t in before} == before  # existing tables exactly as they were


def test_calendar_all_day_upgrade_keeps_existing_events_timed(postgres_database):
    url = url_for(postgres_database)
    command.upgrade(mm.alembic_config(url), "0013_goal_values_as_text")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("""INSERT INTO calendar_events (id, title, kind, starts_at, created_at, updated_at)
            VALUES (3, '면접', 'interview', '2026-10-20 01:00:00', '2026-10-01', '2026-10-01')"""))
    command.upgrade(mm.alembic_config(url), "head")
    with engine.begin() as c:
        row = c.execute(text("SELECT title, starts_at, all_day FROM calendar_events WHERE id=3")).one()
    assert (row.title, row.all_day) == ("면접", 0)
    assert str(row.starts_at).startswith("2026-10-20 01:00:00")
    engine.dispose()


def test_plan_ignores_visible_foreign_schema_history_and_preserves_its_rows(postgres_database):
    from sqlalchemy.engine import make_url

    parent_url = postgres_database()
    command.upgrade(mm.alembic_config(parent_url), "head")
    parent = create_engine(parent_url)
    with parent.begin() as connection:
        parent_schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        connection.execute(text("INSERT INTO app_settings VALUES ('foreign-sentinel', '{}', now())"))
        parent_version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    child_url = legacy_at(postgres_database, "0001_baseline")
    child = create_engine(child_url)
    with child.connect() as connection:
        child_schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    child.dispose()
    visible = make_url(child_url).update_query_dict({
        "options": f"-csearch_path={child_schema},{parent_schema},public",
    }).render_as_string(hide_password=False)
    try:
        result = mm.plan(visible)
        assert (result.action, result.stamp, result.current) == ("stamp", "0001_baseline", None)
        with parent.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == parent_version
            assert connection.execute(text("SELECT value FROM app_settings WHERE key='foreign-sentinel'")).scalar_one() == {}
    finally:
        parent.dispose()
