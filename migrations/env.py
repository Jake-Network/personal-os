"""Use the same server-side database settings as FastAPI."""
from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.modules.database.database import validate_database_url
from app.modules.database.model import Base

config = context.config
connection = config.attributes.get("connection")
url = (connection.engine.url if connection is not None else
       config.attributes.get("database_url") or settings.resolved_database_url)
validate_database_url(url)

# These tables belong to the explicitly migrated official LangGraph savers,
# whose schema is intentionally outside application ORM models.
CHECKPOINT_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in CHECKPOINT_TABLES | {"alembic_version"})

def run_migrations(connection):
    schema = config.attributes.get("version_table_schema") or connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                      version_table_schema=schema,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run():
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        connection = config.attributes.get("connection")
        if connection is not None:
            run_migrations(connection)
        else:
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    run_migrations(connection)
            finally:
                engine.dispose()

run()
