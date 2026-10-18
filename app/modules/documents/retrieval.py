"""Privacy-first hybrid retrieval. SQL is deterministic and never model-authored."""
import hashlib
import json
import math
import re
from sqlalchemy import func, or_, select

from app.config import settings
from app.modules.context.privacy_manager import privacy_manager
from app.modules.database.model import Document, DocumentVersion, DocumentChunk
from app.modules.documents import embedding
from app.modules.context.types import ToolResult
from app.modules.documents.types import DocumentCitation


def _tokens(text):
    return set(re.findall(r"[\w가-힣]+", text.lower()))


def _cosine(left, right, left_norm=None):
    return sum(a*b for a, b in zip(left, right)) / ((left_norm or math.hypot(*left)) * math.hypot(*right))


def _per_version(session, version_ids, order_by, limit, *conditions):
    """Up to `limit` chunks per version in one query: each document keeps its own candidate budget."""
    rank = func.row_number().over(partition_by=DocumentChunk.version_id, order_by=order_by).label("rank")
    ranked = (select(DocumentChunk.id, rank)
              .where(DocumentChunk.version_id.in_(version_ids), *conditions).subquery())
    return session.scalars(select(DocumentChunk).where(
        DocumentChunk.id.in_(select(ranked.c.id).where(ranked.c.rank <= limit)))).all()


def _overlapping_chunks(left, right):
    """Recognize the parser's 150-character overlap, not mere adjacency."""
    if (left.version_id != right.version_id or abs(left.ordinal - right.ordinal) != 1
            or left.page != right.page or left.section != right.section):
        return False
    earlier, later = (left, right) if left.ordinal < right.ordinal else (right, left)
    overlap = earlier.text[-150:].strip()
    return len(overlap) >= 80 and later.text.startswith(overlap)


def citation(chunk, version, document) -> DocumentCitation:
    return {"ref": f"document_chunks:{chunk.id}", "document_id": document.id, "version_id": version.id,
            "chunk_id": chunk.id, "title": document.title, "filename": version.filename, "page": chunk.page,
            "section": chunk.section, "text": chunk.text, "as_of": version.as_of.isoformat() if version.as_of else None}


def visible_documents(session, categories=None, document_ids=None, excluded_categories=None):
    excluded = {str(c) for c in privacy_manager.get_excluded(session)} | {str(c) for c in excluded_categories or []}
    allowed = {str(c) for c in categories} if categories is not None else None
    statement = select(Document).where(Document.sharing_enabled.is_(True), Document.active_version_id.is_not(None))
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    documents = session.scalars(statement).all()
    from app.modules.context.record_privacy import record_allowed
    return [doc for doc in documents if record_allowed(session, "documents", doc.id) and not excluded.intersection(doc.categories)
            and (allowed is None or set(doc.categories).intersection(allowed))
            and (document_ids is None or doc.id in document_ids)]


def cited_categories(session, citations):
    """Sorted categories of the documents the citations come from."""
    ids = {c["document_id"] for c in citations}
    if not ids:
        return []
    return sorted({str(c) for doc in session.scalars(select(Document).where(Document.id.in_(ids)))
                   for c in doc.categories})


def _source_versions(session, ids):
    # Queries must not reload the raw upload bytes for every conversation turn.
    columns = (DocumentVersion.id, DocumentVersion.filename, DocumentVersion.as_of,
               DocumentVersion.content_hash, DocumentVersion.status, DocumentVersion.embedding_model,
               DocumentVersion.embedding_dimensions, DocumentVersion.updated_at)
    return {row.id: row for row in session.execute(select(*columns).where(DocumentVersion.id.in_(ids)))} if ids else {}


