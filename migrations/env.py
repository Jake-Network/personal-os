"""Use the same server-side database settings as FastAPI."""
from contextlib import contextmanager
from copy import copy

from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.modules.database.model import Base

config = context.config
url = config.attributes.get("database_url") or settings.resolved_database_url

# These tables belong to the explicitly migrated official LangGraph savers,
# whose dialect-specific formats are intentionally outside application ORM models.
CHECKPOINT_TABLES = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in CHECKPOINT_TABLES | {"alembic_version"})

@contextmanager
def sqlite_foreign_key_actions(connection):
    """Reflect inline FK actions from SQLite itself, without hiding schema drift.

    SQLAlchemy's SQLite DDL parser only discovers actions on table-level FOREIGN
    KEY clauses. ADD COLUMN ... REFERENCES is additive and preserves child rows,
    but its actions must be read from PRAGMA for accurate Alembic comparisons.
    The migration engine uses a temporary dialect copy, restored on every exit.
    SQLAlchemy inspectors resolve their dialect through the connection engine.
    """
    original = connection.dialect
    if original.name != "sqlite":
        yield
        return

    def get_foreign_keys(bind, table_name, schema=None, **kwargs):
        reflected = original.get_foreign_keys(bind, table_name, schema=schema, **kwargs)
        quote = original.identifier_preparer.quote
        namespace = f"{quote(schema)}." if schema else ""
        rows = bind.exec_driver_sql(f"PRAGMA {namespace}foreign_key_list({quote(table_name)})").fetchall()
        groups = {}
        for row in rows:
            groups.setdefault(row[0], []).append(row)
        actions = {}
        for group in groups.values():
            ordered = sorted(group, key=lambda row: row[1])
            key = (tuple(row[3] for row in ordered), ordered[0][2], tuple(row[4] for row in ordered))
            actions[key] = {"onupdate": ordered[0][5], "ondelete": ordered[0][6]}
        result = []
        for fk in reflected:
            options = dict(fk.get("options", {}))
            key = (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for action, value in actions.get(key, {}).items():
                if value == "NO ACTION":
                    options.pop(action, None)
                else:
                    options[action] = value
            result.append({**fk, "options": options})
        return result

    original_engine_dialect = connection.engine.dialect
    connection.dialect = copy(original)
    connection.dialect.get_foreign_keys = get_foreign_keys
    connection.engine.dialect = connection.dialect
    try:
        yield
    finally:
        connection.dialect = original
        connection.engine.dialect = original_engine_dialect


def run_migrations(connection):
    with sqlite_foreign_key_actions(connection):
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                          version_table_schema=config.attributes.get("version_table_schema"),
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
                with engine.connect() as connection:
                    run_migrations(connection)
            finally:
                engine.dispose()

run()
