"""Official LangGraph savers with application lease fencing and no runtime DDL.

Checkpoint transactions are separate from application result transactions. Every saver
write locks and checks the same run row until commit, including pending task writes.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from sqlalchemy import inspect, text, bindparam


class CheckpointLeaseLost(RuntimeError):
    pass


class CheckpointSchemaMissing(RuntimeError):
    pass


_successful_node_writes = ContextVar("successful_checkpoint_node_writes", default=False)


class _PostgresSaver(PostgresSaver):
    def __init__(self, conn, binding):
        super().__init__(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=None))
        self.binding = binding

    def setup(self):
        raise CheckpointSchemaMissing("체크포인트 스키마는 명시적인 DB 업그레이드로 생성해야 합니다.")

    @contextmanager
    def _cursor(self, *, pipeline=False):
        # Do not pipeline the ownership test: it must finish before any write.
        # Row lock and saver writes share this transaction, including blob writes.
        with self.lock, self.conn.transaction():
            with self.conn.cursor(binary=True, row_factory=dict_row) as cur:
                if pipeline:
                    cur.execute(
                        "UPDATE advisor_runs SET lease_generation=lease_generation "
                        "WHERE id=%s AND lease_owner=%s AND lease_generation=%s "
                        "AND status='running' AND lease_until > %s",
                        (*self.binding, datetime.now(UTC)),
                    )
                    if cur.rowcount != 1:
                        raise CheckpointLeaseLost("상담 실행 소유권이 변경되거나 만료되었습니다.")
                yield cur
                if pipeline and _successful_node_writes.get():
                    cur.execute("UPDATE advisor_runs SET runtime_metadata="
                        "jsonb_set(runtime_metadata::jsonb,'{model_inflight}','false'::jsonb)::json WHERE id=%s",
                        (self.binding[0],))


class RunCheckpointer(BaseCheckpointSaver):
    """Run-bound async facade over the pinned official synchronous savers.

    Small local storage operations finish before yielding to the event loop. No
    background checkpoint can outlive the surrounding run connection.
    """
    def __init__(self, saver, run_id):
        super().__init__(serde=saver.serde)
        self.saver = saver
        self.run_id = run_id

    def with_allowlist(self, extra_allowlist):
        # Reads are delegated to the underlying saver. Cloning only this
        # facade's serde would leave its actual deserializer unchanged.
        return RunCheckpointer(self.saver.with_allowlist(extra_allowlist), self.run_id)

    def _check(self, config):
        if config is None or str(config.get("configurable", {}).get("thread_id")) != self.run_id:
            raise CheckpointLeaseLost("다른 상담 실행의 체크포인트에 접근할 수 없습니다.")

    def get_tuple(self, config):
        self._check(config)
        return self.saver.get_tuple(config)

    def list(self, config, **kwargs):
        self._check(config)
        return self.saver.list(config, **kwargs)

    def put(self, config, checkpoint, metadata, new_versions):
        self._check(config)
        return self.saver.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        self._check(config)
        # Model nodes execute serially; fan-out nodes contain local reads only.
        # A successful node's durable pending output proves its external call need
        # not be repeated. Errors and interrupts leave the ambiguous-call marker.
        token = _successful_node_writes.set(bool(writes) and not any(
            channel in {"__error__", "__interrupt__"} for channel, _ in writes))
        try:
            return self.saver.put_writes(config, writes, task_id, task_path)
        finally:
            _successful_node_writes.reset(token)

    def get_next_version(self, current, channel):
        return self.saver.get_next_version(current, channel)

    async def aget_tuple(self, config):
        return self.get_tuple(config)

    async def alist(self, config, **kwargs):
        for value in self.list(config, **kwargs):
            yield value

    async def aput(self, config, checkpoint, metadata, new_versions):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return self.put_writes(config, writes, task_id, task_path)


@contextmanager
def create_checkpointer(engine, run_id: str, owner: str, generation: int):
    """Use an existing engine without creating a database or running saver setup."""
    required = {
        "checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
    from app.modules.database.legacy_adoption import inspection_schema
    with engine.connect() as connection:
        existing = set(inspect(connection).get_table_names(schema=inspection_schema(connection)))
    if not required.issubset(existing):
        raise CheckpointSchemaMissing("체크포인트 스키마 업그레이드가 필요합니다.")
    connection = engine.raw_connection()
    try:
        raw = connection.driver_connection
        binding = (run_id, owner, generation)
        saver = _PostgresSaver(raw, binding)
        yield RunCheckpointer(saver, run_id)
    finally:
        connection.close()


def run_checkpointer(database, run_id: str, owner: str, generation: int):
    return create_checkpointer(database.engine, run_id, owner, generation)


def delete_run_checkpoints(session, run_ids):
    """Delete derived graph data within the caller's authorized deletion transaction."""
    if not run_ids:
        return
    tables = (
        "checkpoints", "checkpoint_blobs", "checkpoint_writes")
    from app.modules.database.legacy_adoption import inspection_schema
    connection = session.connection()
    existing = set(inspect(connection).get_table_names(schema=inspection_schema(connection)))
    for table in tables:
        if table in existing:
            statement = text(f"DELETE FROM {table} WHERE thread_id IN :ids").bindparams(bindparam("ids", expanding=True))
            session.execute(statement, {"ids": list(run_ids)})
