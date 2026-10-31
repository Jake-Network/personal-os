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


def test_revocation_during_loaded_model_check_blocks_personal_payload(confirmed):
    from sqlalchemy.orm import Session
    from app.modules.llm.transfer_policy import TransferNotConfirmed

    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/models":
            with Session(confirmed.get_bind()) as concurrent:
                transfer_policy.invalidate(concurrent)
                concurrent.commit()
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, text=sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}))

    local = LocalOpenAICompatibleProvider(lambda: "http://127.0.0.1:18081", lambda: MODEL,
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(TransferNotConfirmed):
        run(confirmed, local, LLMRequest(model=MODEL, instructions="", input=[
            {"role": "user", "content": "합성 개인 상담 내용"}]))
    assert [request.url.path for request in seen] == ["/v1/models"]


def test_source_sharing_change_during_model_check_blocks_personal_payload(confirmed):
    from sqlalchemy.orm import Session
    from app.enums.context_category import Category
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.database.model import ContextSnapshot
    from app.modules.llm.errors import AdvisorError

    snapshot = ContextSnapshot(id="synthetic-local-source", context_categories=["financial"], record_references=[],
        source_updated_at={}, data_quality_flags=[], payload={}, content_hash="synthetic")
    confirmed.add(snapshot)
    confirmed.commit()
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/models":
            with Session(confirmed.get_bind()) as concurrent:
                privacy_manager.set_excluded(concurrent, [Category.FINANCIAL])
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, text=sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}))

    local = LocalOpenAICompatibleProvider(lambda: "http://127.0.0.1:18081", lambda: MODEL,
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(AdvisorError) as caught:
        run(confirmed, local, LLMRequest(model=MODEL, instructions="", input=[
            {"role": "user", "content": "합성 재무 상담 내용"}], source_snapshot_id=snapshot.id))
    assert caught.value.provider_code == "source_policy_changed"
    assert [request.url.path for request in seen] == ["/v1/models"]


def test_run_cancellation_during_model_check_blocks_personal_payload(confirmed):
    from datetime import timedelta
    from sqlalchemy.orm import Session
    from app.modules.database.model import AdvisorConversation
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow
    from app.modules.llm.errors import AdvisorError

    conversation = AdvisorConversation(title="합성 상담")
    confirmed.add(conversation)
    confirmed.flush()
    advisor_run = AdvisorRun(id="synthetic-local-run", conversation_id=conversation.id, request_id="synthetic",
        status="running", input_payload={}, lease_owner="synthetic-worker", lease_generation=1,
        lease_until=utcnow() + timedelta(minutes=5))
    confirmed.add(advisor_run)
    confirmed.commit()
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/models":
            with Session(confirmed.get_bind()) as concurrent:
                concurrent.get(AdvisorRun, advisor_run.id).status = "cancel_requested"
                concurrent.commit()
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, text=sse({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}))

    local = LocalOpenAICompatibleProvider(lambda: "http://127.0.0.1:18081", lambda: MODEL,
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(AdvisorError) as caught:
        run(confirmed, local, LLMRequest(model=MODEL, instructions="", input=[
            {"role": "user", "content": "합성 개인 상담 내용"}], run_id=advisor_run.id,
            run_owner="synthetic-worker", run_generation=1))
    assert caught.value.provider_code == "run_authorization_changed"
    assert [request.url.path for request in seen] == ["/v1/models"]


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
