"""A native migration must have an authenticated encrypted pg_dump before writing."""
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import stat
import subprocess
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import Conninfo


@dataclass(frozen=True)
class MigrationBackup:
    archive: Path
    key_file: Path


def _private_directory(path):
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError('Migration backup directories must be private (0700)')


def _write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_migration_backup(url, *, backup_dir=None, key_dir=None):
    """Dump without credential argv or plaintext files; fail before caller writes.

    The operator still stops application writes and keeps document/token-key
    backups. pg_dump provides a consistent database snapshot, not a guarantee
    that later writes before the migration have stopped.
    """
    from app.config import settings
    from app.modules.database.database import validate_database_url
    validate_database_url(url)
    binary = shutil.which('pg_dump')
    if binary is None:
        raise RuntimeError('pg_dump is required before applying a migration; install PostgreSQL client tools')
    archive_dir = Path(backup_dir or settings.data_dir / 'migration-backups').expanduser().resolve()
    keys = Path(key_dir or Path.home() / '.local/share/personal-os/migration-backup-keys').expanduser().resolve()
    if archive_dir.is_relative_to(keys) or keys.is_relative_to(archive_dir):
        raise RuntimeError('Migration backup keys must be kept outside the backup directory')
    try:
        _private_directory(archive_dir)
        _private_directory(keys)
    except OSError:
        raise RuntimeError('Migration backup storage is unavailable; no migration was applied') from None
    parsed = make_url(url)
    # pg_dump does not expand conninfo stored in PGDATABASE: it treats that
    # environment variable as a literal database name. Translate the same
    # driver options to libpq's documented environment variables instead.
    args, parameters = PGDialect_psycopg().create_connect_args(parsed)
    parameters = {**(conninfo_to_dict(args[0]) if args and args[0] else {}), **parameters}
    variables = {item.keyword.decode(): item.envvar.decode() for item in Conninfo.get_defaults()
                 if item.envvar is not None}
    environment = dict(os.environ)
    # Service settings take precedence over PG* environment defaults in pg_dump,
    # unlike the application's explicit connect arguments. Refuse them rather
    # than risk accepting a successful dump of a different database.
    if 'service' in parameters or environment.get('PGSERVICE'):
        raise RuntimeError('Migration backup does not support libpq service configuration; '
                           'use explicit connection settings and unset PGSERVICE')
    for name, value in parameters.items():
        if value is None:
            continue
        variable = variables.get(name)
        if variable is None:
            raise RuntimeError(f'PostgreSQL backup cannot safely transport connection option: {name}')
        if name == 'dbname' and (str(value).startswith(('postgresql://', 'postgres://')) or '=' in str(value)):
            raise RuntimeError('PostgreSQL backup requires an explicit database name, not nested connection information')
        environment[variable] = str(value)
    environment.setdefault('PGCONNECT_TIMEOUT', '30')
    try:
        result = subprocess.run([binary, '--format=custom', '--no-owner', '--no-acl'],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('PostgreSQL backup failed; no migration was applied') from None
    if result.returncode != 0 or not result.stdout.startswith(b'PGDMP'):
        raise RuntimeError('PostgreSQL backup failed or returned an invalid dump; no migration was applied')
    name = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    archive, key_file = archive_dir / (name + '.pgdump.fernet'), keys / (name + '.key')
    key = Fernet.generate_key()
    key_written = archive_written = False
    try:
        _write_private(key_file, key)
        key_written = True
        _write_private(archive, Fernet(key).encrypt(result.stdout))
        archive_written = True
        _sync_directory(keys)
        _sync_directory(archive_dir)
        # Verify the persisted recovery point before allowing any schema write.
        if Fernet(key_file.read_bytes()).decrypt(archive.read_bytes()) != result.stdout:
            raise RuntimeError('Migration backup verification failed')
    except BaseException as error:
        if archive_written:
            archive.unlink(missing_ok=True)
        if key_written:
            key_file.unlink(missing_ok=True)
        if isinstance(error, (OSError, InvalidToken)):
            raise RuntimeError('Migration backup storage/verification failed; no migration was applied') from None
        raise
    return MigrationBackup(archive=archive, key_file=key_file)
