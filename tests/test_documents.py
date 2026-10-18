import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.enums.context_category import Category
from app.modules.context.privacy_manager import privacy_manager
from app.modules.database import db, get_session
from app.modules.database.model import Document, DocumentVersion, DocumentChunk
from app.modules.documents import document_manager as manager, embedding, retrieval
from app.router.document_router import router

REAL_EMBED_TEXTS = embedding.embed_texts


@pytest.fixture
def documents(session, monkeypatch):
    local_settings = replace(settings, embedding_dimensions=3)
    for module in (embedding, retrieval, manager):
        monkeypatch.setattr(module, "settings", local_settings)
    async def fake_embed(texts):
        return [[1., 0., 0.] for _ in texts]
    monkeypatch.setattr(embedding, "embed_texts", fake_embed)
    monkeypatch.setattr(embedding, "embed_query", lambda text: [1., 0., 0.])
    return session


def upload(session, title="이력서", text="Python 데이터 처리 경험", categories=None):
    doc = Document(title=title, categories=categories or ["career"], kind="resume")
    session.add(doc)
    session.flush()
    manager.add_version(session, doc, "resume.md", text.encode())
    return doc


def process():
    assert asyncio.run(manager.process_one(db))


def test_upload_index_pin_and_atomic_version_replacement(documents):
    doc = upload(documents)
    process()
    documents.expire_all()
    original = doc.active_version_id
    result = retrieval.search(documents, "Python", ["career"], [doc.id])
    assert result.data["citations"][0]["version_id"] == original
    manager.add_version(documents, doc, "new.txt", "신규 경력 Java".encode())
    assert retrieval.search(documents, "Python", ["career"], [doc.id]).data["citations"][0]["version_id"] == original
    process()
    documents.expire_all()
    assert doc.active_version_id != original
    assert retrieval.search(documents, "Java", ["career"], [doc.id]).data["citations"][0]["text"] == "신규 경력 Java"


def test_global_privacy_blocks_multitopic_and_pinned_docs(documents):
    doc = upload(documents, categories=["career", "financial"])
    process()
    documents.expire_all()
    privacy_manager.set_excluded(documents, [Category.FINANCIAL])
    assert retrieval.search(documents, "Python", ["career"], [doc.id]).data["citations"] == []
    privacy_manager.set_excluded(documents, [])
    doc.sharing_enabled = False
    documents.commit()
    assert retrieval.search(documents, "Python", ["career"], [doc.id]).data["citations"] == []


def test_pinned_comparison_covers_each_document(documents):
    docs = [upload(documents, title=str(i), text=("Python " * 1000)) for i in range(2)]
    process()
    process()
    documents.expire_all()
    result = retrieval.search(documents, "Python", ["career"], [d.id for d in docs])
    assert {c["document_id"] for c in result.data["citations"]} == {d.id for d in docs}


def test_failed_embedding_retry_and_recovery(documents, monkeypatch):
    doc = upload(documents)
    async def broken(texts):
        raise ValueError("invalid_embedding_vector")
    monkeypatch.setattr(embedding, "embed_texts", broken)
    process()
    version = manager.latest_version(documents, doc.id)
    assert version.status == "failed"
    assert doc.active_version_id is None
    # A legacy `processing` job without a lease is reclaimed by the next claim.
    version.status = "processing"
    documents.commit()
    assert manager._claim(db, "successor")[0] == version.id


def test_parser_and_vector_validation(documents):
    assert manager.parse_chunks("test.md", "# Heading\n한국어 문서".encode())[0]["section"] == "Heading"
    with pytest.raises(ValueError, match="no_extractable"):
        manager.parse_chunks("test.txt", b" ")
    for vector in ([0., 0., 0.], [1., float("nan"), 0.], [1., 0.], [True, 1., 0.]):
        with pytest.raises(ValueError):
            embedding.validate_vectors({"model": settings.embedding_model, "embeddings": [vector]}, 1)
    with pytest.raises(ValueError, match="model_mismatch"):
        embedding.validate_vectors({"model": "other", "embeddings": [[1., 0., 0.]]}, 1)


