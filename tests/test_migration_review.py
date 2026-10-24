"""Migration review regressions use only disposable databases and synthetic data."""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.modules.database import migration_manager as mm
from app.modules.database.types import MigrationPlan


def test_apply_requires_a_backup_before_any_migration(monkeypatch, postgres_url):
    import shutil
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    touched = []
    monkeypatch.setattr(mm.command, 'stamp', lambda *a, **k: touched.append('stamp'))
    monkeypatch.setattr(mm.command, 'upgrade', lambda *a, **k: touched.append('upgrade'))
    with pytest.raises(RuntimeError, match='pg_dump'):
        mm.apply(postgres_url, MigrationPlan(current='0001_baseline', head='0018_merge_advisor_records'))
    assert touched == []


def test_reference_schema_cannot_resolve_operational_tables(postgres_url):
    from app.modules.database.legacy_adoption import reference_connection
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        # public objects are deliberately visible to the ordinary application.
        # Use a name outside the real application's schema to avoid collisions.
        connection.exec_driver_sql('CREATE TABLE public.migration_review_sentinel (id integer)')
        try:
            with reference_connection(connection) as scratch:
                assert scratch.exec_driver_sql("SELECT to_regclass('migration_review_sentinel')").scalar_one() is None
        finally:
            connection.exec_driver_sql('DROP TABLE public.migration_review_sentinel')
    engine.dispose()


