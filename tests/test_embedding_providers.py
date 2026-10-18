"""Provider contract tests: real HTTP serialization, no model inference required."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.config import settings
from app.modules.documents import embedding


@pytest.fixture
def densecore(monkeypatch):
    configured = replace(settings, embedding_provider="densecore", embedding_model="Qwen3-Embedding-0.6B",
                         embedding_densecore_model_id="Qwen3-Embedding-0.6B-Q8_0", embedding_dimensions=3)
    monkeypatch.setattr(embedding, "settings", configured)
    return configured


def model_payload(model_id="Qwen3-Embedding-0.6B-Q8_0"):
    return {"data": [{"id": model_id, "root": "/models/Qwen3-Embedding-0.6B-Q8_0.gguf"}]}


def embedding_payload(vectors):
    return {"model": "Qwen3-Embedding-0.6B", "data": [
        {"index": i, "embedding": vector} for i, vector in enumerate(vectors)]}


def test_densecore_query_uses_loaded_identity_and_query_only_instruction(densecore, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json=model_payload())
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert body == {"model": densecore.embedding_model,
                        "input": [f"Instruct: {embedding.QWEN_RETRIEVAL_INSTRUCTION}\nQuery:내 자산 배분은?"],
                        "pooling_type": "last", "normalize": True}
        return httpx.Response(200, json=embedding_payload([[1., 0., 0.]]))
    client = httpx.Client
    monkeypatch.setattr(embedding.httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    assert embedding.embed_query("내 자산 배분은?") == [1., 0., 0.]
    assert [call.method for call in calls] == ["GET", "POST"]


def test_densecore_async_batches_preserve_raw_documents_and_response_order(densecore, monkeypatch):
    batches = []
    identities = []
    def handler(request):
        if request.method == "GET":
            identities.append(request)
            return httpx.Response(200, json=model_payload())
        body = json.loads(request.content)
        batches.append(body)
        vectors = [[float(int(text) + 1), 1., 0.] for text in body["input"]]
        payload = embedding_payload(vectors)
        payload["data"].reverse()
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient
    monkeypatch.setattr(embedding.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    assert asyncio.run(embedding.embed_texts([str(i) for i in range(35)])) == [
        [float(i + 1), 1., 0.] for i in range(35)]
    assert [len(batch["input"]) for batch in batches] == [16, 16, 3]
    assert len(identities) == 3
    assert all(batch["pooling_type"] == "last" and batch["normalize"] for batch in batches)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_loaded_model_mismatch_blocks_embedding_request(densecore, monkeypatch, asynchronous):
    def handler(request):
        assert request.method == "GET", "wrong loaded model must never receive document input"
        return httpx.Response(200, json=model_payload("other-weights"))
    sync, async_ = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(embedding.httpx, "Client", lambda **kwargs: sync(
        transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(embedding.httpx, "AsyncClient", lambda **kwargs: async_(
        transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError, match="densecore_loaded_model_mismatch"):
        if asynchronous:
            asyncio.run(embedding.embed_texts(["private document"]))
        else:
            embedding.embed_query("private query")


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [1, 0, 0]}, {"index": 0, "embedding": [0, 1, 0]}],
    [{"index": True, "embedding": [1, 0, 0]}, {"index": 0, "embedding": [0, 1, 0]}],
    [{"index": -1, "embedding": [1, 0, 0]}, {"index": 1, "embedding": [0, 1, 0]}],
    [{"index": 2, "embedding": [1, 0, 0]}, {"index": 0, "embedding": [0, 1, 0]}],
    [{"embedding": [1, 0, 0]}, {"index": 1, "embedding": [0, 1, 0]}],
    [None, {"index": 1, "embedding": [0, 1, 0]}],
])
def test_densecore_rejects_invalid_indices(densecore, data):
    with pytest.raises(ValueError, match="invalid_embedding_index"):
        embedding._validate_response({"model": densecore.embedding_model, "data": data}, 2, "densecore")


@pytest.mark.parametrize("vector", [[0, 0, 0], [1, 0], [True, 0, 0], [float("nan"), 0, 0],
                                    [float("inf"), 0, 0], [4e38, 0, 0], ["1", 0, 0], None])
def test_densecore_rejects_invalid_vectors(densecore, vector):
    with pytest.raises(ValueError, match="invalid_embedding_vector"):
        embedding._validate_response(embedding_payload([vector]), 1, "densecore")


def test_densecore_rejects_count_and_echoed_model_mismatch(densecore):
    with pytest.raises(ValueError, match="embedding_count_mismatch"):
        embedding._validate_response(embedding_payload([]), 1, "densecore")
    with pytest.raises(ValueError, match="embedding_model_mismatch"):
        embedding._validate_response({"model": "other", "data": []}, 0, "densecore")


@pytest.mark.parametrize("provider,loaded_id,error", [
    ("typo", "", "unsupported_embedding_provider"),
    ("densecore", "", "densecore_model_id_required"),
])
def test_provider_configuration_fails_before_network(monkeypatch, provider, loaded_id, error):
    monkeypatch.setattr(embedding, "settings", replace(settings, embedding_provider=provider,
                        embedding_densecore_model_id=loaded_id))
    with pytest.raises(ValueError, match=error):
        embedding.embed_query("query")


def test_ollama_query_keeps_original_protocol(monkeypatch):
    configured = replace(settings, embedding_provider="ollama", embedding_model="bge-m3", embedding_dimensions=3)
    monkeypatch.setattr(embedding, "settings", configured)
    def handler(request):
        assert request.url.path == "/api/embed"
        assert json.loads(request.content) == {"model": "bge-m3", "input": ["raw query"], "truncate": False}
        return httpx.Response(200, json={"model": "bge-m3", "embeddings": [[1., 0., 0.]]})
    client = httpx.Client
    monkeypatch.setattr(embedding.httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    assert embedding.embed_query("raw query") == [1., 0., 0.]
