"""Explicit, user-run migration of an existing database to the Alembic head.

The app never changes the schema of an existing database at startup. This command does, and only
when asked:

    uv run python -m app.modules.database.migration_manager            # show the plan (read-only)
    uv run python -m app.modules.database.migration_manager --apply    # back up (SQLite), then migrate

A database created by `create_all` has no `alembic_version` table. Its tables and columns are
compared with the schema of every revision (built in a temporary SQLite file); only an exact match
is stamped, after which the append-only triggers that `create_all` never installs are added and the
remaining migrations run. Without an exact match nothing is changed. Existing rows are never
rewritten: migrations only add tables, columns, indexes, triggers and backfilled history rows.
"""

import argparse
import shutil
import tempfile
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from app.modules.database.schema_diff import schema_differences
from app.modules.database.types import MigrationPlan, Schema

ROOT = Path(__file__).resolve().parents[3]

# Append-only tables guarded by triggers in migrations 0002 and 0005 (same names, so downgrades work).
APPEND_ONLY = {
    "monthly_snapshots": ("reject_monthly_snapshot_mutation", "monthly_snapshots_immutable",
                          "monthly_snapshots_no_", "Monthly snapshots are append-only"),
    "manual_value_changes": ("reject_manual_value_change_mutation", "manual_value_changes_immutable",
                             "manual_value_changes_no_", "Manual value history is append-only"),
}


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["database_url"] = url
    return config


def schema_of(engine: Engine) -> Schema:
    insp = inspect(engine)
    return {t: frozenset(c["name"] for c in insp.get_columns(t))
            for t in insp.get_table_names() if t != "alembic_version"}


@cache
def schema_at(revision: str) -> Schema:
    """Tables and columns after upgrading an empty database to `revision`."""
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'probe.db'}"
        command.upgrade(alembic_config(url), revision)
        engine = create_engine(url)
        try:
            return schema_of(engine)
        finally:
            engine.dispose()


def plan(url: str) -> MigrationPlan:
    config = alembic_config(url)
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        tables = schema_of(engine)
    finally:
        engine.dispose()
    result = MigrationPlan(current=current, head=head)
    if current is not None or not tables:
        return result
    closest: tuple[int, str, list[str]] | None = None
    for rev in script.walk_revisions():  # newest first
        expected = schema_at(rev.revision)
        if expected == tables:
            result.stamp = rev.revision
            return result
        diff = schema_differences(expected, tables)
        if closest is None or len(diff) < closest[0]:
            closest = (len(diff), rev.revision, diff)
    assert closest is not None
    result.differences = [f"closest revision {closest[1]}:"] + closest[2]
    return result


def backup_sqlite(url: str, now: datetime | None = None) -> Path | None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        return None
    source = Path(parsed.database)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = source.with_name(f"{source.name}.bak-{stamp}")
    shutil.copy2(source, target)
    return target


def ensure_append_only_triggers(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, (function, pg_trigger, sqlite_prefix, message) in APPEND_ONLY.items():
            if table not in tables:
                continue
            if engine.dialect.name == "sqlite":
                for action in ("UPDATE", "DELETE"):
                    conn.execute(text(f"""CREATE TRIGGER IF NOT EXISTS {sqlite_prefix}{action.lower()}
                        BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, '{message}'); END"""))
            elif engine.dialect.name == "postgresql":
                exists = conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgname = :n"), {"n": pg_trigger}).first()
                if not exists:
                    conn.execute(text(f"""CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
                        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '{message}'; END; $$"""))
                    conn.execute(text(f"""CREATE TRIGGER {pg_trigger} BEFORE UPDATE OR DELETE ON {table}
                        FOR EACH ROW EXECUTE FUNCTION {function}()"""))


def apply(url: str, migration_plan: MigrationPlan) -> Path | None:
    if migration_plan.action == "refuse":
        raise RuntimeError(migration_plan.describe())
    if migration_plan.action == "none":
        return None
    backup = backup_sqlite(url)
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
    parser.add_argument("--database-url", default=settings.resolved_database_url)
    args = parser.parse_args(argv)
    migration_plan = plan(args.database_url)
    print(migration_plan.describe())
    if migration_plan.action == "refuse":
        return 1
    if args.apply:
        backup = apply(args.database_url, migration_plan)
        if backup:
            print(f"Backup: {backup}")
        print(f"Done: database is at {migration_plan.head}.")
    elif migration_plan.action != "none":
        print("Run again with --apply to perform it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
