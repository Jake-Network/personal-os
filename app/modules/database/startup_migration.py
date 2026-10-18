"""Docker bootstrap: wait for the DB, serialize migrations, then upgrade to this image's head."""
import hashlib
import logging
import math
import os
import sys
import time

from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.modules.database.collation import check_collations
from app.modules.database.legacy_adoption import has_unversioned_tables, migration_config

logger = logging.getLogger(__name__)


class StartupMigrationError(RuntimeError):
    """A bootstrap failure whose static message is safe to show in container logs."""


def _connect(engine, deadline):
    while True:
        try:
            return engine.connect()
        except OperationalError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StartupMigrationError('Database did not become available before the migration timeout') from None
            time.sleep(min(1, remaining))


def upgrade_database(engine, timeout=60):
    """Apply committed revisions only. No adoption, stamp, downgrade, or retry of failed DDL.

    The migration lock and Alembic DDL share one connection/transaction. A second
    bootstrap re-inspects the version only after the first one releases its lock.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Migration timeout must be a positive finite number')
    deadline = time.monotonic() + timeout
    with _connect(engine, deadline) as connection:
        with connection.begin():
            remaining_ms = max(1, math.ceil((deadline - time.monotonic()) * 1000))
            if connection.dialect.name == 'sqlite':
                connection.exec_driver_sql(f'PRAGMA busy_timeout={remaining_ms}')
                # Explicit BEGIN also makes SQLite DDL rollback on migration failure.
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            elif connection.dialect.name == 'postgresql':
                connection.execute(text("SELECT set_config('lock_timeout', :timeout, true)"),
                                   {'timeout': f'{remaining_ms}ms'})
                identity = connection.exec_driver_sql('SELECT current_database(), current_schema()').one()
                key = int.from_bytes(hashlib.sha256(repr(tuple(identity)).encode()).digest()[:8], 'big', signed=True)
                connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
            else:
                raise StartupMigrationError('Automatic migration supports SQLite and PostgreSQL only')
            check_collations(connection)
            if has_unversioned_tables(connection):
                raise StartupMigrationError('Existing database has no Alembic history; use explicit legacy adoption first '
                                   '(PERSONAL_OS_AUTO_MIGRATE=0 for maintenance)')
            config = migration_config(connection)
            script = ScriptDirectory.from_config(config)
            head = script.get_current_head()
            current = MigrationContext.configure(connection, opts={
                'version_table_schema': config.attributes.get('version_table_schema')}).get_current_heads()
            ancestors = {revision.revision for revision in script.walk_revisions(base='base', head=head)}
            if any(revision not in ancestors for revision in current):
                raise StartupMigrationError('Database revision is not supported by this image; no automatic downgrade was attempted')
            if current == (head,):
                logger.info('Database is already at the image migration head')
                return
            logger.info('Applying committed migrations: alembic upgrade head')
            command.upgrade(config, 'head')
            logger.info('Database migration completed')


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    enabled = os.environ.get('PERSONAL_OS_AUTO_MIGRATE', '1').strip().lower()
    if enabled in {'0', 'false'}:
        logger.info('Automatic migration disabled for this maintenance container')
        return 0
    if enabled not in {'1', 'true'}:
        logger.error('PERSONAL_OS_AUTO_MIGRATE must be 1/true or 0/false')
        return 1
    engine = None
    try:
        from app.config import settings
        if os.environ.get('PERSONAL_OS_PRODUCTION', '').lower() == 'true':
            from app.modules.security.deployment_checks import validate_local_services
            validate_local_services(settings.resolved_database_url, settings.embedding_url)
        timeout = float(os.environ.get('PERSONAL_OS_MIGRATION_TIMEOUT_SECONDS', '60'))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid migration timeout')
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if settings.resolved_database_url.startswith('postgresql'):
            kwargs['connect_args'] = {'connect_timeout': max(1, min(5, math.ceil(timeout)))}
        engine = create_engine(settings.resolved_database_url, **kwargs)
        upgrade_database(engine, timeout=timeout)
        return 0
    except Exception as exc:
        # SQLAlchemy errors can include connection URLs, credentials or SQL data.
        # Keep diagnostics actionable without printing those exception details.
        reason = str(exc) if isinstance(exc, StartupMigrationError) else type(exc).__name__
        logger.error('Database startup migration failed (%s); server will not start. '
                     'Check DB availability, migration history and backups. '
                     'Use PERSONAL_OS_AUTO_MIGRATE=0 only for maintenance.', reason)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
