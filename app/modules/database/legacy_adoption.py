"""Explicit, parity-checked adoption of historical create_all databases.

Never called at startup. Explicit --apply creates an encrypted pg_dump before stamping; stop application writes and retain document/token-key backups separately.
"""
import argparse
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import UserDefinedType

SUPPORTED_REVISIONS = (
    "0001_baseline", "0002_portfolio", "0003_google_oauth", "0004_portfolio_identity",
)


def migration_config(connection):
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["connection"] = connection
    config.attributes["version_table_schema"] = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    return config


def inspection_schema(connection):
    return connection.exec_driver_sql("SELECT current_schema()").scalar_one()


def has_unversioned_tables(connection):
    schema = inspection_schema(connection)
    tables = set(inspect(connection).get_table_names(schema=schema))
    if not tables - {"alembic_version"}:
        return False
    if "alembic_version" not in tables:
        return True
    table = "alembic_version"
    if schema is not None:
        table = connection.dialect.identifier_preparer.quote_schema(schema) + "." + table
    return not connection.exec_driver_sql(f"SELECT version_num FROM {table}").first()



def normalized_default(default, schema):
    # PostgreSQL reflection qualifies local serial sequences when schema is
    # explicit. Normalize only that local reference; foreign sequences stay distinct.
    if default and schema:
        for identifier in (schema, '"' + schema.replace('"', '""') + '"'):
            prefix = "nextval('" + identifier.replace("'", "''") + "."
            if default.startswith(prefix):
                return "nextval('" + default[len(prefix):]
    return default


def schema_signature(connection):
    """Compare actual database semantics, independent of generated constraint names."""
    inspector = inspect(connection)
    signature = {}
    current_schema = inspection_schema(connection)
    for table in sorted(set(inspector.get_table_names(schema=current_schema)) - {"alembic_version"}):
        columns = tuple((c["name"], str(c["type"].compile(dialect=connection.dialect)),
                         c["nullable"], normalized_default(c.get("default"), current_schema))
                        for c in inspector.get_columns(table, schema=current_schema))
        foreign_keys = sorted((tuple(f["constrained_columns"]),
                               "" if f.get("referred_schema") in (None, current_schema) else f["referred_schema"],
                               f["referred_table"],
                               tuple(f["referred_columns"]), tuple(sorted(f.get("options", {}).items())))
                              for f in inspector.get_foreign_keys(table, schema=current_schema))
        indexes = sorted((i["name"], tuple(i["column_names"]), bool(i["unique"]),
                          str(i.get("dialect_options", {})))
                         for i in inspector.get_indexes(table, schema=current_schema) if not i.get("duplicates_constraint"))
        uniques = sorted(tuple(u["column_names"]) for u in inspector.get_unique_constraints(table, schema=current_schema))
        checks = sorted(c["sqltext"] for c in inspector.get_check_constraints(table, schema=current_schema))
        signature[table] = (columns, tuple(inspector.get_pk_constraint(table, schema=current_schema)["constrained_columns"]),
                            foreign_keys, indexes, uniques, checks)
    return signature


class _ExtensionVector(UserDefinedType):
    cache_ok = True

    def __init__(self, qualified_name, dimensions):
        self.qualified_name, self.dimensions = qualified_name, dimensions

    def get_col_spec(self, **_kw):
        suffix = f"({self.dimensions})" if self.dimensions is not None else ""
        return self.qualified_name + suffix


@contextmanager
def reference_connection(connection):
    # Only scratch objects and pg_catalog are name-visible. Existing extension
    # types are qualified in connection-local DDL instead of exposing all tables
    # in the extension's schema (which is commonly the operational public schema).
    from pgvector.sqlalchemy import Vector
    transaction = connection.begin_nested()
    previous_path = connection.exec_driver_sql("SHOW search_path").scalar_one()
    extension_schema = connection.execute(text("SELECT n.nspname FROM pg_catalog.pg_extension e "
        "JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'")).scalar_one_or_none()
    qualified_vector = (connection.dialect.identifier_preparer.quote_schema(extension_schema) + '.vector'
                        if extension_schema else None)
    schema = "legacy_check_" + uuid4().hex

    def qualify_extension(_connection, statement, multiparams, params, execution_options):
        if qualified_vector and isinstance(statement, CreateTable) and any(
                isinstance(column.type, Vector) for column in statement.element.columns):
            metadata = MetaData()
            for original in statement.element.metadata.tables.values():
                original.to_metadata(metadata)
            table = metadata.tables[statement.element.key]
            for column in table.columns:
                if isinstance(column.type, Vector):
                    column.type = _ExtensionVector(qualified_vector, column.type.dim)
            statement = CreateTable(table, if_not_exists=statement.if_not_exists)
        return statement, multiparams, params

    event.listen(connection, 'before_execute', qualify_extension, retval=True)
    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        yield connection
    finally:
        event.remove(connection, 'before_execute', qualify_extension)
        transaction.rollback()
        connection.execute(text("SELECT set_config('search_path', :path, true)"), {"path": previous_path})


def validate_legacy(connection):
    if not has_unversioned_tables(connection):
        raise RuntimeError("Database is empty or already versioned; legacy adoption is not applicable")
    actual = schema_signature(connection)
    with reference_connection(connection) as scratch:
        config = migration_config(scratch)
        for revision in SUPPORTED_REVISIONS:
            command.upgrade(config, revision)
            if schema_signature(scratch) == actual:
                return revision
    raise RuntimeError("Legacy schema does not exactly match a supported frozen revision; no adoption performed")


def adopt_legacy(engine, *, apply=False, backup_dir=None, backup_key_dir=None, report_backup=None):
    """Validate read-only, then back up before an atomic adoption/upgrade."""
    with engine.begin() as connection:
        revision = validate_legacy(connection)
    if not apply:
        return revision
    from app.modules.database.migration_backup import create_migration_backup
    backup = create_migration_backup(engine.url, backup_dir=backup_dir, key_dir=backup_key_dir)
    if report_backup:
        report_backup(backup)
    with engine.begin() as connection:
        if validate_legacy(connection) != revision:
            raise RuntimeError("Legacy schema changed after backup; no adoption performed")
        from app.modules.database.collation import check_collations
        check_collations(connection)
        config = migration_config(connection)
        command.stamp(config, revision)
        command.upgrade(config, "head")
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Stamp validated baseline and upgrade (back up first)")
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--backup-key-dir", default=None)
    args = parser.parse_args()
    from app.config import settings
    engine = create_engine(settings.resolved_database_url)
    try:
        revision = adopt_legacy(engine, apply=args.apply, backup_dir=args.backup_dir, backup_key_dir=args.backup_key_dir,
            report_backup=lambda backup: print(f"Encrypted backup: {backup.archive}\nBackup key (retain separately): {backup.key_file}"))
        print(f"Validated legacy schema: {revision}. " +
              ("Adopted and upgraded to head." if args.apply else "No application schema changed. Run with --apply to adopt."))
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
