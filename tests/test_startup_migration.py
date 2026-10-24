"""Container startup migrates disposable databases before starting the server."""

import hashlib
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError

from app.modules.database import migration_manager as mm


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def startup_engine(tmp_path, postgres_url):
    engine = create_engine(postgres_url)
    try:
        yield engine
    finally:
        engine.dispose()


def current_revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection, opts={
            "version_table_schema": connection.execute(text("SELECT current_schema()")).scalar_one(),
        }).get_current_revision()


def test_empty_database_upgrades_and_second_start_has_no_ddl(startup_engine):
    from app.modules.database.startup_migration import upgrade_database

    upgrade_database(startup_engine)
    head = ScriptDirectory.from_config(mm.alembic_config(startup_engine.url.render_as_string(hide_password=False))).get_current_head()
    assert current_revision(startup_engine) == head
    assert {"accounts", "checkpoints", "checkpoint_writes", "checkpoint_blobs"} <= set(inspect(startup_engine).get_table_names(schema=inspect(startup_engine).default_schema_name))
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(startup_engine, "before_cursor_execute", capture)
    upgrade_database(startup_engine)
    assert not any(statement.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP "))
                   for statement in statements)


def test_versioned_database_upgrades_without_losing_existing_rows(startup_engine):
    from app.modules.database.startup_migration import upgrade_database

    command.upgrade(mm.alembic_config(startup_engine.url.render_as_string(hide_password=False)), "0001_baseline")
    with startup_engine.begin() as connection:
        connection.execute(text("""INSERT INTO accounts
            (id, name, kind, currency, balance, balance_as_of, is_liquid, created_at, updated_at)
            VALUES (42, 'synthetic account', 'checking', 'KRW', 150000, '2026-10-01', true,
                    '2026-10-01', '2026-10-01')"""))
    upgrade_database(startup_engine)
    with startup_engine.connect() as connection:
        assert connection.execute(text("SELECT name, balance FROM accounts WHERE id = 42")).one() == (
            "synthetic account", 150000,
        )
        assert connection.execute(text("SELECT change_kind FROM manual_value_changes WHERE record_id = 42")).scalar_one() == "baseline"


@pytest.mark.parametrize("revision", [None, "unknown_future_revision"])
def test_unversioned_or_unknown_database_is_refused_without_mutation(startup_engine, revision):
    from app.modules.database.startup_migration import upgrade_database

    with startup_engine.begin() as connection:
        connection.execute(text("CREATE TABLE synthetic_records (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO synthetic_records VALUES ('preserve me')"))
        if revision:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
    before = set(inspect(startup_engine).get_table_names(schema=inspect(startup_engine).default_schema_name))
    with pytest.raises(RuntimeError):
        upgrade_database(startup_engine)
    assert set(inspect(startup_engine).get_table_names(schema=inspect(startup_engine).default_schema_name)) == before
    with startup_engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM synthetic_records")).scalar_one() == "preserve me"
    assert current_revision(startup_engine) == revision


def test_failed_migration_rolls_back_schema_and_data(startup_engine, monkeypatch):
    from app.modules.database import startup_migration

    command.upgrade(mm.alembic_config(startup_engine.url.render_as_string(hide_password=False)), "0001_baseline")

    def fail_after_changes(config, revision):
        connection = config.attributes["connection"]
        connection.execute(text("CREATE TABLE migration_partial_write (value TEXT)"))
        connection.execute(text("UPDATE alembic_version SET version_num = 'partial'"))
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setattr(startup_migration.command, "upgrade", fail_after_changes)
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        startup_migration.upgrade_database(startup_engine)
    assert current_revision(startup_engine) == "0001_baseline"
    assert "migration_partial_write" not in inspect(startup_engine).get_table_names(schema=inspect(startup_engine).default_schema_name)


