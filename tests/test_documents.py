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
    version.status = "processing"
    documents.commit()
    manager.recover_pending(documents)
    documents.expire_all()
    assert version.status == "pending"


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
    manager.delete_document(documents, doc.id, purge_evidence=True)
    assert {snapshot.id for snapshot in documents.scalars(select(ContextSnapshot))} == {"unrelated"}


def test_background_worker_recovers_transient_database_failure(monkeypatch, caplog):
    from contextlib import contextmanager
    from sqlalchemy.exc import OperationalError

    class FakeDatabase:
        def __init__(self):
            self.sessions = []

        @contextmanager
        def session(self):
            session = object()
            self.sessions.append(session)
            yield session

    async def scenario():
        database = FakeDatabase()
        stop = asyncio.Event()
        calls, recovered = [], []

        async def process_once(received_database):
            assert received_database is database
            calls.append("process")
            if len(calls) == 1:
                raise OperationalError("SELECT private_text", {"document": "private-content"}, Exception("offline"))
            assert recovered == database.sessions
            assert len(recovered) == 1
            stop.set()
            return True

        def recover(session):
            recovered.append(session)

        monkeypatch.setattr(manager, "process_one", process_once)
        monkeypatch.setattr(manager, "recover_pending", recover)
        await asyncio.wait_for(manager.process_pending(database, stop), timeout=3)
        assert calls == ["process", "process"]
        assert len(database.sessions) == 1

    asyncio.run(scenario())
    assert "document_worker_database_unavailable" in caplog.text
    assert "private-content" not in caplog.text
    assert "SELECT private_text" not in caplog.text