def test_api_upload_metadata_retry_source_and_cascade_delete(documents):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: documents
    with TestClient(app) as client:
        invalid = client.post("/api/documents", data={"title": "x", "categories": '["career"]'}, files={"file": ("bad.exe", b"bad")})
        assert invalid.status_code == 422
        assert not list(documents.scalars(select(Document)))
        response = client.post("/api/documents", data={"title": "이력서", "categories": '["career"]'}, files={"file": ("resume.md", "Python 경력".encode())})
        assert response.status_code == 201
        document_id = response.json()["id"]
        assert client.post(f"/api/documents/{document_id}/retry").status_code == 409
        process()
        documents.expire_all()
        chunk_id = documents.scalar(select(DocumentChunk.id))
        assert client.get(f"/api/documents/chunks/{chunk_id}").status_code == 200
        assert client.patch(f"/api/documents/{document_id}", json={"sharing_enabled": False}).status_code == 200
        assert client.get(f"/api/documents/chunks/{chunk_id}").status_code == 404
        assert client.delete(f"/api/documents/{document_id}").status_code == 204
        assert documents.scalar(select(DocumentChunk)) is None
        assert documents.scalar(select(DocumentVersion)) is None


def test_embedding_unavailable_never_returns_misleading_sources(documents, monkeypatch):
    doc = upload(documents)
    process()
    documents.expire_all()
    def unavailable(text):
        raise RuntimeError("offline")
    monkeypatch.setattr(embedding, "embed_query", unavailable)
    result = retrieval.search(documents, "Python", ["career"], [doc.id])
    assert result.data["citations"] == []
    assert result.flags[0]["code"] == "document_embedding_unavailable"


def test_empty_pin_list_uses_auto_and_mismatched_model_pin_is_flagged(documents):
    first = upload(documents)
    second = upload(documents, title="old model")
    process()
    process()
    documents.expire_all()
    assert retrieval.search(documents, "Python", ["career"], []).data["citations"]
    version = documents.get(DocumentVersion, second.active_version_id)
    version.embedding_model = "old-model"
    documents.commit()
    result = retrieval.search(documents, "Python", ["career"], [first.id, second.id])
    assert {c["document_id"] for c in result.data["citations"]} == {first.id}
    assert any(f.get("document_ids") == [second.id] for f in result.flags)


def test_bad_pdf_fails_job_and_preserves_old_version(documents):
    doc = upload(documents)
    process()
    documents.expire_all()
    old_version = doc.active_version_id
    manager.add_version(documents, doc, "broken.pdf", b"this is not a pdf")
    process()
    documents.expire_all()
    assert manager.latest_version(documents, doc.id).status == "failed"
    assert doc.active_version_id == old_version


