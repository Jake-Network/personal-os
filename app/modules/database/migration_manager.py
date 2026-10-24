"""Explicit, user-run migration of an existing database to the Alembic head.

Native app startup leaves an existing database unchanged; Docker's entrypoint upgrades it
automatically. This command supports explicit inspection and migration after an operator-managed pg_dump backup:

    uv run python -m app.modules.database.migration_manager            # show the plan (read-only)
    uv run python -m app.modules.database.migration_manager --apply    # migrate after verifying a pg_dump backup

A database created by `create_all` has no `alembic_version` table. Its tables and columns are
compared with the schema of every revision (built in a rollback-only PostgreSQL schema); only an exact match
is stamped, after which the append-only triggers that `create_all` never installs are added and the
remaining migrations run. Without an exact match nothing is changed. Existing rows are never
rewritten: migrations only add tables, columns, indexes, triggers and backfilled history rows.
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
    insp = inspect(engine)
    return {t: frozenset(c["name"] for c in insp.get_columns(t, schema=schema))
            for t in insp.get_table_names(schema=schema) if t != "alembic_version"}


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
        tables = schema_of(engine)
    finally:
        engine.dispose()
    result = MigrationPlan(current=current, head=head)
    if current is not None or not tables:
        return result
    closest: tuple[int, str, list[str]] | None = None
    for rev in script.walk_revisions():  # newest first
        expected = schema_at(rev.revision, url)
        if expected == tables:
            result.stamp = rev.revision
            return result
        diff = schema_differences(expected, tables)
        if closest is None or len(diff) < closest[0]:
            closest = (len(diff), rev.revision, diff)
    assert closest is not None
    result.differences = [f"closest revision {closest[1]}:"] + closest[2]
    return result


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


def apply(url: str, migration_plan: MigrationPlan) -> None:
    if migration_plan.action == "refuse":
        raise RuntimeError(migration_plan.describe())
    if migration_plan.action == "none":
        return None
    config = alembic_config(url)
    if migration_plan.stamp:
        command.stamp(config, migration_plan.stamp)
        engine = create_engine(url)
        try:
            ensure_append_only_triggers(engine)
        finally:
            engine.dispose()
    command.upgrade(config, "head")
    return None


def main(argv: list[str] | None = None) -> int:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="perform the plan (default: only show it)")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)
    args.database_url = args.database_url or settings.resolved_database_url
    migration_plan = plan(args.database_url)
    print(migration_plan.describe())
    if migration_plan.action == "refuse":
        return 1
    if args.apply:
        apply(args.database_url, migration_plan)
        print(f"Done: database is at {migration_plan.head}.")
    elif migration_plan.action != "none":
        print("Run again with --apply to perform it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
