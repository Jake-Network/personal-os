"""Legacy adoption must prove a frozen baseline before writing migration history."""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app.modules.database.database import Database
from app.modules.database.legacy_adoption import (
    SUPPORTED_REVISIONS, adopt_legacy, migration_config,
)


@pytest.fixture(autouse=True)
def synthetic_backup(monkeypatch, tmp_path):
    # These tests exercise schema changes, not an installed PostgreSQL CLI.
    from app.modules.database import migration_backup
    monkeypatch.setattr(migration_backup, 'create_migration_backup',
        lambda *a, **k: migration_backup.MigrationBackup(tmp_path / 'archive.fernet', tmp_path / 'backup.key'))


def legacy_database(postgres_url, revision="0004_portfolio_identity"):
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), revision)
        connection.exec_driver_sql("DROP TABLE alembic_version")
        # create_all installations have no migration-only triggers.
        if revision != "0001_baseline":
            connection.exec_driver_sql("DROP TRIGGER monthly_snapshots_immutable ON monthly_snapshots")
            connection.exec_driver_sql("DROP FUNCTION reject_monthly_snapshot_mutation()")
        connection.exec_driver_sql("INSERT INTO app_settings VALUES ('preserved', '{}', '2026-10-18')")
        if revision != "0001_baseline":
            connection.exec_driver_sql("INSERT INTO monthly_snapshots (month, revision, created_at, reason, payload) VALUES ('2026-09-01', 1, '2026-10-18', 'legacy', '{\"preserved\": 123}')")
    return engine


@pytest.mark.parametrize("revision", SUPPORTED_REVISIONS)
def test_legacy_adoption_validates_preserves_rows_and_upgrades(postgres_url, revision):
    engine = legacy_database(postgres_url, revision)
    assert adopt_legacy(engine) == revision
    assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    assert adopt_legacy(engine, apply=True) == revision
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM app_settings WHERE key='preserved'")) == {}
        assert connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0001_baseline":
            assert connection.scalar(text("SELECT payload FROM monthly_snapshots WHERE reason='legacy'")) == {"preserved": 123}
        command.check(migration_config(connection))
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO monthly_snapshots (month, revision, created_at, reason, payload) VALUES ('2026-10-01', 1, '2026-10-18', 'initial', '{}')")
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM monthly_snapshots")
    engine.dispose()


