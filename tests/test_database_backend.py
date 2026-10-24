"""Runtime requires an explicit PostgreSQL connection and preserves active engines on invalid input."""
import pytest

from app.config import Settings
from app.modules.database.database import Database


def test_database_url_is_required():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _ = Settings(database_url="").resolved_database_url


@pytest.mark.parametrize("url", ["mysql://localhost/personal", "file:///personal.db"])
def test_database_url_rejects_other_backends(url):
    with pytest.raises(ValueError, match="PostgreSQL"):
        _ = Settings(database_url=url).resolved_database_url


def test_invalid_backend_preserves_active_database(postgres_url):
    database = Database()
    engine = database.init(postgres_url)
    factory = database._sessionmaker
    try:
        with pytest.raises(ValueError, match="PostgreSQL"):
            database.init("mysql://localhost/personal")
        assert database.engine is engine
        assert database._sessionmaker is factory
    finally:
        engine.dispose()


def test_child_schema_owns_models_and_requires_its_own_checkpoints(postgres_database):
    from alembic import command
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    from app.modules.advisor.runtime.checkpoints import CheckpointSchemaMissing, create_checkpointer
    from app.modules.database.migration_manager import alembic_config

    parent_url, child_url = postgres_database(), postgres_database()
    command.upgrade(alembic_config(parent_url), "head")
    parent = create_engine(parent_url)
    child = Database()
    try:
        with parent.begin() as connection:
            parent_schema = connection.execute(text("SELECT current_schema()")).scalar_one()
            connection.execute(text("""INSERT INTO accounts
                (name,kind,currency,balance,balance_as_of,is_liquid,created_at,updated_at)
                VALUES ('synthetic parent','checking','KRW',123,'2026-10-01',true,now(),now())"""))
        child_engine = create_engine(child_url)
        with child_engine.connect() as connection:
            child_schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        child_engine.dispose()
        visible = make_url(child_url).update_query_dict({
            "options": f"-csearch_path={child_schema},{parent_schema},public",
        }).render_as_string(hide_password=False)
        child.init(visible)
        child.create_schema()
        with child.engine.connect() as connection:
            assert "accounts" in inspect(connection).get_table_names(schema=child_schema)
            assert connection.execute(text("SELECT count(*) FROM accounts")).scalar_one() == 0
        with pytest.raises(CheckpointSchemaMissing):
            with create_checkpointer(child.engine, "synthetic", "worker", 1):
                pass
        with parent.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM accounts")).scalar_one() == 1
    finally:
        if child.engine is not None:
            child.engine.dispose()
        parent.dispose()
