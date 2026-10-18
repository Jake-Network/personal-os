"""Bounded local Ollama or DenseCore embedding calls; no provider fallback."""
import math

import httpx

from app.config import settings

BATCH_SIZE = 16
QWEN_RETRIEVAL_INSTRUCTION = "Given a search query, retrieve relevant passages that answer the query"


def validate_vectors(payload: dict, count: int) -> list[list[float]]:
    if not isinstance(payload, dict) or payload.get("model") != settings.embedding_model:
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


def _provider() -> str:
    provider = settings.embedding_provider
    if provider not in {"ollama", "densecore"}:
        raise ValueError("unsupported_embedding_provider")
    if provider == "densecore" and not settings.embedding_densecore_model_id:
        raise ValueError("densecore_model_id_required")
    return provider


def _validate_loaded_model(payload: dict) -> None:
    # DenseCore echoes the requested model in embeddings, regardless of its loaded
    # weights. Check its independently reported loaded GGUF identity instead.
    data = payload.get("data") if isinstance(payload, dict) else None
    if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
            or data[0].get("id") != settings.embedding_densecore_model_id
            or not data[0].get("root")):
        raise ValueError("densecore_loaded_model_mismatch")


def _request(texts: list[str], provider: str) -> tuple[str, dict]:
    if provider == "ollama":
        return "/api/embed", {"model": settings.embedding_model, "input": texts, "truncate": False}
    return "/v1/embeddings", {"model": settings.embedding_model, "input": texts,
                              "pooling_type": "last", "normalize": True}


def _validate_response(payload: dict, count: int, provider: str) -> list[list[float]]:
    if provider == "ollama":
        return validate_vectors(payload, count)
    if not isinstance(payload, dict) or payload.get("model") != settings.embedding_model:
        raise ValueError("embedding_model_mismatch")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise ValueError("embedding_count_mismatch")
    vectors = [None] * count
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("invalid_embedding_index")
        index = item.get("index")
        if (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count
                or vectors[index] is not None):
            raise ValueError("invalid_embedding_index")
        vectors[index] = item.get("embedding")
    return validate_vectors({"model": payload["model"], "embeddings": vectors}, count)


def embed_query(text: str) -> list[float]:
    provider = _provider()
    if provider == "densecore" and "qwen3-embedding" in settings.embedding_model.lower():
        text = f"Instruct: {QWEN_RETRIEVAL_INSTRUCTION}\nQuery:{text}"
    base = settings.embedding_url.rstrip("/")
    with httpx.Client(timeout=60 if provider == "densecore" else 20) as client:
        if provider == "densecore":
            response = client.get(base + "/v1/models")
            response.raise_for_status()
            _validate_loaded_model(response.json())
        path, body = _request([text], provider)
        response = client.post(base + path, json=body)
        response.raise_for_status()
        return _validate_response(response.json(), 1, provider)[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    provider = _provider()
    base = settings.embedding_url.rstrip("/")
    result = []
    async with httpx.AsyncClient(timeout=180 if provider == "densecore" else 90) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            # Recheck for every batch: never silently mix a changed loaded model.
            if provider == "densecore":
                response = await client.get(base + "/v1/models")
                response.raise_for_status()
                _validate_loaded_model(response.json())
            batch = texts[start:start + BATCH_SIZE]
            path, body = _request(batch, provider)
            response = await client.post(base + path, json=body)
            response.raise_for_status()
            result.extend(_validate_response(response.json(), len(batch), provider))
    return result
