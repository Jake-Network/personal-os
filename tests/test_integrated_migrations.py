"""Published agent and security migration branches converge without rewriting data."""
from contextlib import contextmanager
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, make_url, text

from app.modules.database.migration_manager import alembic_config


MERGED_HEAD = "0017_merge_agent_security"


def test_agent_and_checkpoint_branches_have_one_successor():
    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    assert script.get_heads() == [MERGED_HEAD]


@contextmanager
def branch_database(tmp_path, dialect, revision):
    admin = schema = None
    if dialect == "postgresql":
        configured = os.environ.get("TEST_DATABASE_URL", "")
        if not configured.startswith("postgresql"):
            pytest.skip("requires disposable PostgreSQL test database")
        admin = create_engine(configured)
        schema = "merge_security_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(configured).update_query_dict(
            {"options": f"-csearch_path={schema},public"}).render_as_string(hide_password=False)
    else:
        url = f"sqlite:///{tmp_path / 'branch.db'}"
    config = alembic_config(url)
    if schema:
        config.attributes["version_table_schema"] = schema
    engine = create_engine(url)
    try:
        command.upgrade(config, revision)
        yield config, engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
@pytest.mark.parametrize("revision", ["0016_agent_playbooks_inbox", "0016_checkpoint_task_path"])
def test_upgrade_from_either_branch_preserves_records(tmp_path, dialect, revision):
    with branch_database(tmp_path, dialect, revision) as (config, engine):
        agent_branch = revision == "0016_agent_playbooks_inbox"
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO advisor_conversations (id,title,created_at,updated_at) "
                "VALUES (501,'synthetic retained conversation','2026-10-01','2026-10-01')"))
            if agent_branch:
                connection.execute(text("INSERT INTO playbooks "
                    "(id,slug,status,source,external_allowed,created_at,updated_at) "
                    "VALUES (501,'retained-procedure','active','user',true,'2026-10-01','2026-10-01')"))
            if dialect == "sqlite":
                connection.execute(text("INSERT INTO checkpoints "
                    "(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata) "
                    "VALUES ('retained','','checkpoint','msgpack',:value,:metadata)"),
                    {"value": b"synthetic-checkpoint", "metadata": b"{}"})
                connection.execute(text("INSERT INTO writes "
                    "(thread_id,checkpoint_ns,checkpoint_id,task_id,idx,channel,type,value) "
                    "VALUES ('retained','','checkpoint','task',0,'answer','msgpack',:value)"),
                    {"value": b"synthetic-pending-write"})
                if not agent_branch:
                    connection.execute(text("UPDATE writes SET task_path='retained-path'"))
            else:
                connection.execute(text("INSERT INTO checkpoints "
                    "(thread_id,checkpoint_ns,checkpoint_id,checkpoint,metadata) "
                    "VALUES ('retained','','checkpoint','{}','{}')"))
                connection.execute(text("INSERT INTO checkpoint_blobs "
                    "(thread_id,checkpoint_ns,channel,version,type,blob) "
                    "VALUES ('retained','','answer','1','msgpack',:value)"),
                    {"value": b"synthetic-checkpoint"})
                connection.execute(text("INSERT INTO checkpoint_writes "
                    "(thread_id,checkpoint_ns,checkpoint_id,task_id,task_path,idx,channel,type,blob) "
                    "VALUES ('retained','','checkpoint','task','retained-path',0,'answer','msgpack',:value)"),
                    {"value": b"synthetic-pending-write"})
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == MERGED_HEAD
            assert connection.execute(text("SELECT title,origin FROM advisor_conversations WHERE id=501")).one() == (
                "synthetic retained conversation", "user")
            if agent_branch:
                assert connection.execute(text("SELECT slug FROM playbooks WHERE id=501")).scalar_one() == "retained-procedure"
            assert "playbook_revisions" in inspect(connection).get_table_names()
            table, blob = ("writes", "value") if dialect == "sqlite" else ("checkpoint_writes", "blob")
            value, path = connection.execute(text(f"SELECT {blob},task_path FROM {table} WHERE thread_id='retained'")).one()
            assert bytes(value) == b"synthetic-pending-write"
            assert path == ("" if dialect == "sqlite" and agent_branch else "retained-path")
            source, field = ("checkpoints", "checkpoint") if dialect == "sqlite" else ("checkpoint_blobs", "blob")
            assert bytes(connection.execute(text(f"SELECT {field} FROM {source} WHERE thread_id='retained'")).scalar_one()) == b"synthetic-checkpoint"