def test_backup_encrypts_dump_uses_private_files_and_preserves_connection_options(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from app.modules.database import migration_backup as backup
    from subprocess import CompletedProcess
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    seen = []
    def dump(argv, **kwargs):
        seen.append((argv, kwargs))
        return CompletedProcess(argv, 0, b'PGDMPsynthetic-backup', b'')
    monkeypatch.setattr(backup.subprocess, 'run', dump)
    monkeypatch.setenv('PGDATABASE', 'wrong-database')
    artifact = backup.create_migration_backup(
        'postgresql+psycopg://operator:synthetic-secret@db.example:5439/personal?sslmode=verify-full&options=-csearch_path%3Dapp%2Cextensions',
        backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
    argv, kwargs = seen[0]
    assert all('synthetic-secret' not in part for part in argv)
    assert kwargs['env']['PGDATABASE'] == 'personal'
    assert kwargs['env']['PGHOST'] == 'db.example'
    assert kwargs['env']['PGPORT'] == '5439'
    assert kwargs['env']['PGSSLMODE'] == 'verify-full'
    assert kwargs['env']['PGOPTIONS'] == '-csearch_path=app,extensions'
    assert kwargs['env']['PGPASSWORD'] == 'synthetic-secret'
    assert artifact.archive.stat().st_mode & 0o777 == 0o600
    assert artifact.key_file.stat().st_mode & 0o777 == 0o600
    assert artifact.key_file.parent != artifact.archive.parent
    assert b'PGDMP' not in artifact.archive.read_bytes()
    assert Fernet(artifact.key_file.read_bytes()).decrypt(artifact.archive.read_bytes()) == b'PGDMPsynthetic-backup'


@pytest.mark.parametrize('dump_result', [(1, b'PGDMPpartial'), (0, b'not-a-dump')])
def test_failed_dump_leaves_no_accepted_backup(monkeypatch, tmp_path, dump_result):
    from subprocess import CompletedProcess
    from app.modules.database import migration_backup as backup
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    monkeypatch.setattr(backup.subprocess, 'run', lambda argv, **k: CompletedProcess(argv, dump_result[0], dump_result[1], b'withheld'))
    with pytest.raises(RuntimeError, match='backup failed'):
        backup.create_migration_backup('postgresql+psycopg://operator:secret@localhost/db',
            backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
    assert list((tmp_path / 'archives').iterdir()) == []
    assert list((tmp_path / 'keys').iterdir()) == []


def test_backup_write_failure_removes_partial_archive_and_key(monkeypatch, tmp_path):
    from subprocess import CompletedProcess
    from app.modules.database import migration_backup as backup
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    monkeypatch.setattr(backup.subprocess, 'run', lambda argv, **k: CompletedProcess(argv, 0, b'PGDMPsynthetic', b''))
    original = backup.os.fsync
    calls = []
    def partial(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError('synthetic full disk')
        original(fd)
    monkeypatch.setattr(backup.os, 'fsync', partial)
    with pytest.raises(RuntimeError, match='storage/verification'):
        backup.create_migration_backup('postgresql+psycopg://operator:secret@localhost/db',
            backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
    assert list((tmp_path / 'archives').iterdir()) == []
    assert list((tmp_path / 'keys').iterdir()) == []


def test_legacy_adoption_requires_backup_before_stamp(monkeypatch, postgres_url):
    import shutil
    from alembic import command
    from app.modules.database.legacy_adoption import adopt_legacy
    command.upgrade(mm.alembic_config(postgres_url), '0001_baseline')
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE alembic_version')
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='pg_dump'):
        adopt_legacy(engine, apply=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT to_regclass('alembic_version')").scalar_one() is None
    engine.dispose()


@pytest.fixture
def isolated_extension_database():
    from sqlalchemy.engine import make_url
    from uuid import uuid4
    configured = make_url(os.environ['TEST_DATABASE_URL'])
    name = 'migration_review_' + uuid4().hex
    admin = create_engine(configured.update_query_dict({'options': '-csearch_path=public'}), isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    target = configured.set(database=name).update_query_dict({'options': '-csearch_path=app,extensions'})
    try:
        yield target.render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def test_reference_schema_preserves_custom_vector_visibility_without_live_table_fallback(isolated_extension_database):
    from alembic import command
    from app.modules.database.legacy_adoption import migration_config, reference_connection
    engine = create_engine(isolated_extension_database)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE SCHEMA app')
        connection.exec_driver_sql('CREATE SCHEMA extensions')
        connection.exec_driver_sql('CREATE EXTENSION vector WITH SCHEMA extensions')
        connection.exec_driver_sql('CREATE TABLE app.accounts (id integer primary key)')
        connection.exec_driver_sql('INSERT INTO app.accounts VALUES (7)')
        original = connection.exec_driver_sql('SHOW search_path').scalar_one()
        with reference_connection(connection) as scratch:
            assert scratch.exec_driver_sql("SELECT to_regclass('accounts')").scalar_one() is None
            command.upgrade(migration_config(scratch), '6581e3048ce0')
            # The new vector column uses the real extension's type, not a copied
            # domain or a type guessed from the public schema.
            namespace = scratch.exec_driver_sql("SELECT n.nspname FROM pg_attribute a "
                "JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE a.attrelid='document_chunks'::regclass AND a.attname='embedding'").scalar_one()
            assert namespace == 'extensions'
            target = scratch.exec_driver_sql("SELECT n.nspname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid=c.confrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                "WHERE c.conrelid='holdings'::regclass AND c.contype='f'").scalar_one()
            assert target.startswith('legacy_check_')
        assert connection.exec_driver_sql('SHOW search_path').scalar_one() == original
        assert connection.exec_driver_sql('SELECT id FROM app.accounts').scalar_one() == 7
        assert connection.exec_driver_sql("SELECT to_regclass('app.document_chunks')").scalar_one() is None
    engine.dispose()


def test_plan_uses_one_engine_and_executes_baseline_ddl_once(postgres_url, monkeypatch):
    from alembic import command
    from sqlalchemy import event
    import re
    command.upgrade(mm.alembic_config(postgres_url), '0004_portfolio_identity')
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE alembic_version')
        connection.exec_driver_sql('ALTER TABLE accounts ADD COLUMN unknown_review_column integer')
    engine.dispose()
    engines, account_creates = [], []
    original = mm.create_engine
    def instrumented(*args, **kwargs):
        created = original(*args, **kwargs)
        engines.append(created)
        @event.listens_for(created, 'before_cursor_execute')
        def count(_conn, _cursor, statement, _parameters, _context, _executemany):
            if re.search(r'^\s*CREATE TABLE accounts\s*\(', statement):
                account_creates.append(statement)
        return created
    monkeypatch.setattr(mm, 'create_engine', instrumented)
    result = mm.plan(postgres_url)
    assert result.action == 'refuse'
    assert len(engines) == 1
    assert len(account_creates) == 1


@pytest.mark.parametrize('revision,expected', [
    ('0016_checkpoint_task_path', '0016_checkpoint_task_path'),
    ('0016_agent_playbooks_inbox', '0017_merge_agent_security'),
    ('0017_workout_duration_seconds', '0017_workout_duration_seconds'),
])
def test_linear_plan_retains_each_independent_branch_shape(postgres_url, revision, expected):
    from alembic import command
    command.upgrade(mm.alembic_config(postgres_url), revision)
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE alembic_version')
    engine.dispose()
    assert mm.plan(postgres_url).stamp == expected


def test_backup_refuses_options_without_a_libpq_environment_transport(monkeypatch, tmp_path):
    from app.modules.database import migration_backup as backup
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Unsupported connection option must fail before pg_dump')
    monkeypatch.setattr(backup.subprocess, 'run', forbidden)
    with pytest.raises(RuntimeError, match='connection option: keepalives'):
        backup.create_migration_backup('postgresql+psycopg://operator:secret@localhost/db?keepalives=1',
            backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')


def test_backup_syncs_key_and_archive_directories_before_acceptance(monkeypatch, tmp_path):
    from subprocess import CompletedProcess
    from app.modules.database import migration_backup as backup
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    monkeypatch.setattr(backup.subprocess, 'run', lambda argv, **k: CompletedProcess(argv, 0, b'PGDMPsynthetic', b''))
    events = []
    original = backup._write_private
    def write(path, content):
        original(path, content)
        events.append(('written', path.parent.name))
    monkeypatch.setattr(backup, '_write_private', write)
    monkeypatch.setattr(backup, '_sync_directory', lambda path: events.append(('directory-synced', path.name)))
    artifact = backup.create_migration_backup('postgresql+psycopg://operator:secret@localhost/db',
        backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
    assert events == [('written', 'keys'), ('written', 'archives'),
                      ('directory-synced', 'keys'), ('directory-synced', 'archives')]
    assert artifact.archive.exists() and artifact.key_file.exists()


@pytest.mark.parametrize('service_source', ['inherited', 'explicit'])
def test_backup_rejects_service_settings_before_dump(monkeypatch, tmp_path, service_source):
    from app.modules.database import migration_backup as backup
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/synthetic/pg_dump')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('A service must not override the URL-selected database during backup')
    monkeypatch.setattr(backup.subprocess, 'run', forbidden)
    url = 'postgresql+psycopg://operator:secret@localhost/requested_database'
    if service_source == 'inherited':
        monkeypatch.setenv('PGSERVICE', 'conflicting-service')
        monkeypatch.setenv('PGSERVICEFILE', str(tmp_path / 'conflicting-service.conf'))
    else:
        monkeypatch.delenv('PGSERVICE', raising=False)
        url += '?service=conflicting-service'
    with pytest.raises(RuntimeError, match='service configuration'):
        backup.create_migration_backup(url, backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
    assert not list((tmp_path / 'archives').iterdir())
    assert not list((tmp_path / 'keys').iterdir())
