import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.database import get_session
from app.modules.database.model import Document, DocumentVersion, DocumentChunk, JobApplication, Goal
from app.modules.documents import document_manager as manager
from app.modules.documents.retrieval import citation, visible_documents
from app.schema.document_schema import DocumentItem, DocumentPatch

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _categories(value):
    try:
        values = json.loads(value)
        if not isinstance(values, list) or not values or len(values) > 7:
            raise ValueError()
        return sorted({Category(c).value for c in values})
    except (ValueError, TypeError):
        raise HTTPException(422, "categories_must_be_nonempty_json_array_of_valid_categories")


def _get(session, document_id):
    try:
        return manager.get_document(session, document_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("", response_model=list[DocumentItem])
def list_documents(session: Session = Depends(get_session)):
    return [manager.item(session, doc) for doc in session.scalars(select(Document).order_by(Document.updated_at.desc()))]


@router.post("", response_model=DocumentItem, status_code=201)
async def upload_document(file: UploadFile = File(...), title: str = Form(..., min_length=1, max_length=200),
                          categories: str = Form(...), kind: str = Form("reference", min_length=1, max_length=64),
                          as_of: date | None = Form(None), application_id: int | None = Form(None),
                          goal_id: int | None = Form(None), session: Session = Depends(get_session)):
    cats = _categories(categories)
    for model, value in ((JobApplication, application_id), (Goal, goal_id)):
        if value is not None and session.get(model, value) is None:
            raise HTTPException(422, "linked_record_not_found")
    document = Document(title=title, categories=cats, kind=kind, application_id=application_id, goal_id=goal_id)
    content = await file.read(manager.MAX_BYTES + 1)
    try:
        session.add(document)
        session.flush()
        return manager.add_version(session, document, file.filename or "", content, as_of)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("/{document_id}/versions", response_model=DocumentItem, status_code=201)
async def upload_version(document_id: int, file: UploadFile = File(...), as_of: date | None = Form(None),
                         session: Session = Depends(get_session)):
    document = _get(session, document_id)
    try:
        return manager.add_version(session, document, file.filename or "", await file.read(manager.MAX_BYTES + 1), as_of)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{document_id}/versions")
def versions(document_id: int, session: Session = Depends(get_session)):
    _get(session, document_id)
    return [{key: getattr(row, key) for key in ("id", "document_id", "filename", "as_of", "status", "error",
             "embedding_model", "embedding_dimensions", "created_at", "updated_at")}
            for row in session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                                       .order_by(DocumentVersion.id.desc()))]


@router.post("/{document_id}/retry", response_model=DocumentItem)
def retry(document_id: int, session: Session = Depends(get_session)):
    document = _get(session, document_id)
    version = manager.latest_version(session, document_id)
    if version.status != "failed":
        raise HTTPException(409, "only_failed_versions_can_be_retried")
    version.status, version.error = "pending", None
    session.commit()
    return manager.item(session, document)


@router.patch("/{document_id}", response_model=DocumentItem)
def patch(document_id: int, body: DocumentPatch, session: Session = Depends(get_session)):
    document = _get(session, document_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, "metadata_cannot_be_null")
        setattr(document, key, sorted({str(c) for c in value}) if key == "categories" else value)
    session.commit()
    return manager.item(session, document)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, purge_evidence: bool = False, session: Session = Depends(get_session)):
    _get(session, document_id)
    manager.delete_document(session, document_id, purge_evidence)


@router.get("/chunks/{chunk_id}")
def chunk_source(chunk_id: int, session: Session = Depends(get_session)):
    chunk = session.get(DocumentChunk, chunk_id)
    version = session.get(DocumentVersion, chunk.version_id) if chunk else None
    allowed = {d.id: d for d in visible_documents(session)}
    if version is None or version.document_id not in allowed:
        raise HTTPException(404, "document_chunk_not_available")
    return citation(chunk, version, allowed[version.document_id])
