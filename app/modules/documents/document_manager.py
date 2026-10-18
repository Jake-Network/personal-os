"""Durable uploads, atomic version promotion, and bounded document parsing."""
import asyncio
import hashlib
import io
import logging
import re
import threading
from contextlib import suppress
from datetime import timedelta
from uuid import uuid4
from pathlib import PurePath

import httpx
from pypdf import PdfReader
from sqlalchemy import delete, select, update, or_, and_
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.modules.database.model import Document, DocumentVersion, DocumentChunk
from app.modules.database.model.base import utcnow
from app.modules.documents import embedding

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 500_000
MAX_CHUNKS = 500
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
POLL_SECONDS = 15
MAX_ATTEMPTS = 4
RETRY_BASE_SECONDS = 30
_worker_signals = set()
_signal_lock = threading.Lock()


def notify_workers():
    """Safe from sync request threads; idle workers hold no executor threads."""
    with _signal_lock:
        for loop, event in _worker_signals:
            if not loop.is_closed():
                loop.call_soon_threadsafe(event.set)


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
    notify_workers()
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


def _expired():
    return or_(DocumentVersion.lease_expires_at.is_(None), DocumentVersion.lease_expires_at <= utcnow())


def _eligible():
    now = utcnow()
    return or_(and_(DocumentVersion.status == "pending",
                    or_(DocumentVersion.retry_after.is_(None), DocumentVersion.retry_after <= now)),
               and_(DocumentVersion.status == "processing", _expired()))


def _claim(database, owner):
    with database.session() as session:
        eligible = _eligible()
        version_id = session.scalar(select(DocumentVersion.id).where(eligible)
                                    .order_by(DocumentVersion.id).limit(1))
        if version_id is None:
            return None
        attempts = session.scalar(select(DocumentVersion.attempts).where(DocumentVersion.id == version_id)) or 0
        if attempts >= MAX_ATTEMPTS:
            # A job that keeps killing or hanging the worker (its lease expired each time) must not
            # be claimed forever and starve the others.
            session.execute(update(DocumentVersion).where(DocumentVersion.id == version_id, eligible)
                            .values(status="failed", error="indexing_attempts_exhausted", lease_owner=None,
                                    lease_expires_at=None, retry_after=None))
            session.commit()
            return False
        claimed = session.execute(update(DocumentVersion).where(DocumentVersion.id == version_id, eligible)
                                  .values(status="processing", error=None, lease_owner=owner,
                                          lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS),
                                          attempts=attempts + 1, retry_after=None))
        if not claimed.rowcount:
            session.rollback()
            return False
        version = session.get(DocumentVersion, version_id)
        claim = version_id, version.filename, version.content, attempts + 1
        session.commit()
        return claim


def _owned(version_id, owner):
    return (DocumentVersion.id == version_id, DocumentVersion.status == "processing",
            DocumentVersion.lease_owner == owner, DocumentVersion.lease_expires_at > utcnow())


def _renew(database, version_id, owner):
    with database.session() as session:
        result = session.execute(update(DocumentVersion).where(*_owned(version_id, owner))
                                 .values(lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS)))
        session.commit()
        return bool(result.rowcount)


async def _heartbeat(database, version_id, owner):
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        if not await asyncio.to_thread(_renew, database, version_id, owner):
            return


def _finish(database, version_id, owner, chunks=None, vectors=None, error=None, cancelled=False,
            retry_after=None):
    with database.session() as session:
        # This UPDATE locks/fences the row until chunks and promotion commit together.
        values = dict(status="pending" if cancelled or retry_after else "failed" if error else "ready",
                      error=error, lease_owner=None, lease_expires_at=None, retry_after=retry_after)
        if cancelled:  # shutdown is not the job's fault: give the attempt back
            values["attempts"] = DocumentVersion.attempts - 1
        if chunks is not None:
            values.update(embedding_model=settings.embedding_model,
                          embedding_dimensions=settings.embedding_dimensions)
        result = session.execute(update(DocumentVersion).where(*_owned(version_id, owner)).values(**values))
        if not result.rowcount:
            session.rollback()
            return
        if chunks is not None:
            session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version_id))
            session.add_all([DocumentChunk(version_id=version_id, ordinal=i, embedding=vector, **chunk)
                             for i, (chunk, vector) in enumerate(zip(chunks, vectors))])
            version = session.get(DocumentVersion, version_id)
            session.execute(update(Document).where(Document.id == version.document_id,
                            or_(Document.active_version_id.is_(None), Document.active_version_id < version_id))
                            .values(active_version_id=version_id, updated_at=utcnow()))
        session.commit()


