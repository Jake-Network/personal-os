"""Exercise the managed schema path, including database-level immutability."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError


def test_fresh_migrations_match_models_and_protect_snapshot_history(tmp_path, postgres_url):
    config = Config("alembic.ini")
    url = postgres_url
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO monthly_snapshots
            (id, month, revision, created_at, reason, payload)
            VALUES (1, '2026-09-01', 1, '2026-10-01', 'Initial', '{}')"""))
    for statement in ("UPDATE monthly_snapshots SET reason='rewrite' WHERE id=1",
                      "DELETE FROM monthly_snapshots WHERE id=1"):
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(text(statement))
    command.downgrade(config, "0001_baseline")
    assert "monthly_snapshots" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    assert "holdings" in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()


@pytest.mark.parametrize('previous_revision', [None, '0004_portfolio_identity', 'head'])
def test_startup_builds_empty_databases_and_preserves_existing_ones(tmp_path, monkeypatch, previous_revision, postgres_url):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.modules.database import Database
    from app.modules.database.model import Base
    import app.main as main

    url = postgres_url
    config = Config('alembic.ini')
    from alembic.script import ScriptDirectory
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    config.attributes['database_url'] = url
    if previous_revision:
        command.upgrade(config, previous_revision)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO app_settings (key, value, updated_at) VALUES ('preserved', '{}', '2026-10-18')"))
        engine.dispose()
    database = Database()
    monkeypatch.setattr(main, 'db', database)
    monkeypatch.setattr(main, 'settings', replace(main.settings, database_url=url, data_dir=tmp_path))
    monkeypatch.chdir(tmp_path)
    try:
        with TestClient(main.app):
            tables = set(inspect(database.engine).get_table_names(schema=inspect(database.engine).default_schema_name))
            with database.engine.connect() as connection:
                version = connection.scalar(text('SELECT version_num FROM alembic_version'))
            if previous_revision == '0004_portfolio_identity':  # existing databases are never migrated at startup
                assert version == previous_revision and 'documents' not in tables
            else:
                assert tables == set(Base.metadata.tables) | {'alembic_version', 'checkpoint_migrations', 'checkpoints', 'checkpoint_writes', 'checkpoint_blobs'}
                assert version == expected_head
            with database.engine.connect() as connection:
                if previous_revision:
                    assert connection.scalar(text("SELECT value FROM app_settings WHERE key='preserved'")) == {}
    finally:
        if database.engine is not None:
            database.engine.dispose()


def test_revision_ids_fit_the_alembic_version_column():
    # alembic_version.version_num is VARCHAR(32), enforced by PostgreSQL.
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert [r.revision for r in script.walk_revisions() if len(r.revision) > 32] == []
