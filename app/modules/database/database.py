import logging
from collections.abc import Iterator

from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.modules.database.model import Base

logger = logging.getLogger(__name__)


class Database:
    """Engine + session factory. Handlers receive a Session; they never open their own."""

    def __init__(self) -> None:
        self.engine: Engine | None = None
        self._sessionmaker: sessionmaker[Session] | None = None

    def init(self, url: str) -> Engine:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self._sessionmaker = None
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", lambda conn, _rec: conn.execute("PRAGMA foreign_keys=ON"))
        self._sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False)
        return self.engine

    def create_schema(self) -> None:
        """Create model tables for isolated tests; runtime uses migrations."""
        assert self.engine is not None, "Database.init() not called"
        Base.metadata.create_all(self.engine)

    def migrate_schema(self) -> None:
        """Build an empty database from the committed migrations; use an existing one as it is.

        Startup never alters, migrates or stamps a database that already has tables. Upgrading one
        is the explicit `python -m app.modules.database.migration_manager --apply` step.
        """
        assert self.engine is not None, "Database.init() not called"
        from app.modules.database.collation import check_collations
        from app.modules.database.legacy_adoption import inspection_schema, migration_config

        try:
            with self.engine.begin() as connection:
                if connection.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN")
                check_collations(connection)
                tables = set(inspect(connection).get_table_names(schema=inspection_schema(connection)))
                config = migration_config(connection)
                if not tables - {"alembic_version"}:
                    command.upgrade(config, "head")
                    return
                head = ScriptDirectory.from_config(config).get_current_head()
                current = MigrationContext.configure(connection, opts={
                    "version_table_schema": config.attributes.get("version_table_schema")}).get_current_revision()
                if current != head:
                    logger.warning(
                        "Database schema is at %s, not %s; it was left unchanged. Back up the database and "
                        "run `uv run python -m app.modules.database.migration_manager` to plan the upgrade.",
                        current or "an unversioned revision", head)
        except Exception:
            self.engine.dispose()
            self.engine = None
            self._sessionmaker = None
            raise

    def session(self) -> Session:
        assert self._sessionmaker is not None, "Database.init() not called"
        return self._sessionmaker()


db = Database()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with db.session() as session:
        yield session