async def process_one(database):
    owner = str(uuid4())
    claiming = asyncio.create_task(asyncio.to_thread(_claim, database, owner))
    try:
        claim = await asyncio.shield(claiming)
    except asyncio.CancelledError:
        claim = await claiming
        if claim:
            await asyncio.to_thread(_finish, database, claim[0], owner, cancelled=True)
        raise
    if claim is None:
        return False
    if claim is False:
        return True
    version_id, filename, content, attempt = claim
    heartbeat = asyncio.create_task(_heartbeat(database, version_id, owner))
    try:
        chunks = await asyncio.to_thread(parse_chunks, filename, content)
        vectors = await embedding.embed_texts([chunk["text"] for chunk in chunks])  # validated per batch
        if heartbeat.done():
            heartbeat.result()
        await asyncio.to_thread(_finish, database, version_id, owner, chunks, vectors)
    except asyncio.CancelledError:
        await asyncio.to_thread(_finish, database, version_id, owner, cancelled=True)
        raise
    except Exception as exc:
        safe_codes = {"embedding_model_mismatch", "embedding_count_mismatch", "invalid_embedding_vector",
                      "encrypted_or_too_many_pdf_pages", "document_text_too_large",
                      "too_many_document_chunks", "no_extractable_text_ocr_not_supported"}
        error = str(exc) if str(exc) in safe_codes else type(exc).__name__
        retry_after = None
        if _transient(exc) and attempt < MAX_ATTEMPTS:
            # The embedding server may still be starting or loading its model: back off, then retry.
            retry_after = utcnow() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** (attempt - 1))
        await asyncio.to_thread(_finish, database, version_id, owner, error=error, retry_after=retry_after)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
    return True


def _transient(exc):
    """Errors that a later attempt can succeed past: transport failures, timeouts, 429 and 5xx."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _next_retry_delay(database):
    with database.session() as session:
        due = session.scalar(select(DocumentVersion.retry_after).where(
            DocumentVersion.status == "pending", DocumentVersion.retry_after.is_not(None))
            .order_by(DocumentVersion.retry_after).limit(1))
    return None if due is None else max(0.0, (due - utcnow()).total_seconds())


async def process_pending(database, stop_event):
    signal = asyncio.Event()
    registration = (asyncio.get_running_loop(), signal)
    with _signal_lock:
        _worker_signals.add(registration)
    try:
        while not stop_event.is_set():
            signal.clear()
            timeout = POLL_SECONDS
            try:
                if await process_one(database):
                    continue
                delay = await asyncio.to_thread(_next_retry_delay, database)
                if delay is not None:
                    timeout = min(timeout, delay)
            except SQLAlchemyError:
                logging.getLogger(__name__).warning("document_worker_database_unavailable")
            except Exception:  # never let one bad job end the worker; the job's lease lets it be reclaimed
                logging.getLogger(__name__).exception("document_worker_iteration_failed")
            wake = asyncio.create_task(signal.wait())
            stop = asyncio.create_task(stop_event.wait())
            try:
                await asyncio.wait((wake, stop), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            finally:
                wake.cancel()
                stop.cancel()
                await asyncio.gather(wake, stop, return_exceptions=True)
    finally:
        with _signal_lock:
            _worker_signals.discard(registration)


def reindex(session, document):
    latest = latest_version(session, document.id)
    if latest is None or latest.status in {"pending", "processing"}:
        raise ValueError("document_indexing_in_progress")
    return add_version(session, document, latest.filename, latest.content, latest.as_of)


def delete_document(session, document_id, purge_evidence=False):
    document = get_document(session, document_id)
    if purge_evidence:
        from app.modules.documents.evidence import purge_document_evidence
        purge_document_evidence(session, document_id)
    session.delete(document)
    session.commit()
