"""Opt-in real pg_dump/restore using the disposable PostgreSQL service's own client."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.modules.database.migration_backup import create_migration_backup


@pytest.fixture
def backup_databases():
    configured = os.environ.get('TEST_DATABASE_URL', '')
    container = os.environ.get('TEST_PG_DUMP_CONTAINER', '')
    if not container or not shutil.which('docker'):
        pytest.skip('Set TEST_PG_DUMP_CONTAINER to the disposable local PostgreSQL service')
    url = make_url(configured)
    assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1'}
    names = ['backup_source_' + uuid4().hex, 'backup_restored_' + uuid4().hex]
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    created = []
    try:
        with admin.connect() as connection:
            for name in names:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
                created.append(name)
        yield container, url.set(database=names[0]), url.set(database=names[1])
    finally:
        with admin.connect() as connection:
            for name in reversed(created):
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def test_native_backup_is_recoverable_with_real_pg_dump_and_pg_restore(backup_databases, tmp_path, monkeypatch):
    container, source_url, restored_url = backup_databases
    source, restored = create_engine(source_url), create_engine(restored_url)
    try:
        with source.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE recovery_marker(id integer primary key, note text)')
            connection.exec_driver_sql("INSERT INTO recovery_marker VALUES (1,'synthetic-preserved')")
        # Only adapt the network transport to the matching client inside the
        # test service. In particular PGDATABASE is forwarded unchanged, so a
        # conninfo string incorrectly used as the DB name fails the real client.
        client = tmp_path / 'client.py'
        client.write_text('''import os, subprocess, sys
values = dict(os.environ)
values.update(PGHOST='127.0.0.1', PGPORT='5432')
args = ['docker', 'exec', '-i']
for name in sorted(values):
    if name.startswith('PG'):
        args += ['-e', name]
args += [values['TEST_PG_DUMP_CONTAINER'], 'pg_dump', *sys.argv[1:]]
raise SystemExit(subprocess.run(args, env=values).returncode)
''')
        executable = tmp_path / 'pg_dump'
        executable.write_text('#!/bin/sh\nexec "$TEST_BACKUP_PYTHON" "$TEST_BACKUP_CLIENT" "$@"\n')
        executable.chmod(0o700)
        monkeypatch.setenv('TEST_BACKUP_PYTHON', sys.executable)
        monkeypatch.setenv('TEST_BACKUP_CLIENT', str(client))
        monkeypatch.setenv('TEST_PG_DUMP_CONTAINER', container)
        monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ.get('PATH', ''))
        artifact = create_migration_backup(source_url.render_as_string(hide_password=False),
            backup_dir=tmp_path / 'archives', key_dir=tmp_path / 'keys')
        dump = Fernet(artifact.key_file.read_bytes()).decrypt(artifact.archive.read_bytes())
        process = subprocess.run(['docker', 'exec', '-i', container, 'pg_restore',
            '--no-owner', '--no-acl', '--exit-on-error', '-U', source_url.username,
            '-d', restored_url.database], input=dump, capture_output=True)
        assert process.returncode == 0, 'Synthetic backup restore failed'
        with restored.connect() as connection:
            assert connection.scalar(text('SELECT note FROM recovery_marker WHERE id=1')) == 'synthetic-preserved'
        assert artifact.archive.stat().st_mode & 0o777 == artifact.key_file.stat().st_mode & 0o777 == 0o600
    finally:
        source.dispose()
        restored.dispose()
