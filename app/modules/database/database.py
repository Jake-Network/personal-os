from collections.abc import Iterator

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
        assert self.engine is not None, "Database.init() not called"
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        assert self._sessionmaker is not None, "Database.init() not called"
        return self._sessionmaker()


db = Database()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with db.session() as session:
        yield session
