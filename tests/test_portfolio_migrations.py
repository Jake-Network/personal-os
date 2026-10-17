"""Exercise the managed schema path, including database-level immutability."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError


def test_fresh_migrations_match_models_and_protect_snapshot_history(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path / 'migration.db'}"
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
    assert "monthly_snapshots" not in inspect(engine).get_table_names()
    assert "holdings" in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()


@pytest.mark.parametrize('previous_revision', [None, '0004_portfolio_identity', 'head'])
def test_startup_applies_committed_revisions_and_preserves_existing_rows(tmp_path, monkeypatch, previous_revision):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.modules.database import Database
    from app.modules.database.model import Base
    import app.main as main

    url = f"sqlite:///{tmp_path / 'startup.db'}"
    config = Config('alembic.ini')
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
            assert set(inspect(database.engine).get_table_names()) == set(Base.metadata.tables) | {'alembic_version'}
            with database.engine.connect() as connection:
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '6581e3048ce0'
                if previous_revision:
                    assert connection.scalar(text("SELECT value FROM app_settings WHERE key='preserved'")) == '{}'
    finally:
        if database.engine is not None:
            database.engine.dispose()
