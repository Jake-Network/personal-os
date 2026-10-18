from collections.abc import Iterator

from alembic import command
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.modules.database.model import Base


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
        """Upgrade the configured database, including migration-only constraints."""
        assert self.engine is not None, "Database.init() not called"
        from app.modules.database.collation import check_collations
        from app.modules.database.legacy_adoption import has_unversioned_tables, migration_config

        try:
            with self.engine.begin() as connection:
                if connection.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN")
                check_collations(connection)
                if has_unversioned_tables(connection):
                    raise RuntimeError(
                        "Existing database has tables without Alembic history. Back up the database, "
                        "then run make db-adopt-legacy to validate it, and "
                        "make db-adopt-legacy APPLY=1 to explicitly adopt and upgrade it."
                    )
                command.upgrade(migration_config(connection), "head")
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