def test_concurrent_startups_serialize_one_database_upgrade(startup_engine, monkeypatch):
    from app.modules.database import startup_migration

    barrier = threading.Barrier(2)
    calls = []
    real_upgrade = startup_migration.command.upgrade

    def tracked_upgrade(config, revision):
        calls.append(revision)
        return real_upgrade(config, revision)

    monkeypatch.setattr(startup_migration.command, "upgrade", tracked_upgrade)

    def start():
        barrier.wait(timeout=10)
        startup_migration.upgrade_database(startup_engine, timeout=20)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(start) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert calls == ["head"]
    assert current_revision(startup_engine) == ScriptDirectory.from_config(
        mm.alembic_config(startup_engine.url.render_as_string(hide_password=False)),
    ).get_current_head()


def test_startup_lock_has_bounded_wait_and_does_not_migrate(startup_engine):
    from app.modules.database.startup_migration import upgrade_database

    with startup_engine.connect() as lock_holder:
        identity = lock_holder.exec_driver_sql("SELECT current_database(), current_schema()").one()
        key = int.from_bytes(hashlib.sha256(repr(tuple(identity)).encode()).digest()[:8], "big", signed=True)
        lock_holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        try:
            started = time.monotonic()
            with pytest.raises(OperationalError, match="lock timeout"):
                upgrade_database(startup_engine, timeout=0.05)
            assert time.monotonic() - started < 1
        finally:
            lock_holder.rollback()
    assert inspect(startup_engine).get_table_names(schema=inspect(startup_engine).default_schema_name) == []


def test_cli_can_skip_migration_without_connecting(monkeypatch):
    from app.modules.database import startup_migration

    monkeypatch.setenv("PERSONAL_OS_AUTO_MIGRATE", "0")

    def forbidden(*args, **kwargs):
        raise AssertionError("migration disabled: no database connection is allowed")

    monkeypatch.setattr(startup_migration, "upgrade_database", forbidden)
    assert startup_migration.main() == 0


def test_cli_failure_returns_nonzero_and_omits_sensitive_exception(tmp_path, monkeypatch, caplog):
    from app import config
    from app.modules.database import startup_migration

    disposed = []

    class SyntheticEngine:
        def dispose(self):
            disposed.append(True)

    def fail(_engine, timeout):
        raise RuntimeError("synthetic-private-credential-and-sql-content")

    monkeypatch.setenv("PERSONAL_OS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("PERSONAL_OS_PRODUCTION", "false")
    monkeypatch.setattr(config, "settings", config.Settings(data_dir=tmp_path, database_url="postgresql+psycopg://synthetic@127.0.0.1/test"))
    monkeypatch.setattr(startup_migration, "create_engine", lambda *args, **kwargs: SyntheticEngine())
    monkeypatch.setattr(startup_migration, "upgrade_database", fail)
    assert startup_migration.main() == 1
    assert disposed == [True]
    assert "server will not start" in caplog.text
    assert "synthetic-private-credential-and-sql-content" not in caplog.text


@pytest.mark.parametrize("migration_exit", [0, 7])
def test_entrypoint_migrates_before_command_and_stops_on_failure(tmp_path, migration_exit):
    fake_python = tmp_path / "python"
    fake_python.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$MIGRATION_ARGUMENTS"\nexit "$MIGRATION_EXIT"\n',
    )
    fake_python.chmod(0o755)
    args_file = tmp_path / "migration-arguments"
    command_file = tmp_path / "command-arguments"
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "MIGRATION_ARGUMENTS": str(args_file),
        "MIGRATION_EXIT": str(migration_exit),
    }
    result = subprocess.run(
        ["sh", str(ROOT / "docker/entrypoint.sh"), "sh", "-c",
         'printf "%s\\n" "$@" > "$0"', str(command_file), "two words", "literal;$value"],
        env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == migration_exit
    assert args_file.read_text().splitlines() == ["-m", "app.modules.database.startup_migration"]
    if migration_exit:
        assert not command_file.exists()
    else:
        assert command_file.read_text().splitlines() == ["two words", "literal;$value"]
