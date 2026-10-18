from datetime import UTC, datetime, timedelta

import pytest
from langgraph.store.base import GetOp, PutOp

from app.modules.advisor.memory_store import ConfirmedMemoryStore
from app.modules.database.model import MemoryRevision, PersonalMemory


def memory(session, kind="constraint", **revision_fields):
    row = PersonalMemory(kind=kind, content="합성 제약", status="confirmed", source="user")
    session.add(row)
    session.flush()
    revision = MemoryRevision(memory_id=row.id, revision=1, kind=kind,
        content=row.content, status="confirmed", **revision_fields)
    session.add(revision)
    session.commit()
    return row, revision


def test_store_keeps_mandatory_constraints_and_rechecks_revocation(session):
    row, revision = memory(session)
    store = ConfirmedMemoryStore(session)
    assert [i.key for i in store.search(store.namespace, query="다른 주제", limit=0)] == [str(row.id)]
    assert store.get(store.namespace, str(row.id)).value["revision_id"] == revision.id
    revision.external_allowed = False
    session.commit()
    assert store.get(store.namespace, str(row.id)) is None
    assert store.search(store.namespace, query="합성") == []


def test_store_validity_and_unconfirmed_memories_are_not_facts(session):
    row, _ = memory(session, valid_until=datetime.now(UTC) - timedelta(days=1))
    store = ConfirmedMemoryStore(session)
    assert store.get(store.namespace, str(row.id)) is None
    row.status = "proposed"
    session.commit()
    assert store.search(store.namespace) == []


def test_store_rejects_an_entire_mixed_write_batch(session):
    row, _ = memory(session)
    store = ConfirmedMemoryStore(session)
    with pytest.raises(PermissionError):
        store.batch([GetOp(store.namespace, str(row.id)), PutOp(store.namespace, str(row.id), {"content": "overwrite"})])
    assert session.get(PersonalMemory, row.id).content == "합성 제약"


def test_store_get_preserves_request_scope(session):
    at = datetime.now(UTC)
    row, revision = memory(session, scope="합성회사", valid_from=at - timedelta(days=2))
    store = ConfirmedMemoryStore(session, request_query="합성회사 지원 계획", at=at)
    assert store.get(store.namespace, str(row.id)).value['revision_id'] == revision.id
    store.request_query = "다른회사 지원 계획"
    assert store.get(store.namespace, str(row.id)) is None
