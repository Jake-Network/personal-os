"""Checkpoint persistence is migrated explicitly and fenced independently of app writes."""
import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.graph import START, END, StateGraph
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.modules.advisor.runtime.checkpoints import (
    CheckpointLeaseLost, CheckpointSchemaMissing, create_checkpointer,
)
from app.modules.database.migration_manager import alembic_config
from app.modules.database.model import AdvisorConversation, AdvisorRun


@pytest.fixture
def checkpoint_engine(tmp_path, postgres_url):
    url = postgres_url
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    with Session(engine) as session:
        session.add(AdvisorConversation(id=1, title="synthetic"))
        session.flush()
        session.add(AdvisorRun(id="run", conversation_id=1, request_id="request", status="running",
            input_payload={}, lease_owner="worker", lease_generation=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=5)))
        session.commit()
    yield engine
    engine.dispose()


def test_stale_worker_cannot_write_checkpoint_or_pending_writes(checkpoint_engine):
    config = {"configurable": {"thread_id": "run", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    with checkpoint_engine.begin() as connection:
        connection.execute(text("UPDATE advisor_runs SET runtime_metadata=:metadata"),
            {"metadata": json.dumps({"model_inflight": True, "preserved": 1})})
    with create_checkpointer(checkpoint_engine, "run", "worker", 1) as saver:
        saved = saver.put(config, checkpoint, {"source": "input", "step": -1, "parents": {}}, {})
        saver.put_writes(saved, [("__error__", "synthetic error")], "failed-task")
        with checkpoint_engine.connect() as connection:
            assert connection.execute(text("SELECT runtime_metadata FROM advisor_runs")).scalar_one()["model_inflight"] is True
        saver.put_writes(saved, [("value", "valid")], "task-valid")
        with checkpoint_engine.connect() as connection:
            assert connection.execute(text("SELECT runtime_metadata FROM advisor_runs")).scalar_one() == {
                "model_inflight": False, "preserved": 1}
        with checkpoint_engine.begin() as connection:
            connection.execute(text("UPDATE advisor_runs SET lease_generation=2,lease_owner='new-worker'"))
        with pytest.raises(CheckpointLeaseLost):
            saver.put(config, empty_checkpoint(), {"source": "loop", "step": 0, "parents": {}}, {})
        with pytest.raises(CheckpointLeaseLost):
            saver.put_writes(saved, [("value", "stale")], "task-stale")
        with pytest.raises(CheckpointLeaseLost):
            saver.put({"configurable": {"thread_id": "other"}}, checkpoint, {}, {})
    with checkpoint_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM checkpoints")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM checkpoint_writes")).scalar_one() == 2


def test_async_graph_checkpoint_roundtrip_without_runtime_ddl(checkpoint_engine, monkeypatch):
    from app.modules.advisor.runtime.checkpoints import _PostgresSaver

    statements = []
    original = _PostgresSaver._cursor

    class TracedCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def execute(self, query, *args, **kwargs):
            statements.append(str(query))
            return self.cursor.execute(query, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    @contextmanager
    def traced_cursor(saver, **kwargs):
        with original(saver, **kwargs) as cursor:
            yield TracedCursor(cursor)

    monkeypatch.setattr(_PostgresSaver, "_cursor", traced_cursor)

    async def execute():
        graph = StateGraph(dict)
        graph.add_node("answer", lambda state: {"answer": state["question"]})
        graph.add_edge(START, "answer")
        graph.add_edge("answer", END)
        config = {"configurable": {"thread_id": "run"}}
        with create_checkpointer(checkpoint_engine, "run", "worker", 1) as saver:
            compiled = graph.compile(checkpointer=saver)
            result = await compiled.ainvoke({"question": "synthetic"}, config, durability="sync")
            assert result["answer"] == "synthetic"
        with create_checkpointer(checkpoint_engine, "run", "worker", 1) as saver:
            assert (await saver.aget_tuple(config)).checkpoint["channel_values"]["__root__"]["answer"] == "synthetic"

    asyncio.run(execute())
    assert any("INSERT INTO checkpoints" in sql for sql in statements)
    assert not any(sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP")) for sql in statements)


def test_missing_schema_is_not_created(tmp_path, postgres_url):
    engine = create_engine(postgres_url)
    try:
        with pytest.raises(CheckpointSchemaMissing):
            with create_checkpointer(engine, "run", "worker", 1):
                pass
        with engine.connect() as connection:
            assert inspect(connection).get_table_names(schema=inspect(connection).default_schema_name) == []
    finally:
        engine.dispose()
