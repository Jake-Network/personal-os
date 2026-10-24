"""Explicit, user-run migration of an existing database to the Alembic head.

Native app startup leaves an existing database unchanged; Docker's entrypoint upgrades it
automatically. This command supports explicit inspection and migration with an automatic encrypted pg_dump backup before any schema write:

    uv run python -m app.modules.database.migration_manager            # show the plan (read-only)
    uv run python -m app.modules.database.migration_manager --apply    # back up, then migrate (requires pg_dump)

A database created by `create_all` has no `alembic_version` table. Its tables and columns are
compared with the schema of every revision (built in a rollback-only PostgreSQL schema); only an exact match
is stamped, after which the append-only triggers that `create_all` never installs are added and the
remaining migrations run. Without an exact match nothing is changed. Existing data changes are limited to the explicit, versioned migration contracts; planning never writes the application schema.
"""

import argparse
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

from app.modules.database.schema_diff import schema_differences
from app.modules.database.types import MigrationPlan, Schema

ROOT = Path(__file__).resolve().parents[3]

# Append-only tables guarded by triggers in migrations 0002 and 0005 (same names, so downgrades work).
APPEND_ONLY = {
    "monthly_snapshots": ("reject_monthly_snapshot_mutation", "monthly_snapshots_immutable",
                          "Monthly snapshots are append-only"),
    "manual_value_changes": ("reject_manual_value_change_mutation", "manual_value_changes_immutable",
                             "Manual value history is append-only"),
}


def alembic_config(url: str) -> Config:
    from app.modules.database.database import validate_database_url
    validate_database_url(url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["database_url"] = url
    return config


def schema_of(engine: Engine | Connection) -> Schema:
    from app.modules.database.legacy_adoption import inspection_schema
    if isinstance(engine, Engine):
        with engine.connect() as connection:
            return schema_of(connection)
    schema = inspection_schema(engine)
    tables = {table: set() for table in inspect(engine).get_table_names(schema=schema)
              if table != "alembic_version"}
    for table, column in engine.execute(text("SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema=:schema"), {'schema': schema}):
        if table in tables:
            tables[table].add(column)
    return {table: frozenset(columns) for table, columns in tables.items()}


@cache
def schema_at(revision: str, url: str) -> Schema:
    """Inspect a revision in a private PostgreSQL schema rolled back on exit."""
    from app.modules.database.legacy_adoption import migration_config, reference_connection

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            with reference_connection(connection) as scratch:
                command.upgrade(migration_config(scratch), revision)
                return schema_of(scratch)
    finally:
        engine.dispose()


def _revision_schemas(connection, script):
    """Execute each migration once, projecting away unrelated sibling branches.

    The planner compares table/column shapes. Capturing each step's column delta
    lets a branch's shape be reconstructed from its ancestors even though the
    one scratch schema has also traversed earlier independent sibling branches.
    """
    from app.modules.database.legacy_adoption import migration_config, reference_connection
    revisions = list(script.walk_revisions())
    results, deltas, ancestors, processed = {}, {}, {}, []
    with reference_connection(connection) as scratch:
        config = migration_config(scratch)
        previous = {}
        for revision in reversed(revisions):
            command.upgrade(config, revision.revision)
            observed = schema_of(scratch)
            changes = {}
            for table in previous.keys() | observed.keys():
                if table not in observed:
                    changes[table] = None
                elif table not in previous or observed[table] != previous[table]:
                    changes[table] = (observed[table] - previous.get(table, frozenset()),
                                      previous.get(table, frozenset()) - observed[table])
            deltas[revision.revision] = changes
            parents = []
            for value in (revision.down_revision, revision.dependencies):
                parents.extend((value,) if isinstance(value, str) else value or ())
            lineage = {revision.revision}
            for parent in parents:
                lineage.update(ancestors[parent])
            ancestors[revision.revision] = lineage
            processed.append(revision.revision)
            expected = {}
            for key in processed:
                if key not in lineage:
                    continue
                for table, change in deltas[key].items():
                    if change is None:
                        expected.pop(table, None)
                    else:
                        added, removed = change
                        expected[table] = (expected.get(table, frozenset()) | added) - removed
            results[revision.revision] = expected
            previous = observed
    return results


def plan(url: str) -> MigrationPlan:
    config = alembic_config(url)
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            from app.modules.database.legacy_adoption import inspection_schema
            current = MigrationContext.configure(conn, opts={
                "version_table_schema": inspection_schema(conn)}).get_current_revision()
            tables = schema_of(conn)
            result = MigrationPlan(current=current, head=head)
            if current is not None or not tables:
                return result
            shapes = _revision_schemas(conn, script)
            closest = None
            for revision in script.walk_revisions():  # newest exact match wins
                expected = shapes[revision.revision]
                if expected == tables:
                    result.stamp = revision.revision
                    return result
                diff = schema_differences(expected, tables)
                if closest is None or len(diff) < closest[0]:
                    closest = (len(diff), revision.revision, diff)
            assert closest is not None
            result.differences = [f"closest revision {closest[1]}:"] + closest[2]
            return result
    finally:
        engine.dispose()


def ensure_append_only_triggers(engine: Engine) -> None:
    from app.modules.database.legacy_adoption import inspection_schema
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names(schema=inspection_schema(conn)))
        for table, (function, pg_trigger, message) in APPEND_ONLY.items():
            if table not in tables:
                continue
            exists = conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgname = :n AND tgrelid = to_regclass(:table)"), {"n": pg_trigger, "table": table}).first()
            if not exists:
                conn.execute(text(f"""CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '{message}'; END; $$"""))
                conn.execute(text(f"""CREATE TRIGGER {pg_trigger} BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION {function}()"""))


def apply(url: str, migration_plan: MigrationPlan, *, backup_dir=None, backup_key_dir=None):
    if migration_plan.action == "refuse":
        raise RuntimeError(migration_plan.describe())
    if migration_plan.action == "none":
        return None
    from app.modules.database.migration_backup import create_migration_backup
    backup = create_migration_backup(url, backup_dir=backup_dir, key_dir=backup_key_dir)
    config = alembic_config(url)
    if migration_plan.stamp:
        command.stamp(config, migration_plan.stamp)
        engine = create_engine(url)
        try:
            ensure_append_only_triggers(engine)
        finally:
            engine.dispose()
    command.upgrade(config, "head")
    return backup


def main(argv: list[str] | None = None) -> int:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="perform the plan (default: only show it)")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--backup-dir", default=None, help="private encrypted backup directory")
    parser.add_argument("--backup-key-dir", default=None, help="private key directory outside the backups")
    args = parser.parse_args(argv)
    args.database_url = args.database_url or settings.resolved_database_url
    migration_plan = plan(args.database_url)
    print(migration_plan.describe())
    if migration_plan.action == "refuse":
        return 1
    if args.apply:
        try:
            backup = apply(args.database_url, migration_plan, backup_dir=args.backup_dir, backup_key_dir=args.backup_key_dir)
        except RuntimeError as error:
            parser.exit(1, f"{error}\n")
        if backup:
            print(f"Encrypted backup: {backup.archive}\nBackup key (retain separately): {backup.key_file}")
        print(f"Done: database is at {migration_plan.head}.")
    elif migration_plan.action != "none":
        print("Run again with --apply to perform it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