def test_postgresql_vector_search_and_migration_parity(monkeypatch):
    """Opt in only with a disposable database; use a random isolated schema."""
    import os
    import uuid
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from app.modules.database.database import Database

    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL must point to a disposable PostgreSQL database")
    local_settings = replace(settings, embedding_dimensions=3)
    for module in (embedding, retrieval, manager):
        monkeypatch.setattr(module, "settings", local_settings)
    async def fake_embed(texts):
        return [[1., 0., 0.] for _ in texts]
    monkeypatch.setattr(embedding, "embed_texts", fake_embed)
    monkeypatch.setattr(embedding, "embed_query", lambda text: [1., 0., 0.])
    schema = "rag_test_" + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            config.attributes["version_table_schema"] = schema
            command.upgrade(config, "head")
            command.check(config)
            database = Database()
            database.engine = engine
            database._sessionmaker = sessionmaker(bind=connection, expire_on_commit=False)
            with database.session() as session:
                doc = upload(session)
                asyncio.run(manager.process_one(database))
                session.expire_all()
                results = retrieval.search(session, "Python", ["career"], [doc.id])
                assert results.data["citations"][0]["document_id"] == doc.id
                manager.delete_document(session, doc.id)
                assert session.scalar(select(DocumentChunk)) is None
            connection.commit()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_embedding_http_batches_inputs_and_validates_provider_response(documents, monkeypatch):
    import httpx
    import json
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"model": settings.embedding_model,
                                       "embeddings": [[1., 0., 0.] for _ in body["input"]]})
    client_type = httpx.AsyncClient
    monkeypatch.setattr(embedding.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    vectors = asyncio.run(REAL_EMBED_TEXTS(["문서 조각"] * 35))
    assert len(vectors) == 35
    assert [len(call["input"]) for call in calls] == [16, 16, 3]
    assert all(call["truncate"] is False for call in calls)


def test_deleted_ids_never_alias_new_evidence(documents):
    doc = upload(documents)
    process()
    documents.expire_all()
    old_ids = (doc.id, doc.active_version_id, documents.scalar(select(DocumentChunk.id)))
    manager.delete_document(documents, doc.id)
    replacement = upload(documents, title="다른 문서")
    process()
    documents.expire_all()
    new_ids = (replacement.id, replacement.active_version_id, documents.scalar(select(DocumentChunk.id)))
    assert all(new > old for old, new in zip(old_ids, new_ids))


def test_pdf_text_page_references_blank_and_encrypted(documents):
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    def make_pdf(text=None, encrypted=False):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
        if encrypted:
            writer.encrypt("secret")
        result = BytesIO()
        writer.write(result)
        return result.getvalue()

    chunks = manager.parse_chunks("resume.pdf", make_pdf("Python platform experience"))
    assert len(chunks) == 1
    assert chunks[0]["page"] == 1
    assert "Python platform experience" in chunks[0]["text"]
    with pytest.raises(ValueError, match="no_extractable_text_ocr_not_supported"):
        manager.parse_chunks("scanned.pdf", make_pdf())
    with pytest.raises(ValueError, match="encrypted_or_too_many_pdf_pages"):
        manager.parse_chunks("encrypted.pdf", make_pdf("private", True))


def test_purge_evidence_removes_direct_and_transitive_snapshots(documents):
    from app.modules.database.model import ContextSnapshot
    doc = upload(documents)
    for ident, payload in (("direct", {"data": {"search_documents": {"citations": [{"document_id": doc.id, "text": "private"}]}}}),
                           ("derived", {"document_dependencies": [{"document_id": doc.id}]}),
                           ("unrelated", {"data": {}})):
        documents.add(ContextSnapshot(id=ident, context_categories=["career"], excluded_categories=[],
                                      record_references=[], source_updated_at={}, data_quality_flags=[],
                                      payload=payload, content_hash=ident))
    documents.commit()
    from app.modules.documents.evidence import record_references
    for snapshot in documents.scalars(select(ContextSnapshot)):
        record_references(documents, snapshot)
    manager.delete_document(documents, doc.id, purge_evidence=True)
    assert {snapshot.id for snapshot in documents.scalars(select(ContextSnapshot))} == {"unrelated"}


def test_background_worker_recovers_transient_database_failure(monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError

    async def scenario():
        database = object()
        stop = asyncio.Event()
        calls = []
        async def process_once(received_database):
            assert received_database is database
            calls.append("process")
            if len(calls) == 1:
                raise OperationalError("SELECT private_text", {"document": "private-content"}, Exception("offline"))
            stop.set()
            return True
        monkeypatch.setattr(manager, "process_one", process_once)
        monkeypatch.setattr(manager, "POLL_SECONDS", .01)
        await asyncio.wait_for(manager.process_pending(database, stop), timeout=1)
        assert calls == ["process", "process"]
    asyncio.run(scenario())
    assert "document_worker_database_unavailable" in caplog.text
    assert "private-content" not in caplog.text
    assert "SELECT private_text" not in caplog.text


@pytest.mark.parametrize("dimensions", [3, 4])
def test_reindex_changed_model_preserves_old_version_and_source(documents, monkeypatch, dimensions):
    doc = upload(documents)
    process()
    documents.expire_all()
    original = doc.active_version_id
    original_chunks = list(documents.scalars(select(DocumentChunk).where(DocumentChunk.version_id == original)))
    changed = replace(manager.settings, embedding_model="replacement-model", embedding_dimensions=dimensions)
    for module in (embedding, retrieval, manager):
        monkeypatch.setattr(module, "settings", changed)
    async def updated_embed(texts):
        return [[1.] + [0.] * (dimensions - 1) for _ in texts]
    monkeypatch.setattr(embedding, "embed_texts", updated_embed)
    monkeypatch.setattr(embedding, "embed_query", lambda text: [1.] + [0.] * (dimensions - 1))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: documents
    with TestClient(app) as client:
        response = client.post(f"/api/documents/{doc.id}/reindex")
        assert response.status_code == 202
        assert response.json()["status"] == "pending"
        assert response.json()["active_version_id"] == original
        assert client.post(f"/api/documents/{doc.id}/reindex").status_code == 409
    latest = manager.latest_version(documents, doc.id)
    assert latest.content == documents.get(DocumentVersion, original).content
    process()
    documents.expire_all()
    assert doc.active_version_id == latest.id != original
    assert latest.embedding_model == "replacement-model"
    assert latest.embedding_dimensions == dimensions
    assert {c.id for c in documents.scalars(select(DocumentChunk).where(DocumentChunk.version_id == original))} == {c.id for c in original_chunks}
    assert retrieval.search(documents, "Python", ["career"], [doc.id]).data["citations"]


def test_claim_recovery_fences_old_worker_and_keeps_live_lease(documents):
    from datetime import timedelta
    from sqlalchemy import update
    from app.modules.database.model.base import utcnow
    doc = upload(documents)
    claim = manager._claim(db, "worker-one")
    assert claim
    assert manager._claim(db, "worker-two") is None
    documents.expire_all()
    version = manager.latest_version(documents, doc.id)
    assert version.status == "processing" and version.lease_owner == "worker-one"
    documents.execute(update(DocumentVersion).where(DocumentVersion.id == version.id)
                      .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
    documents.commit()
    assert manager._claim(db, "worker-two")[0] == version.id
    manager._finish(db, version.id, "worker-one", [{"text": "stale", "page": None, "section": None}], [[1.,0.,0.]])
    documents.expire_all()
    assert version.status == "processing" and version.lease_owner == "worker-two"
    assert not list(documents.scalars(select(DocumentChunk)))
    manager._finish(db, version.id, "worker-two", [{"text": "current", "page": None, "section": None}], [[1.,0.,0.]])
    documents.expire_all()
    assert version.status == "ready" and doc.active_version_id == version.id


def test_worker_cancellation_releases_only_owned_job(documents, monkeypatch):
    doc = upload(documents)
    async def scenario():
        started = asyncio.Event()
        async def blocked(texts):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(embedding, "embed_texts", blocked)
        task = asyncio.create_task(manager.process_one(db))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    documents.expire_all()
    version = manager.latest_version(documents, doc.id)
    assert version.status == "pending" and version.lease_owner is None
    assert doc.active_version_id is None


def test_worker_idle_notification_and_database_work_do_not_block_event_loop(monkeypatch):
    import threading
    import time
    async def scenario():
        stop = asyncio.Event()
        entered = threading.Event()
        release = threading.Event()
        claims = []
        def slow_claim(database, owner):
            claims.append(owner)
            entered.set()
            assert release.wait(timeout=2)
            return None
        monkeypatch.setattr(manager, "_claim", slow_claim)
        worker = asyncio.create_task(manager.process_pending(object(), stop))
        try:
            deadline = time.monotonic() + 1
            while not entered.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(.005)
            # If claim ran on the event loop, release could never be set in time.
            release.set()
            await asyncio.sleep(.65)
            assert len(claims) == 1  # no half-second idle polling
            await asyncio.to_thread(manager.notify_workers)
            deadline = time.monotonic() + 1
            while len(claims) < 2:
                assert time.monotonic() < deadline
                await asyncio.sleep(.005)
            stop.set()
            await asyncio.wait_for(worker, timeout=.5)
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())


def test_postgresql_worker_leases_concurrent_recovery_and_stale_completion(monkeypatch):
    """Independent connections prove claim fencing against real PostgreSQL row locks."""
    import os
    import uuid
    from datetime import timedelta
    from sqlalchemy import create_engine, text, update
    from sqlalchemy.orm import sessionmaker
    from app.modules.database.database import Database
    from app.modules.database.model import Base
    from app.modules.database.model.base import utcnow

    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL must point to a disposable PostgreSQL database")
    schema = "rag_workers_" + uuid.uuid4().hex
    admin = create_engine(url)
    engine = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f'-csearch_path={schema},public'})
        # checkfirst would see same-named tables in public (also on search_path) and skip creating them here.
        Base.metadata.create_all(engine, checkfirst=False)
        database = Database()
        database.engine = engine
        database._sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)
        local_settings = replace(settings, embedding_dimensions=3)
        monkeypatch.setattr(manager, "settings", local_settings)
        monkeypatch.setattr(embedding, "settings", local_settings)
        monkeypatch.setattr(manager, "HEARTBEAT_SECONDS", .05)
        monkeypatch.setattr(manager, "LEASE_SECONDS", 3)
        with database.session() as session:
            doc = upload(session)
            document_id = doc.id
            version_id = manager.latest_version(session, document_id).id

        async def scenario():
            started = asyncio.Event()
            finish = asyncio.Event()
            calls = []
            async def blocked_embed(texts):
                calls.append(texts)
                started.set()
                await finish.wait()
                return [[1., 0., 0.] for _ in texts]
            monkeypatch.setattr(embedding, "embed_texts", blocked_embed)
            workers = [asyncio.create_task(manager.process_one(database)) for _ in range(2)]
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                # A claim from a second connection must not take over the live owner's job.
                def recover():
                    with database.session() as session:
                        owner = session.get(DocumentVersion, version_id).lease_owner
                    assert manager._claim(database, "intruder") is None
                    with database.session() as session:
                        version = session.get(DocumentVersion, version_id)
                        assert version.status == "processing" and version.lease_owner == owner
                        return owner
                owner = await asyncio.to_thread(recover)
                # More than the original lease: heartbeats must keep ownership alive.
                await asyncio.sleep(3.2)
                assert await asyncio.to_thread(recover) == owner
                assert await manager.process_one(database) is False
                assert len(calls) == 1
                finish.set()
                await asyncio.wait_for(asyncio.gather(*workers), timeout=3)
            finally:
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
        asyncio.run(scenario())
        with database.session() as session:
            assert session.get(DocumentVersion, version_id).status == "ready"
            assert len(list(session.scalars(select(DocumentChunk)))) == 1
            # Simulate an owner that died after claiming, with a real expired lease.
            session.execute(update(DocumentVersion).where(DocumentVersion.id == version_id)
                            .values(status="processing", lease_owner="abandoned",
                                    lease_expires_at=utcnow() - timedelta(seconds=1)))
            session.commit()
        assert manager._claim(database, "successor")[0] == version_id
        manager._finish(database, version_id, "abandoned", error="old_worker_failed")
        with database.session() as session:
            assert session.get(DocumentVersion, version_id).lease_owner == "successor"
        chunks = [{"text": "successor text", "page": None, "section": None}]
        manager._finish(database, version_id, "successor", chunks, [[1., 0., 0.]])
        manager._finish(database, version_id, "abandoned", chunks, [[1., 0., 0.]])
        with database.session() as session:
            assert session.get(DocumentVersion, version_id).status == "ready"
            rows = list(session.scalars(select(DocumentChunk)))
            assert len(rows) == 1 and rows[0].text == "successor text"
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_search_keeps_distinct_adjacent_markdown_sections(documents):
    doc = upload(documents, text="# 오로라 제안\n서울 연봉 9000\n\n# 바다 제안\n부산 연봉 10000")
    process()
    documents.expire_all()
    result = retrieval.search(documents, "오로라 바다 제안 비교", ["career"])
    assert {row["section"] for row in result.data["citations"]} == {"오로라 제안", "바다 제안"}
    assert {row["document_id"] for row in result.data["citations"]} == {doc.id}


