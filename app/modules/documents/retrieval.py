"""Privacy-first hybrid retrieval. SQL is deterministic and never model-authored."""
import hashlib
import json
import math
import re
from sqlalchemy import select

from app.config import settings
from app.modules.context.privacy_manager import privacy_manager
from app.modules.database.model import Document, DocumentVersion, DocumentChunk
from app.modules.documents import embedding
from app.schema.context_schema import ToolResult


def _tokens(text):
    return set(re.findall(r"[\w가-힣]+", text.lower()))


def _cosine(left, right):
    return sum(a*b for a, b in zip(left, right)) / (math.hypot(*left) * math.hypot(*right))


def citation(chunk, version, document):
    return {"ref": f"document_chunks:{chunk.id}", "document_id": document.id, "version_id": version.id,
            "chunk_id": chunk.id, "title": document.title, "filename": version.filename, "page": chunk.page,
            "section": chunk.section, "text": chunk.text, "as_of": version.as_of.isoformat() if version.as_of else None}


def visible_documents(session, categories=None, document_ids=None, excluded_categories=None):
    excluded = {str(c) for c in privacy_manager.get_excluded(session)} | {str(c) for c in excluded_categories or []}
    allowed = {str(c) for c in categories} if categories is not None else None
    documents = session.scalars(select(Document).where(Document.sharing_enabled.is_(True),
                                                       Document.active_version_id.is_not(None))).all()
    return [doc for doc in documents if not excluded.intersection(doc.categories)
            and (allowed is None or set(doc.categories).intersection(allowed))
            and (document_ids is None or doc.id in document_ids)]


def library_fingerprint(session, categories, document_ids=None, excluded_categories=None):
    """Source identity for snapshot comparison; does not rerun semantic retrieval."""
    docs = visible_documents(session, categories, document_ids or None, excluded_categories)
    sources = []
    for doc in sorted(docs, key=lambda row: row.id):
        version = session.get(DocumentVersion, doc.active_version_id)
        sources.append((doc.id, doc.title, doc.categories, str(doc.updated_at), version.id,
                        version.content_hash, version.status, version.embedding_model,
                        version.embedding_dimensions, str(version.as_of), str(version.updated_at)))
    body = [settings.embedding_model, settings.embedding_dimensions, sources]
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def search(session, query, categories, document_ids=None, limit=6, excluded_categories=None):
    pinned = list(dict.fromkeys(document_ids or []))[:5]
    result = ToolResult(data={"query": query, "citations": [], "requested_document_ids": pinned,
                             "source_fingerprint": library_fingerprint(session, categories, pinned, excluded_categories)})
    if not query.strip():
        return result
    documents = visible_documents(session, categories, pinned or None, excluded_categories)
    if not documents:
        result.flags.append({"code": "no_matching_documents", "category": "documents"})
        return result
    versions = {v.id: v for v in session.scalars(select(DocumentVersion).where(
        DocumentVersion.id.in_([d.active_version_id for d in documents]), DocumentVersion.status == "ready",
        DocumentVersion.embedding_model == settings.embedding_model,
        DocumentVersion.embedding_dimensions == settings.embedding_dimensions))}
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
    # Candidate budget is per document: pinned comparisons retain both sources.
    for version_id, version in versions.items():
        statement = select(DocumentChunk).where(DocumentChunk.version_id == version_id)
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.order_by(DocumentChunk.embedding.cosine_distance(vector)).limit(40)
            candidates = session.scalars(statement).all()
            # Include lexical candidates independently of nearest neighbors.
            from sqlalchemy import or_
            conditions = [DocumentChunk.text.ilike("%" + token.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\")
                          for token in sorted(tokens)[:12]]
            lexical = session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id,
                                      or_(*conditions)).order_by(DocumentChunk.id).limit(40)).all() if conditions else []
            candidates = list({c.id: c for c in candidates + lexical}.values())
        else:
            candidates = session.scalars(statement.order_by(DocumentChunk.ordinal).limit(500)).all()
        for chunk in candidates:
            cosine = _cosine(vector, chunk.embedding)
            lexical = len(tokens & _tokens(chunk.text)) / max(1, len(tokens))
            if not pinned and cosine < 0.35 and lexical == 0:
                continue
            score = cosine * 0.7 + lexical * 0.3
            ranked.append((score, chunk, version, documents_by_version[version_id]))
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
            if not any(r[1].version_id == row[1].version_id and abs(r[1].ordinal-row[1].ordinal) <= 1 for r in chosen):
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