def library_fingerprint(session, categories, document_ids=None, excluded_categories=None, *, documents=None, versions=None):
    """Source identity for snapshot comparison; does not rerun semantic retrieval."""
    docs = visible_documents(session, categories, document_ids or None, excluded_categories) if documents is None else documents
    sources = []
    versions = _source_versions(session, [d.active_version_id for d in docs]) if versions is None else versions
    for doc in sorted(docs, key=lambda row: row.id):
        version = versions.get(doc.active_version_id)
        if version is None:
            continue
        sources.append((doc.id, doc.title, doc.categories, str(doc.updated_at), version.id,
                        version.content_hash, version.status, version.embedding_model,
                        version.embedding_dimensions, str(version.as_of), str(version.updated_at)))
    body = [settings.embedding_model, settings.embedding_dimensions, sources]
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def search(session, query, categories, document_ids=None, limit=6, excluded_categories=None):
    pinned = list(dict.fromkeys(document_ids or []))[:5]
    documents = visible_documents(session, categories, pinned or None, excluded_categories)
    sources = _source_versions(session, [d.active_version_id for d in documents])
    result = ToolResult(data={"query": query, "citations": [], "requested_document_ids": pinned,
                             "source_fingerprint": library_fingerprint(session, categories, pinned, excluded_categories,
                                                                       documents=documents, versions=sources)})
    if not query.strip():
        return result
    if not documents:
        result.flags.append({"code": "no_matching_documents", "category": "documents"})
        return result
    versions = {key: version for key, version in sources.items() if version.status == "ready"
                and version.embedding_model == settings.embedding_model
                and version.embedding_dimensions == settings.embedding_dimensions}
    if not versions:
        result.flags.append({"code": "document_embedding_reindex_required", "category": "documents"})
        return result
    try:
        vector = embedding.embed_query(query[:4000])
    except Exception:
        result.flags.append({"code": "document_embedding_unavailable", "category": "documents"})
        return result
    documents_by_version = {d.active_version_id: d for d in documents}
    tokens = _tokens(query)
    ranked = []
    # Candidate budget is per document: pinned comparisons retain both sources. One query per
    # candidate kind for the whole library, never one per document.
    version_ids = list(versions)
    if session.get_bind().dialect.name == "postgresql":
        candidates = _per_version(session, version_ids, DocumentChunk.embedding.cosine_distance(vector), 40)
        # Include lexical candidates independently of nearest neighbors.
        conditions = [DocumentChunk.text.ilike("%" + token.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\")
                      for token in sorted(tokens)[:12]]
        lexical = _per_version(session, version_ids, DocumentChunk.id, 40, or_(*conditions)) if conditions else []
        candidates = list({c.id: c for c in candidates + lexical}.values())
    else:
        candidates = _per_version(session, version_ids, DocumentChunk.ordinal, 500)
    query_norm = math.hypot(*vector)
    for chunk in candidates:
        cosine = _cosine(vector, chunk.embedding, query_norm)
        lexical = len(tokens & _tokens(chunk.text)) / max(1, len(tokens))
        if not pinned and cosine < 0.35 and lexical == 0:
            continue
        score = cosine * 0.7 + lexical * 0.3
        ranked.append((score, chunk, versions[chunk.version_id], documents_by_version[chunk.version_id]))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    chosen = []
    if pinned:
        for document_id in pinned:
            found = next((r for r in ranked if r[3].id == document_id), None)
            if found:
                chosen.append(found)
    for row in ranked:
        if len(chosen) >= max(len(pinned), min(limit, 10)):
            break
        if row[1].id not in {r[1].id for r in chosen}:
            # Overlapping chunks can otherwise crowd out other evidence.
            if not any(_overlapping_chunks(r[1], row[1]) for r in chosen):
                chosen.append(row)
    result.data["citations"] = [citation(chunk, version, document) for _, chunk, version, document in chosen]
    result.refs = [{"table": "document_chunks", "id": chunk.id, "document_id": document.id,
                    "version_id": version.id, "updated_at": version.updated_at.isoformat()}
                   for _, chunk, version, document in chosen]
    if chosen:
        result.source_updated_at = max(row[2].updated_at for row in chosen)
    else:
        result.flags.append({"code": "no_relevant_document_chunks", "category": "documents"})
    missing = sorted(set(pinned) - {row[3].id for row in chosen})
    if missing:
        result.flags.append({"code": "requested_document_unavailable", "category": "documents", "document_ids": missing})
    return result