def test_search_keeps_independent_paragraphs_under_same_heading(documents):
    first = "서울 지원 조건 " * 100
    second = "부산 지원 조건 " * 100
    doc = upload(documents, text=f"# 지원 비교\n{first}\n\n{second}")
    process()
    documents.expire_all()
    chunks = documents.scalars(select(DocumentChunk).where(DocumentChunk.version_id == doc.active_version_id)
                               .order_by(DocumentChunk.ordinal)).all()
    assert len(chunks) == 2
    assert {chunk.section for chunk in chunks} == {"지원 비교"}
    result = retrieval.search(documents, "서울 부산 지원 비교", ["career"])
    assert {row["chunk_id"] for row in result.data["citations"]} == {chunk.id for chunk in chunks}


def test_search_suppresses_actual_long_paragraph_overlap(documents):
    doc = upload(documents, text="# 긴 경력\n" + "서비스 운영 성과 " * 180)
    process()
    documents.expire_all()
    chunks = documents.scalars(select(DocumentChunk).where(DocumentChunk.version_id == doc.active_version_id)
                               .order_by(DocumentChunk.ordinal)).all()
    assert len(chunks) == 2
    assert chunks[1].text.startswith(chunks[0].text[-150:].strip())
    result = retrieval.search(documents, "서비스 운영 성과", ["career"])
    assert len(result.data["citations"]) == 1


