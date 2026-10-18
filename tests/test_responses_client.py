import asyncio
import json

import httpx
import pytest

from app.modules.llm.errors import IncompleteResponse, QuotaExceeded, ScopeNotAuthorized
from app.modules.llm.providers import ResponsesApiClient
from app.modules.llm.types import LLMRequest

REQ = LLMRequest(model="m", instructions="i", input=[{"role": "user", "content": "hi"}])


def client_for(handler):
    transport = httpx.MockTransport(handler)
    return ResponsesApiClient("https://api.openai.com/v1", lambda: httpx.AsyncClient(transport=transport))


def sse(*events: str) -> bytes:
    return "".join(f"data: {e}\n\n" for e in events).encode()


def collect(client):
    async def go():
        return [e async for e in client.stream("tok", REQ)]
    return asyncio.run(go())


def test_streams_deltas_until_completed_with_store_false():
    seen = {}

    def handler(request):
        seen["body"] = request.content
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, content=sse(
            '{"type":"response.output_text.delta","delta":"안녕"}',
            '{"type":"response.output_text.delta","delta":"하세요"}',
            '{"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":2}}}',
        ), headers={"content-type": "text/event-stream"})

    events = collect(client_for(handler))
    assert "".join(e.text for e in events if e.type == "delta") == "안녕하세요"
    assert events[-1].usage["output_tokens"] == 2
    body = json.loads(seen["body"])
    assert body["store"] is False and body["stream"] is True
    assert "text" not in body
    assert seen["auth"] == "Bearer tok"


def test_structured_request_uses_provider_json_mode():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=sse('{"type":"response.completed"}'))

    request = LLMRequest(model="m", instructions="Return JSON", input=[], json_mode=True)

    async def go():
        return [event async for event in client_for(handler).stream("tok", request)]

    asyncio.run(go())
    assert seen["text"] == {"format": {"type": "json_object"}}
    assert seen["store"] is False


def test_usage_limit_in_stream_maps_to_quota_exceeded():
    def handler(request):
        return httpx.Response(200, content=sse(
            '{"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}}'))
    with pytest.raises(QuotaExceeded):
        collect(client_for(handler))


def test_http_errors_map_to_recovery_paths():
    with pytest.raises(QuotaExceeded):
        collect(client_for(lambda r: httpx.Response(
            429, json={"error": {"code": "subscription_sharing_usage_limit_exceeded"}})))
    with pytest.raises(ScopeNotAuthorized):
        collect(client_for(lambda r: httpx.Response(403, json={"error": {"code": "chatpass_v2_scope_not_authorized"}})))


def test_stream_without_completed_is_incomplete():
    with pytest.raises(IncompleteResponse):
        collect(client_for(lambda r: httpx.Response(200, content=sse(
            '{"type":"response.output_text.delta","delta":"부분"}'))))


def test_model_listing_keeps_listed_slugs():
    def handler(request):
        return httpx.Response(200, json={"data": [{"slug": "a", "visibility": "list"},
                                                  {"slug": "b", "visibility": "hide"}]})
    assert asyncio.run(client_for(handler).list_models("tok")) == ["a"]
