"""Published agent and security migration branches converge without rewriting data."""
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.modules.database.migration_manager import alembic_config


HEAD = "0019_fx_rate_per_pair"


def test_agent_and_checkpoint_branches_have_one_successor(postgres_url):
    script = ScriptDirectory.from_config(alembic_config(postgres_url))
    assert script.get_heads() == [HEAD]


@pytest.mark.parametrize("revision", ["0016_agent_playbooks_inbox", "0016_checkpoint_task_path", "0017_merge_agent_security", "0017_workout_duration_seconds"])
def test_upgrade_from_either_branch_preserves_records(postgres_url, revision):
    config = alembic_config(postgres_url)
    engine = create_engine(postgres_url)
    try:
        command.upgrade(config, revision)
        agent_branch = revision in {"0016_agent_playbooks_inbox", "0017_merge_agent_security"}
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO advisor_conversations (id,title,created_at,updated_at) "
                "VALUES (501,'synthetic retained conversation','2026-10-01','2026-10-01')"))
            if agent_branch:
                connection.execute(text("INSERT INTO playbooks "
                    "(id,slug,status,source,external_allowed,created_at,updated_at) "
                    "VALUES (501,'retained-procedure','active','user',true,'2026-10-01','2026-10-01')"))
            seconds = revision == "0017_workout_duration_seconds"
            duration_field = "duration_seconds" if seconds else "duration_minutes"
            connection.execute(text(f"INSERT INTO workout_logs "
                f"(id,performed_on,activity,{duration_field},created_at,updated_at) "
                "VALUES (501,'2026-10-24','synthetic retained workout',:duration,'2026-10-24','2026-10-24')"),
                {"duration": 2737 if seconds else 46})
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
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
            assert connection.execute(text("SELECT title,origin FROM advisor_conversations WHERE id=501")).one() == (
                "synthetic retained conversation", "user")
            if agent_branch:
                assert connection.execute(text("SELECT slug FROM playbooks WHERE id=501")).scalar_one() == "retained-procedure"
            assert "playbook_revisions" in inspect(connection).get_table_names(schema=inspect(connection).default_schema_name)
            assert connection.execute(text("SELECT duration_seconds FROM workout_logs WHERE id=501")).scalar_one() == (2737 if seconds else 2760)
            table, blob = "checkpoint_writes", "blob"
            value, path = connection.execute(text(f"SELECT {blob},task_path FROM {table} WHERE thread_id='retained'")).one()
            assert bytes(value) == b"synthetic-pending-write"
            assert path == "retained-path"
            source, field = "checkpoint_blobs", "blob"
            assert bytes(connection.execute(text(f"SELECT {field} FROM {source} WHERE thread_id='retained'")).scalar_one()) == b"synthetic-checkpoint"
    finally:
        engine.dispose()
