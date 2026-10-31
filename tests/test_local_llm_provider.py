"""Local OpenAI-compatible provider (DenseCore): stream parsing, loaded-model check, local-only URLs. No real server."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.config import settings
from app.modules.llm import transfer_policy
from app.modules.llm.errors import IncompleteResponse, ProviderUnavailable
from app.modules.llm.llm_gateway_manager import PROVIDER_KEY, llm_gateway_manager
from app.modules.llm.providers import LocalOpenAICompatibleProvider, local_url_allowed
from app.modules.llm.types import LLMRequest
from app.modules.crud import app_setting_handler

MODEL = "Synthetic-Qwen-Q4"


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def fake_server(seen, loaded=MODEL, chunks=None):
    chunks = chunks or [
        {"choices": [{"delta": {"reasoning_content": "생각 중"}}]},
        {"choices": [{"delta": {"content": '{"answer":'}}]},
        {"choices": [{"delta": {"content": ' "합성"}'}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4}},
    ]

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": loaded, "root": "/models/x.gguf"}]})
        return httpx.Response(200, text=sse(*chunks), headers={"content-type": "text/event-stream"})
    return handler


def provider(seen, **kwargs):
    transport = httpx.MockTransport(fake_server(seen, **kwargs))
    return LocalOpenAICompatibleProvider(lambda: "http://127.0.0.1:18081", lambda: MODEL,
                                         lambda: httpx.AsyncClient(transport=transport))


def run(session, local, request):
    async def collect():
        return [event async for event in local.stream(session, request)]
    return asyncio.run(collect())


@pytest.fixture
def confirmed(session, monkeypatch):
    import app.config
    monkeypatch.setattr(app.config, "settings", replace(settings, llm_local_model_id=MODEL))
    transfer_policy.confirm(session, "local_densecore", True, True)
    return session


def test_streams_answer_text_without_reasoning_and_sends_json_mode(confirmed):
    seen = []
    events = run(confirmed, provider(seen), LLMRequest(model="ignored", instructions="규칙", json_mode=True,
                                                        input=[{"role": "developer", "content": "Context Package\n{}"},
                                                               {"role": "user", "content": "질문"}]))
    assert "".join(e.text for e in events if e.type == "delta") == '{"answer": "합성"}'
    assert events[-1].type == "completed" and events[-1].usage == {"input_tokens": 12, "output_tokens": 4}
    body = json.loads(seen[-1].content)
    assert body["model"] == MODEL and body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "developer", "user"]


def test_refuses_when_a_different_model_is_loaded(confirmed):
    seen = []
    with pytest.raises(ProviderUnavailable) as caught:
        run(confirmed, provider(seen, loaded="Other-Model"), LLMRequest(model="m", instructions="", input=[{"role": "user", "content": "q"}]))
    assert caught.value.provider_code == "local_model_mismatch"
    assert all(r.url.path == "/v1/models" for r in seen)  # nothing was sent for generation


def test_truncated_output_is_incomplete_not_an_answer(confirmed):
    chunks = [{"choices": [{"delta": {"content": "잘린"}, "finish_reason": "length"}]}]
    with pytest.raises(IncompleteResponse):
        run(confirmed, provider([], chunks=chunks), LLMRequest(model="m", instructions="", input=[{"role": "user", "content": "q"}]))


def test_requires_transfer_confirmation_for_this_server_and_model(session):
    from app.modules.llm.transfer_policy import TransferNotConfirmed
    with pytest.raises(TransferNotConfirmed):
        run(session, provider([]), LLMRequest(model="m", instructions="", input=[{"role": "user", "content": "q"}]))


def test_only_local_urls_are_allowed():
    assert all(local_url_allowed(u) for u in ["http://127.0.0.1:18081", "http://localhost:1", "http://densecore:8080",
                                               "http://192.168.0.5:8080", "http://10.0.0.2",
                                               "http://host.docker.internal:18081"])
    assert not any(local_url_allowed(u) for u in ["https://api.example.com", "http://8.8.8.8", "ftp://127.0.0.1"])


def test_selected_explicitly_and_never_a_fallback(session, monkeypatch):
    local = llm_gateway_manager.providers["local_densecore"]
    monkeypatch.setattr(local, "model_id", lambda: MODEL)
    assert llm_gateway_manager.provider_name(session) == "chatgpt_plan"
    app_setting_handler.set_value(session, PROVIDER_KEY, {"name": "local_densecore"})
    assert llm_gateway_manager.configuration_complete(session)
    monkeypatch.setattr(local, "base_url", lambda: "https://api.example.com")
    assert not llm_gateway_manager.configuration_complete(session)
