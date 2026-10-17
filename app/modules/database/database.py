from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
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
        root = Path(__file__).resolve().parents[3]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def session(self) -> Session:
        assert self._sessionmaker is not None, "Database.init() not called"
        return self._sessionmaker()


db = Database()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with db.session() as session:
        yield session
