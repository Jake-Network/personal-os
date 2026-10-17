"""Durable uploads, atomic version promotion, and bounded document parsing."""
import asyncio
import hashlib
import io
import logging
import re
from pathlib import PurePath

from pypdf import PdfReader
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.modules.database.model import Document, DocumentVersion, DocumentChunk, ContextSnapshot
from app.modules.database.model.base import utcnow
from app.modules.documents import embedding

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 500_000
MAX_CHUNKS = 500
EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}


def get_document(session, document_id):
    row = session.get(Document, document_id)
    if row is None:
        raise LookupError("document_not_found")
    return row


def latest_version(session, document_id):
    return session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                          .order_by(DocumentVersion.id.desc()).limit(1))


def item(session, document):
    latest = latest_version(session, document.id)
    return {**{key: getattr(document, key) for key in ("id", "title", "categories", "kind", "sharing_enabled",
            "application_id", "goal_id", "active_version_id", "created_at", "updated_at")},
            "latest_version_id": latest.id if latest else None, "as_of": latest.as_of if latest else None,
            "filename": latest.filename if latest else None, "status": latest.status if latest else "pending",
            "error": latest.error if latest else None}


def add_version(session, document, filename, content, as_of=None):
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if PurePath(filename).suffix.lower() not in EXTENSIONS:
        raise ValueError("supported_formats_pdf_md_txt")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("file_size_must_be_between_1_byte_and_10_mb")
    if len(filename) > 255:
        raise ValueError("filename_too_long")
    version = DocumentVersion(document_id=document.id, filename=filename, content=content,
                              content_hash=hashlib.sha256(content).hexdigest(), as_of=as_of, status="pending")
    document.updated_at = utcnow()
    session.add(version)
    session.commit()
    return item(session, document)


def parse_chunks(filename, content):
    if PurePath(filename).suffix.lower() == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError("encrypted_or_too_many_pdf_pages")
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    else:
        pages = [(None, content.decode("utf-8-sig"))]
    if sum(len(text) for _, text in pages) > MAX_TEXT:
        raise ValueError("document_text_too_large")
    result = []
    for page, text in pages:
        text = text.replace("\x00", "").strip()
        section, pending = None, ""
        def flush():
            nonlocal pending
            if pending.strip():
                result.append({"text": pending.strip(), "page": page, "section": section})
            pending = ""
        # Keep paragraphs and headings together; only oversized paragraphs split.
        for paragraph in re.split(r"\n\s*\n", text):
            for segment in re.split(r"(?m)(?=^#{1,6} )", paragraph):
                segment = segment.strip()
                if not segment:
                    continue
                if segment.startswith("#"):
                    flush()
                    section = segment.splitlines()[0].lstrip("# ")[:200]
                if pending and len(pending) + len(segment) + 2 > 1600:
                    flush()
                while len(segment) > 1600:
                    flush()
                    boundary = segment.rfind(" ", 800, 1600)
                    boundary = boundary if boundary > 0 else 1600
                    result.append({"text": segment[:boundary], "page": page, "section": section})
                    segment = segment[max(0, boundary-150):].strip()
                pending = (pending + "\n\n" + segment).strip()
        flush()
        if len(result) > MAX_CHUNKS:
            raise ValueError("too_many_document_chunks")
    if not result:
        raise ValueError("no_extractable_text_ocr_not_supported")
    return result


def recover_pending(session):
    session.execute(update(DocumentVersion).where(DocumentVersion.status == "processing")
                    .values(status="pending", error=None))
    session.commit()


async def process_one(database):
    with database.session() as session:
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.status == "pending")
                                 .order_by(DocumentVersion.id).limit(1))
        if version is None:
            return False
        version_id = version.id
        # Conditional claim also prevents two worker loops indexing the same job.
        claimed = session.execute(update(DocumentVersion).where(DocumentVersion.id == version_id,
                                  DocumentVersion.status == "pending").values(status="processing", error=None))
        session.commit()
        if not claimed.rowcount:
            return True
        filename, content = version.filename, version.content
    try:
        chunks = await asyncio.to_thread(parse_chunks, filename, content)
        vectors = await embedding.embed_texts([chunk["text"] for chunk in chunks])
        # Defense in depth for replacement providers and tests.
        embedding.validate_vectors({"model": settings.embedding_model, "embeddings": vectors}, len(chunks))
        with database.session() as session:
            version = session.get(DocumentVersion, version_id)
            if version is None or version.status != "processing":
                return True
            session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version_id))
            session.add_all([DocumentChunk(version_id=version_id, ordinal=i, embedding=vector, **chunk)
                             for i, (chunk, vector) in enumerate(zip(chunks, vectors))])
            version.status = "ready"
            version.embedding_model = settings.embedding_model
            version.embedding_dimensions = settings.embedding_dimensions
            document = session.get(Document, version.document_id)
            # A late older job must not supersede an already-ready newer version.
            if document.active_version_id is None or document.active_version_id < version_id:
                document.active_version_id = version_id
                document.updated_at = utcnow()
            session.commit()
    except asyncio.CancelledError:
        with database.session() as session:
            session.execute(update(DocumentVersion).where(DocumentVersion.id == version_id,
                            DocumentVersion.status == "processing").values(status="pending"))
            session.commit()
        raise
    except Exception as exc:
        with database.session() as session:
            version = session.get(DocumentVersion, version_id)
            if version is not None:
                version.status = "failed"
                # Store a safe error code, never arbitrary server bodies/document text.
                safe_codes = {"embedding_model_mismatch", "embedding_count_mismatch", "invalid_embedding_vector",
                              "encrypted_or_too_many_pdf_pages", "document_text_too_large",
                              "too_many_document_chunks", "no_extractable_text_ocr_not_supported"}
                version.error = str(exc) if str(exc) in safe_codes else type(exc).__name__
                session.commit()
    return True


async def process_pending(database, stop_event):
    needs_recovery = False
    while not stop_event.is_set():
        try:
            if needs_recovery:
                with database.session() as session:
                    recover_pending(session)
                needs_recovery = False
            await process_one(database)
        except SQLAlchemyError:
            # Transient database failures must not silently kill the indexing loop.
            # Avoid logging SQL parameters containing document text.
            logging.getLogger(__name__).warning("document_worker_database_unavailable")
            needs_recovery = True
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.5)
        except TimeoutError:
            pass


def delete_document(session, document_id, purge_evidence=False):
    document = get_document(session, document_id)
    if purge_evidence:
        # Snapshots are indivisible provenance packages: remove the entire affected
        # snapshot; FK SET NULL preserves the conversation without retained excerpts.
        for snapshot in session.scalars(select(ContextSnapshot)):
            citations = snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", [])
            dependencies = snapshot.payload.get("document_dependencies", [])
            if any(c.get("document_id") == document_id for c in citations + dependencies):
                session.delete(snapshot)
    session.delete(document)
    session.commit()
