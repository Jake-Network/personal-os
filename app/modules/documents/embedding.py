"""Bounded local Ollama embedding calls; no paid fallback."""
import math
import httpx
from app.config import settings

BATCH_SIZE = 16


def validate_vectors(payload: dict, count: int) -> list[list[float]]:
    if payload.get("model") != settings.embedding_model:
        raise ValueError("embedding_model_mismatch")
    vectors = payload.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("embedding_count_mismatch")
    for vector in vectors:
        if (not isinstance(vector, list) or len(vector) != settings.embedding_dimensions
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector)
                or any(abs(v) > 3.4e38 for v in vector)
                or math.hypot(*vector) < 1e-12):
            raise ValueError("invalid_embedding_vector")
    return vectors


def embed_query(text: str) -> list[float]:
    with httpx.Client(timeout=20) as client:
        response = client.post(settings.embedding_url.rstrip("/") + "/api/embed",
                               json={"model": settings.embedding_model, "input": [text], "truncate": False})
        response.raise_for_status()
        return validate_vectors(response.json(), 1)[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    result = []
    async with httpx.AsyncClient(timeout=90) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start:start + BATCH_SIZE]
            response = await client.post(settings.embedding_url.rstrip("/") + "/api/embed",
                                         json={"model": settings.embedding_model, "input": batch, "truncate": False})
            response.raise_for_status()
            result.extend(validate_vectors(response.json(), len(batch)))
    return result
