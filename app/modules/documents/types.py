"""Shapes of the document evidence that retrieval returns and snapshots record."""

from typing import TypedDict


class DocumentCitation(TypedDict):
    """One retrieved chunk as the model and the Context Inspector see it."""

    ref: str  # "document_chunks:<chunk id>", the token the model cites
    document_id: int
    version_id: int
    chunk_id: int
    title: str
    filename: str
    page: int | None
    section: str | None
    text: str
    as_of: str | None


class DocumentReferenceRow(TypedDict):
    """One `context_document_references` row: a snapshot depends on a document version."""

    snapshot_id: str
    document_id: int
    version_id: int  # 0 when the evidence carries no version