def test_transient_embedding_failure_backs_off_then_succeeds(documents, monkeypatch):
    import httpx

    doc = upload(documents)
    calls = []

    async def flaky(texts):
        calls.append(len(texts))
        if len(calls) == 1:
            raise httpx.ConnectError("embedding server still starting")
        return [[1., 0., 0.] for _ in texts]
    monkeypatch.setattr(embedding, "embed_texts", flaky)
    process()
    documents.expire_all()
    version = manager.latest_version(documents, doc.id)
    assert (version.status, version.error, version.attempts) == ("pending", "ConnectError", 1)
    assert version.retry_after is not None
    assert asyncio.run(manager.process_one(db)) is False  # not due yet
    version.retry_after = None
    documents.commit()
    process()
    documents.expire_all()
    assert manager.latest_version(documents, doc.id).status == "ready"


def test_transient_failures_stop_after_max_attempts(documents, monkeypatch):
    import httpx

    doc = upload(documents)

    async def down(texts):
        raise httpx.ReadTimeout("no answer")
    monkeypatch.setattr(embedding, "embed_texts", down)
    for _ in range(manager.MAX_ATTEMPTS):
        process()
        documents.expire_all()
        version = manager.latest_version(documents, doc.id)
        version.retry_after = None
        documents.commit()
    assert (version.status, version.attempts) == ("failed", manager.MAX_ATTEMPTS)


