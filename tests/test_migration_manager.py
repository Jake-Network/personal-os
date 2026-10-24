"""Existing databases move to Alembic only on explicit request, verified, backed up, never rewritten."""
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app.modules.database import migration_manager as mm
from app.modules.database.model import Base


def url_for(tmp_path, name="legacy.db"):
    return f"sqlite:///{tmp_path / name}"


def legacy_at(tmp_path, revision: str) -> str:
    """A database whose schema is `revision` but which carries no alembic_version (create_all era)."""
    url = url_for(tmp_path)
    command.upgrade(mm.alembic_config(url), revision)
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
    engine.dispose()
    return url


def test_create_all_database_is_stamped_then_gets_checkpoints_and_triggers(tmp_path):
    url = url_for(tmp_path)
    engine = create_engine(url)
    Base.metadata.create_all(engine)  # what historical native startup produced: no triggers, no version
    with engine.begin() as c:  # create_all installations predate the calendar all_day column
        c.execute(text("ALTER TABLE calendar_events DROP COLUMN all_day"))
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(c)):
            from alembic import op
            with op.batch_alter_table("decision_journal", naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}) as batch:
                batch.drop_constraint("fk_decision_journal_source_message_id_advisor_messages", type_="foreignkey")
                batch.drop_column("source_message_id")
        # ... and the agent playbook/inbox tables and briefing schedule columns.
        for table in ("playbook_usages", "playbook_revisions", "playbooks", "inbox_items"):
            c.execute(text(f"DROP TABLE {table}"))
        for column in ("kind", "local_time", "options", "authorization", "paused_reason"):
            c.execute(text(f'ALTER TABLE job_schedules DROP COLUMN "{column}"'))
        c.execute(text("ALTER TABLE advisor_conversations DROP COLUMN origin"))
    plan = mm.plan(url)
    assert plan.action == "stamp" and plan.stamp == "0010_advisor_runtime"
    assert plan.head == "0017_merge_agent_security"
    mm.apply(url, plan)
    assert mm.plan(url).action == "none"
    assert {"checkpoints", "writes"}.issubset(inspect(engine).get_table_names())
    with engine.begin() as c:
        c.execute(text("""INSERT INTO monthly_snapshots (id, month, revision, created_at, reason, payload)
            VALUES (1, '2026-09-01', 1, '2026-10-01', 'x', '{}')"""))
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as c:
            c.execute(text("DELETE FROM monthly_snapshots"))
    engine.dispose()


def test_older_legacy_database_is_upgraded_with_data_and_backup(tmp_path):
    url = legacy_at(tmp_path, "0001_baseline")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("""INSERT INTO accounts (id, name, kind, currency, balance, balance_as_of, is_liquid,
            created_at, updated_at) VALUES (7, 'a', 'checking', 'KRW', 1234.5, '2026-09-30', 1,
            '2026-09-30', '2026-09-30')"""))
    plan = mm.plan(url)
    assert (plan.action, plan.stamp) == ("stamp", "0001_baseline")
    backup = mm.apply(url, plan)
    assert backup is not None and backup.exists()
    with engine.begin() as c:
        assert Decimal(str(c.execute(text("SELECT balance FROM accounts WHERE id=7")).scalar_one())) == Decimal("1234.5")
        assert c.execute(text("SELECT change_kind FROM manual_value_changes WHERE record_id=7")).scalar_one() == "baseline"
    assert mm.plan(url).action == "none"
    engine.dispose()


def test_unrecognised_schema_is_refused_and_left_untouched(tmp_path):
    url = legacy_at(tmp_path, "0004_portfolio_identity")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE accounts ADD COLUMN nickname VARCHAR(20)"))
    plan = mm.plan(url)
    assert plan.action == "refuse"
    assert "accounts: unexpected column nickname" in plan.describe()
    with pytest.raises(RuntimeError):
        mm.apply(url, plan)
    assert "alembic_version" not in inspect(engine).get_table_names()
    assert not list(tmp_path.glob("*.bak-*"))
    engine.dispose()


def test_versioned_and_empty_databases_upgrade(tmp_path):
    url = url_for(tmp_path, "versioned.db")
    command.upgrade(mm.alembic_config(url), "0003_google_oauth")
    assert mm.plan(url).action == "upgrade"
    empty = url_for(tmp_path, "empty.db")
    create_engine(empty).connect().close()
    plan = mm.plan(empty)
    assert plan.action == "upgrade" and plan.current is None


def test_dry_run_changes_nothing(tmp_path, capsys):
    url = legacy_at(tmp_path, "0002_portfolio")
    assert mm.main(["--database-url", url]) == 0
    assert "--apply" in capsys.readouterr().out
    assert "alembic_version" not in inspect(create_engine(url)).get_table_names()


def test_app_startup_never_migrates_an_existing_database(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main
    from app.config import Settings
    from app.modules.database import db

    url = legacy_at(tmp_path, "0004_portfolio_identity")
    before = mm.schema_of(create_engine(url))
    monkeypatch.setattr(main, "settings", Settings(data_dir=tmp_path, database_url=url))
    monkeypatch.setattr(db, "engine", None)
    with TestClient(main.app, base_url="http://127.0.0.1:8000") as c:
        assert c.get("/api/health").status_code == 200
        for path in ("/api/security/status", "/api/dashboard", "/auth/callback"):
            response = c.get(path)
            assert response.status_code == 503
            assert response.json()["code"] == "schema_upgrade_required"
    engine = create_engine(url)
    assert "alembic_version" not in inspect(engine).get_table_names()
    after = mm.schema_of(engine)
    assert {t: after[t] for t in before} == before  # existing tables exactly as they were


def test_calendar_all_day_upgrade_keeps_existing_events_timed(tmp_path):
    url = url_for(tmp_path, "calendar.db")
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
