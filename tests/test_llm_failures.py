"""Provider failures end the turn safely: an error event, no paid fallback, nothing broken replayed."""
import asyncio

import httpx

from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.crud import llm_usage_event_handler, message_handler
from app.modules.llm.errors import AuthRequired, QuotaExceeded
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.modules.llm.types import StreamEvent


def run(session, conv, text):
    async def collect():
        return [e async for e in advisor_manager.ask(session, conv, text)]
    return asyncio.run(collect())


class MidStreamFailure:
    name = "chatgpt_plan"

    def __init__(self, error: Exception):
        self.error = error
        self.requests = []

    async def list_models(self, session):
        return ["fake-model"]

    async def stream(self, session, request):
        self.requests.append(request)
        yield StreamEvent("delta", text="부분 ")
        yield StreamEvent("delta", text="응답")
        raise self.error


def test_auth_error_is_reported_without_paid_fallback(seeded, fake_provider):
    fake_provider.error = AuthRequired()
    conv = advisor_manager.create_conversation(seeded, "x")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert events[-1]["type"] == "error" and events[-1]["code"] == "reauth_required"
    assert [(u.provider, u.outcome) for u in llm_usage_event_handler.get_recent(seeded)] == [
        ("chatgpt_plan", "auth_error")]
    assert llm_gateway_manager.provider_name(seeded) == "chatgpt_plan"  # selection untouched


def test_mid_stream_quota_keeps_partial_answer_out_of_history(seeded, fake_provider, monkeypatch):
    failing = MidStreamFailure(QuotaExceeded())
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", failing)
    conv = advisor_manager.create_conversation(seeded, "x")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert [e["type"] for e in events] == ["context", "delta", "delta", "error"]
    msgs = message_handler.get_by_conversation(seeded, conv.id)
    assert [(m.role, m.status, m.content) for m in msgs] == [
        ("user", "failed", "현재 내 순자산은?"), ("assistant", "incomplete", "부분 응답")]

    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", fake_provider)
    run(seeded, conv, "현재 내 순자산은?")
    assert [i["role"] for i in fake_provider.requests[0].input] == ["developer", "user"]


def test_unexpected_transport_error_becomes_an_error_event(seeded, fake_provider, monkeypatch):
    failing = MidStreamFailure(httpx.ReadTimeout("timed out"))
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", failing)
    conv = advisor_manager.create_conversation(seeded, "x")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert events[-1] == {"type": "error", "code": "advisor_error", "message": "AI 응답을 생성하지 못했습니다.",
                          "provider_code": None}
    assert [m.status for m in message_handler.get_by_conversation(seeded, conv.id)] == ["failed", "incomplete"]
    assert [u.outcome for u in llm_usage_event_handler.get_recent(seeded)] == ["failed"]


def test_no_models_is_an_error_not_a_fallback(seeded, fake_provider, monkeypatch):
    async def none(session):
        return []
    monkeypatch.setattr(fake_provider, "list_models", none)
    monkeypatch.setattr(llm_gateway_manager, "default_model", "")
    conv = advisor_manager.create_conversation(seeded, "x")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert events[-1]["type"] == "error" and events[-1]["provider_code"] == "no_models"
    assert fake_provider.requests == []