def test_job_that_keeps_crashing_the_worker_is_given_up(documents):
    from datetime import timedelta
    from app.modules.database.model.base import utcnow

    doc = upload(documents)
    version = manager.latest_version(documents, doc.id)
    # Each crash leaves the job `processing` with an expired lease after one more claim.
    version.status, version.attempts = "processing", manager.MAX_ATTEMPTS
    version.lease_expires_at = utcnow() - timedelta(seconds=1)
    documents.commit()
    other = upload(documents, title="다른 문서")
    process()  # gives up on the crash-looping job instead of claiming it again
    process()
    documents.expire_all()
    assert manager.latest_version(documents, doc.id).error == "indexing_attempts_exhausted"
    assert manager.latest_version(documents, other.id).status == "ready"


def test_worker_survives_unexpected_errors(monkeypatch, caplog):
    async def scenario():
        stop = asyncio.Event()
        calls = []
        async def process_once(_database):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("adapter bug")
            stop.set()
            return True
        monkeypatch.setattr(manager, "process_one", process_once)
        monkeypatch.setattr(manager, "POLL_SECONDS", .01)
        await asyncio.wait_for(manager.process_pending(object(), stop), timeout=1)
        assert len(calls) == 2
    asyncio.run(scenario())
    assert "document_worker_iteration_failed" in caplog.text


def test_retry_resets_attempts_and_handles_missing_versions(documents):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: documents
    client = TestClient(app)
    doc = upload(documents)
    version = manager.latest_version(documents, doc.id)
    version.status, version.attempts, version.error = "failed", manager.MAX_ATTEMPTS, "indexing_attempts_exhausted"
    documents.commit()
    assert client.post(f"/api/documents/{doc.id}/retry").status_code == 200
    documents.expire_all()
    assert (version.status, version.attempts) == ("pending", 0)
    empty = Document(title="빈 문서", categories=["career"], kind="reference")
    documents.add(empty)
    documents.commit()
    assert client.post(f"/api/documents/{empty.id}/retry").status_code == 404
