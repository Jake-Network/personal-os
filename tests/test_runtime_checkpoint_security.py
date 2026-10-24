"""Synthetic checkpoint migration and untrusted-object reconstruction regressions."""
from dataclasses import dataclass
import json
import os
from uuid import uuid4

import pytest
from alembic import command
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.modules.advisor.runtime.checkpoints import create_checkpointer
from app.modules.database.migration_manager import alembic_config


_reconstructed = []


@dataclass
class UntrustedCheckpointValue:
    label: str

    def __post_init__(self):
        _reconstructed.append(self.label)


@dataclass
class AllowedCheckpointValue:
    label: str


@pytest.fixture
def checkpoint_engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'checkpoints.db'}"
    admin = None
    schema = None
    configured = os.environ.get("TEST_DATABASE_URL", "")
    if configured.startswith("postgresql"):
        admin = create_engine(configured)
        schema = "checkpoint_security_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(configured).update_query_dict({"options": f"-csearch_path={schema},public"}).render_as_string(hide_password=False)
    migration = alembic_config(url)
    if schema is not None:
        migration.attributes["version_table_schema"] = schema
    command.upgrade(migration, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def _inject_checkpoint(engine, value, *, pending_write=False):
    """Simulate privileged database tampering, without running any unsafe code."""
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"answer": "safe" if pending_write else value}
    postgres = engine.dialect.name == "postgresql"
    serializer = JsonPlusSerializer()
    with engine.begin() as connection:
        if postgres:
            # Postgres keeps JSON graph structure and msgpack channel blobs apart.
            kind, payload = serializer.dumps_typed(checkpoint["channel_values"]["answer"])
            checkpoint["channel_values"] = {}
            checkpoint["channel_versions"] = {"answer": "1"}
            connection.execute(text("INSERT INTO checkpoints "
                "(thread_id,checkpoint_ns,checkpoint_id,checkpoint,metadata) "
                "VALUES ('synthetic','',:id,CAST(:payload AS jsonb),'{}'::jsonb)"),
                {"id": checkpoint["id"], "payload": json.dumps(checkpoint)})
            connection.execute(text("INSERT INTO checkpoint_blobs "
                "(thread_id,checkpoint_ns,channel,version,type,blob) "
                "VALUES ('synthetic','','answer','1',:kind,:payload)"),
                {"kind": kind, "payload": payload})
        else:
            kind, payload = serializer.dumps_typed(checkpoint)
            connection.execute(text("INSERT INTO checkpoints "
                "(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata) "
                "VALUES ('synthetic','',:id,:kind,:payload,:metadata)"),
                {"id": checkpoint["id"], "kind": kind, "payload": payload, "metadata": b"{}"})
        if pending_write:
            kind, payload = serializer.dumps_typed(value)
            table, blob = ("checkpoint_writes", "blob") if postgres else ("writes", "value")
            connection.execute(text(f"INSERT INTO {table} "
                f"(thread_id,checkpoint_ns,checkpoint_id,task_id,idx,channel,type,{blob}) "
                "VALUES ('synthetic','',:id,'task',0,'answer',:kind,:payload)"),
                {"id": checkpoint["id"], "kind": kind, "payload": payload})
    return {"configurable": {"thread_id": "synthetic", "checkpoint_ns": ""}}


@pytest.mark.parametrize("pending_write", [False, True])
def test_untrusted_checkpoint_constructor_is_not_revived(checkpoint_engine, pending_write):
    # Bypass the benign test constructor while preparing attacker-controlled bytes.
    value = object.__new__(UntrustedCheckpointValue)
    value.label = "must-stay-inert"
    _reconstructed.clear()
    config = _inject_checkpoint(checkpoint_engine, value, pending_write=pending_write)
    with create_checkpointer(checkpoint_engine, "synthetic", "worker", 1) as saver:
        loaded = saver.get_tuple(config)
    assert _reconstructed == []
    recovered = loaded.pending_writes[0][2] if pending_write else loaded.checkpoint["channel_values"]["answer"]
    assert recovered == {"label": "must-stay-inert"}


def test_derived_allowlist_reaches_underlying_saver_without_widening_original(checkpoint_engine):
    value = AllowedCheckpointValue("explicit-schema-type")
    config = _inject_checkpoint(checkpoint_engine, value)
    with create_checkpointer(checkpoint_engine, "synthetic", "worker", 1) as saver:
        scoped = saver.with_allowlist([(AllowedCheckpointValue.__module__, AllowedCheckpointValue.__name__)])
        assert scoped.get_tuple(config).checkpoint["channel_values"]["answer"] == value
        assert saver.get_tuple(config).checkpoint["channel_values"]["answer"] == {"label": value.label}


def test_checkpoint_upgrade_preserves_legacy_sqlite_pending_writes(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy-checkpoints.db'}"
    config = alembic_config(url)
    command.upgrade(config, "0015_decision_source_message")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO checkpoints "
            "(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata) "
            "VALUES ('legacy','','checkpoint','msgpack',:value,:metadata)"),
            {"value": b"synthetic-checkpoint", "metadata": b"{}"})
        connection.execute(text("INSERT INTO writes "
            "(thread_id,checkpoint_ns,checkpoint_id,task_id,idx,channel,type,value) "
            "VALUES ('legacy','','checkpoint','task',0,'answer','msgpack',:value)"),
            {"value": b"synthetic-pending-write"})
    command.upgrade(config, "head")
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("writes")}
        assert "task_path" in columns
        assert connection.execute(text("SELECT checkpoint FROM checkpoints")).scalar_one() == b"synthetic-checkpoint"
        row = connection.execute(text("SELECT value,task_path FROM writes")).one()
        assert row == (b"synthetic-pending-write", "")
    engine.dispose()
