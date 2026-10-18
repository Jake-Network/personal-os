"""How a failed indexing job is reported and whether it is retried."""
from datetime import timedelta

import httpx

RETRY_BASE_SECONDS = 30
# Error strings that are fixed codes and safe to show; anything else is reported by exception type.
SAFE_ERROR_CODES = {"embedding_model_mismatch", "embedding_count_mismatch", "invalid_embedding_vector",
                    "encrypted_or_too_many_pdf_pages", "document_text_too_large",
                    "too_many_document_chunks", "no_extractable_text_ocr_not_supported"}


def failure_code(exc):
    return str(exc) if str(exc) in SAFE_ERROR_CODES else type(exc).__name__


def is_transient(exc):
    """Errors that a later attempt can succeed past: transport failures, timeouts, 429 and 5xx."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def retry_delay(attempt):
    """Exponential backoff from RETRY_BASE_SECONDS; `attempt` counts from 1."""
    return timedelta(seconds=RETRY_BASE_SECONDS * 2 ** (attempt - 1))
