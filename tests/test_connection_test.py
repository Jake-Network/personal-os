"""AI connection test: one fixed sentence, the global one-call slot, no fallback. Fake providers only."""

from datetime import timedelta

from sqlalchemy import select

from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob
from app.modules.llm.errors import QuotaExceeded
from app.modules.llm.connection_test import PROMPT


def test_sends_only_the_fixed_sentence_and_leaves_no_job(client, fake_provider, session):
    response = client.post("/api/settings/ai-provider/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["model"] == "fake-model"
    [request] = fake_provider.requests
    assert request.input == [{"role": "user", "content": PROMPT}]
    session.expire_all()
    assert session.scalars(select(BackgroundJob)).all() == []


def test_waits_for_a_running_model_call_instead_of_overlapping(client, fake_provider, session):
    session.add(BackgroundJob(request_id="synthetic-reflection", kind="advisor_reflection", enabled=True,
                              status="running", payload={}, lease_owner="worker", lease_until=utcnow() + timedelta(minutes=1)))
    session.commit()
    body = client.post("/api/settings/ai-provider/test").json()
    assert (body["ok"], body["code"]) == (False, "busy")
    assert fake_provider.requests == []


def test_provider_failure_is_reported_without_switching(client, fake_provider):
    fake_provider.error = QuotaExceeded()
    body = client.post("/api/settings/ai-provider/test").json()
    assert body["ok"] is False and body["code"] == QuotaExceeded.code
    assert len(fake_provider.requests) == 1  # ExplodingProvider (paid API) was never called


def test_slow_model_lookup_counts_against_the_same_timeout(client, fake_provider, session, monkeypatch):
    import asyncio

    from app.modules.llm import connection_test
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager

    async def slow_lookup(_session):
        await asyncio.sleep(5)
        return "fake-model"

    monkeypatch.setattr(connection_test, "TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(llm_gateway_manager, "resolve_model", slow_lookup)
    body = client.post("/api/settings/ai-provider/test").json()
    assert (body["ok"], body["code"]) == (False, "timeout")
    assert fake_provider.requests == []
    session.expire_all()
    assert session.scalars(select(BackgroundJob)).all() == []