@pytest.mark.parametrize("drift", [
    "ALTER TABLE accounts ADD COLUMN unexpected TEXT",
    "DROP INDEX ix_monthly_snapshots_month",
    "CREATE TABLE unexpected (id INTEGER PRIMARY KEY)",
    "DROP TABLE workout_logs",
])
def test_drift_is_rejected_without_stamping(postgres_url, drift):
    engine = legacy_database(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(drift)
    with pytest.raises(RuntimeError, match="does not exactly match"):
        adopt_legacy(engine, apply=True)
    assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    engine.dispose()


def test_startup_leaves_legacy_untouched_until_explicit_adoption(postgres_url):
    engine = legacy_database(postgres_url)
    database = Database()
    database.init(engine.url.render_as_string(hide_password=False))
    before = inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    database.migrate_schema()
    assert inspect(engine).get_table_names(schema=inspect(engine).default_schema_name) == before
    database.engine.dispose()
    adopt_legacy(engine, apply=True)
    database.init(engine.url.render_as_string(hide_password=False))
    database.migrate_schema()
    database.engine.dispose()
    engine.dispose()


def test_versioned_database_cannot_be_adopted(postgres_url):
    engine = legacy_database(postgres_url)
    adopt_legacy(engine, apply=True)
    with pytest.raises(RuntimeError, match="already versioned"):
        adopt_legacy(engine, apply=True)
    engine.dispose()


def test_failed_upgrade_rolls_back_adoption(postgres_url, monkeypatch):
    engine = legacy_database(postgres_url)
    original = command.upgrade
    def fail_head(config, revision):
        if revision == "head":
            config.attributes["connection"].exec_driver_sql("CREATE TABLE partial_upgrade (id INTEGER)")
            raise RuntimeError("upgrade failed")
        return original(config, revision)
    monkeypatch.setattr(command, "upgrade", fail_head)
    with pytest.raises(RuntimeError, match="upgrade failed"):
        adopt_legacy(engine, apply=True)
    assert "alembic_version" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    assert "partial_upgrade" not in inspect(engine).get_table_names(schema=inspect(engine).default_schema_name)
    engine.dispose()


def test_postgresql_legacy_adoption_preserves_data_and_constraints():
    import os
    from uuid import uuid4
    from sqlalchemy.engine import make_url
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL must point to disposable PostgreSQL")
    admin = create_engine(url)
    schema = "legacy_test_" + uuid4().hex
    managed_schema = "managed_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'CREATE SCHEMA "{managed_schema}"')
    managed = create_engine(make_url(url), connect_args={"options": f"-csearch_path={managed_schema},public"})
    with managed.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        managed_version = connection.scalar(text(f'SELECT version_num FROM "{managed_schema}".alembic_version'))
        connection.exec_driver_sql("INSERT INTO app_settings VALUES ('outer-preserved', '{}', now())")
        managed_tables = inspect(connection).get_table_names(schema=managed_schema)
    engine = create_engine(make_url(url), connect_args={"options": f"-csearch_path={schema},{managed_schema},public"})
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0004_portfolio_identity")
            connection.exec_driver_sql(f'DROP TABLE "{schema}".alembic_version')
            connection.exec_driver_sql("DROP TRIGGER monthly_snapshots_immutable ON monthly_snapshots")
            connection.exec_driver_sql("DROP FUNCTION reject_monthly_snapshot_mutation()")
            connection.exec_driver_sql("INSERT INTO app_settings VALUES ('preserved', '{}', now())")
            connection.exec_driver_sql("INSERT INTO monthly_snapshots (month, revision, created_at, reason, payload) VALUES ('2026-09-01', 1, now(), 'legacy', '{\"preserved\": 123}')")
        # A visible managed schema must neither supply migration history nor
        # make a foreign sequence default look equivalent to a local one.
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER TABLE accounts ALTER COLUMN id SET DEFAULT nextval('{managed_schema}.accounts_id_seq'::regclass)")
        with pytest.raises(RuntimeError, match="does not exactly match"):
            adopt_legacy(engine, apply=True)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER TABLE accounts ALTER COLUMN id SET DEFAULT nextval('{schema}.accounts_id_seq'::regclass)")
        assert adopt_legacy(engine) == "0004_portfolio_identity"
        assert adopt_legacy(engine, apply=True) == "0004_portfolio_identity"
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT value FROM app_settings WHERE key='preserved'")) == {}
            assert connection.scalar(text("SELECT payload FROM monthly_snapshots WHERE reason='legacy'")) == {"preserved": 123}
            connection.exec_driver_sql("INSERT INTO monthly_snapshots (month, revision, created_at, reason, payload) VALUES ('2026-10-01', 1, now(), 'initial', '{}')")
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.exec_driver_sql("DELETE FROM monthly_snapshots")
        with managed.connect() as connection:
            assert connection.scalar(text(f'SELECT version_num FROM "{managed_schema}".alembic_version')) == managed_version
            assert inspect(connection).get_table_names(schema=managed_schema) == managed_tables
            assert connection.scalar(text("SELECT value FROM app_settings WHERE key='outer-preserved'")) == {}
    finally:
        engine.dispose()
        managed.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            connection.exec_driver_sql(f'DROP SCHEMA "{managed_schema}" CASCADE')
        admin.dispose()


def test_unknown_version_is_not_overwritten(postgres_url):
    engine = legacy_database(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('unknown_baseline')")
    with pytest.raises(RuntimeError, match="already versioned"):
        adopt_legacy(engine, apply=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == 'unknown_baseline'
    engine.dispose()


def test_empty_version_table_is_treated_as_unversioned(postgres_url):
    engine = legacy_database(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    database = Database()
    database.init(engine.url.render_as_string(hide_password=False))
    database.migrate_schema()
    database.engine.dispose()
    assert adopt_legacy(engine) == '0004_portfolio_identity'
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    engine.dispose()
