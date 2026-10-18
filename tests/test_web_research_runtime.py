"""Public-query-only web evidence through the durable consultation worker."""
import asyncio
import json
from contextlib import suppress
from datetime import timedelta

import pytest
from sqlalchemy import select

from test_advisor_runtime_execution import FINAL, PLAN, REVIEW, runtime_env  # noqa: F401
from app.modules.advisor.runtime.worker import process_one
from app.modules.database.model import AdvisorConversation, AdvisorMessage, ContextSnapshot
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow
from app.modules.web_search import WebSearchError, WebSearchService

PUBLIC_QUERY = "공개 회사 채용 정보"
PAGE_URL = "https://example.com/careers/987654321"
EXCERPT = "공개 채용 본문에서는 원격 근무와 서버 개발 경험을 요구합니다."


def test_local_snapshot_comparison_does_not_claim_web_content_changed(monkeypatch):
    from types import SimpleNamespace
    from app.modules.context.context_builder_manager import ContextBuilderManager
    builder = ContextBuilderManager(char_limit=24_000)
    monkeypatch.setattr(builder, 'collect', lambda *args, **kwargs: ({}, [], [], {}))
    snapshot = SimpleNamespace(context_categories=[], payload={'data': {'web_search': {'pages': ['old body']}}})
    assert builder.compare_with_current(None, snapshot) == ([], [])


def evidence():
    return {"query": PUBLIC_QUERY, "pages": [{"url": PAGE_URL, "title": "공개 채용",
        "published_at": None, "retrieved_at": "2026-10-18T00:00:00+00:00",
        "content_hash": "synthetic-web-content", "excerpts": [EXCERPT]}],
        "data_quality_flags": []}


def create_web(client, **overrides):
    response = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "web-first", "message": "검색 결과를 알려줘.", "depth": "auto",
        "web_search": True, "web_query": f"  {PUBLIC_QUERY}  ", **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def complete(client, database, run):
    assert asyncio.run(process_one(database))
    return client.get(f"/api/advisor/runs/{run['id']}").json()


def mock_search(monkeypatch, calls):
    async def search(self, query):
        calls.append(query)
        return evidence()
    monkeypatch.setattr(WebSearchService, "search", search)


def test_public_query_collects_body_into_model_and_saved_inspector(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    calls = []
    mock_search(monkeypatch, calls)
    secret = "합성 비공개 개인 이력"
    with database.session() as session:
        session.add(AdvisorMessage(conversation_id=1, role="user", content=secret, status="complete"))
        session.commit()
    provider.replies.append({**FINAL, "answer": f"원격 근무와 서버 개발 경험을 요구합니다. [출처]({PAGE_URL})"})
    run = create_web(client, message=f"{secret}와 비교할 공개 정보를 검색해줘.")
    done = complete(client, database, run)
    assert done["status"] == "completed", done
    assert calls == [PUBLIC_QUERY]
    assert len(provider.requests) == 1
    assert EXCERPT in json.dumps(provider.requests[0].input, ensure_ascii=False)
    assert done["result"]["context"]["web_sources"][0]["url"] == PAGE_URL
    # Digits in an actual source URL must survive numeric-answer validation.
    assert PAGE_URL in done["result"]["answer"]
    with database.session() as session:
        snapshot = session.get(ContextSnapshot, done["result"]["context_snapshot_id"])
        page = snapshot.payload["data"]["web_search"]["pages"][0]
        assert page["excerpts"] == [EXCERPT]
        assert page["untrusted_external_content"] is True


def test_deep_consultation_keeps_web_evidence_through_plan_and_review(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    calls = []
    mock_search(monkeypatch, calls)
    provider.replies.extend([PLAN, REVIEW, {**FINAL, "answer": f"공개 채용 본문입니다. [출처]({PAGE_URL})"}])
    done = complete(client, database, create_web(client, depth="deep"))
    assert done["status"] == "completed", done
    assert calls == [PUBLIC_QUERY]
    assert len(provider.requests) == 3
    assert all(EXCERPT in json.dumps(request.input, ensure_ascii=False) for request in provider.requests)
    assert done["result"]["context"]["web_sources"][0]["url"] == PAGE_URL


def test_legacy_single_response_cannot_bypass_web_citation_validation(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    mock_search(monkeypatch, [])
    run = create_web(client)
    with database.session() as session:
        stored = session.get(AdvisorRun, run["id"])
        stored.runtime_metadata = {**(stored.runtime_metadata or {}), "single_response": True}
        session.commit()
    provider.replies.append({**FINAL, "answer": "출처 없는 웹 답변"})
    done = complete(client, database, run)
    assert done["status"] in {"blocked", "failed"}, done
    assert done["result"] is None
    events = client.get(f"/api/advisor/runs/{run['id']}/events").text
    assert "출처 없는 웹 답변" not in events


def test_direct_legacy_ask_preserves_snapshot_events_and_structured_proposals(runtime_env, monkeypatch):
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.schema.advisor_schema import AskRequest
    _, database, provider = runtime_env
    mock_search(monkeypatch, [])
    answer = f"공개 채용을 확인했습니다. [출처]({PAGE_URL})"
    provider.replies.append({"answer": answer,
        "proposals": [{"action": "create_task", "payload": {"title": "공고 검토"}, "rationale": "공개 공고 확인"}],
        "memories": [{"kind": "preference", "content": "합성 원격 근무 선호"}]})
    async def collect():
        with database.session() as session:
            return [event async for event in advisor_manager.ask(session,
                session.get(AdvisorConversation, 1), "검색해줘",
                AskRequest(message="검색해줘", web_search=True, web_query=PUBLIC_QUERY).options())]
    events = asyncio.run(collect())
    assert [event["type"] for event in events] == ["context", "delta", "done"], events
    assert " ".join(events[1]["text"].split()) == answer
    assert events[-1]["proposals"][0]["payload"]["title"] == "공고 검토"
    assert events[-1]["memory_proposals"][0]["content"] == "합성 원격 근무 선호"
    with database.session() as session:
        messages = session.scalars(select(AdvisorMessage).order_by(AdvisorMessage.id)).all()
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].context_snapshot_id == messages[1].context_snapshot_id == events[-1]["context_snapshot_id"]
        assert messages[0].context_snapshot_id is not None
        assert messages[1].content == events[1]["text"]


def test_web_budget_trimming_preserves_source_and_reports_omission():
    from types import SimpleNamespace
    from app.modules.advisor.runtime.web import merge_web_sources
    page = {**evidence()["pages"][0], "ref": "web:synthetic", "excerpts": [EXCERPT * 300]}
    source = SimpleNamespace(payload={"data": {"web_search": {"query": PUBLIC_QUERY, "pages": [page]}}},
                             data_quality_flags=[])
    payload = {"data": {"private_constraint": "개인 제약 유지"}, "data_quality_flags": []}
    bounded = merge_web_sources(payload, [source], 2200)
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))) <= 2200
    assert bounded["data"]["private_constraint"] == "개인 제약 유지"
    assert bounded["data"]["web_search"]["pages"][0]["url"] == PAGE_URL
    assert any(flag["code"] == "web_excerpts_trimmed" for flag in bounded["data_quality_flags"])
    assert page["excerpts"] == [EXCERPT * 300]


def test_inherited_web_evidence_is_historical_until_collected_again():
    from decimal import Decimal
    from types import SimpleNamespace
    from app.modules.advisor.runtime.graph import numeric_values
    from app.modules.advisor.runtime.web import merge_web_sources
    page = {**evidence()["pages"][0], "ref": "web:stable", "excerpts": ["공개 지표는 73입니다."]}
    section = {"data": {"web_search": {"query": PUBLIC_QUERY, "pages": [page]}}}
    inherited = SimpleNamespace(payload=section, data_quality_flags=[])
    payload = {"data": {}, "data_quality_flags": []}
    old = merge_web_sources(payload, [inherited], 10000)["data"]["web_search"]["pages"][0]
    assert old["historical"] is True
    assert numeric_values(old) == set()
    fresh = SimpleNamespace(payload={**section, "web_research_only": True}, data_quality_flags=[])
    for sources in ([inherited, fresh], [fresh, inherited]):
        renewed = merge_web_sources(payload, sources, 10000)["data"]["web_search"]["pages"][0]
        assert renewed["historical"] is False
        assert Decimal(73) in numeric_values(renewed)


@pytest.mark.parametrize("answer", ["본문을 확인했습니다.", "[출처](https://invented.example/fake)",
    f"증가율은 876543219%입니다 [출처]({PAGE_URL})"])
def test_web_answer_requires_a_collected_source(runtime_env, monkeypatch, answer):
    client, database, provider = runtime_env
    mock_search(monkeypatch, [])
    provider.replies.append({**FINAL, "answer": answer})
    done = complete(client, database, create_web(client))
    assert done["status"] in {"blocked", "failed"}, done
    assert done["result"] is None
    with database.session() as session:
        assert not session.scalars(select(AdvisorMessage).where(AdvisorMessage.role == "assistant")).all()


def test_raw_web_artifact_is_not_a_conversation_routing_snapshot(runtime_env):
    from app.modules.advisor.runtime.web import save_web_snapshot
    from app.modules.crud import context_snapshot_handler
    _, database, _ = runtime_env
    with database.session() as session:
        assert context_snapshot_handler.get_latest_for_conversation(session, 1) is None
        source_id = save_web_snapshot(session, 1, evidence())
        session.commit()
        assert session.get(ContextSnapshot, source_id).payload["web_research_only"] is True
        assert context_snapshot_handler.get_latest_for_conversation(session, 1) is None


def test_disabled_search_never_sends_even_a_present_query(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    calls = []
    mock_search(monkeypatch, calls)
    provider.replies.append(FINAL)
    done = complete(client, database, create_web(client, web_search=False, message="안녕"))
    assert done["status"] == "completed", done
    assert not calls
    assert len(provider.requests) == 1


def test_missing_api_key_failure_does_not_fall_back_to_model(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    async def fail(self, query):
        raise WebSearchError("web_search_not_configured", "웹 검색 설정이 필요합니다.")
    monkeypatch.setattr(WebSearchService, "search", fail)
    done = complete(client, database, create_web(client))
    assert done["status"] in {"blocked", "failed"}, done
    assert not provider.requests
    assert done["result"] is None


def test_preview_has_no_web_call_or_persisted_evidence(runtime_env, monkeypatch):
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.schema.advisor_schema import AskRequest
    client, database, provider = runtime_env
    calls = []
    mock_search(monkeypatch, calls)
    options = AskRequest(message="검색해줘", web_search=True, web_query=PUBLIC_QUERY).options()
    with database.session() as session:
        before = len(session.scalars(select(ContextSnapshot)).all())
        preview = advisor_manager.preview(session, "검색해줘", session.get(AdvisorConversation, 1), options)
        assert preview["context_snapshot_id"] is None
        assert len(session.scalars(select(ContextSnapshot)).all()) == before
    assert not calls and not provider.requests


def test_cancel_during_collection_discards_returned_evidence(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    run = create_web(client)
    async def search(self, query):
        response = client.post(f"/api/advisor/runs/{run['id']}/cancel")
        assert response.status_code == 200
        with database.session() as session:
            assert session.get(AdvisorRun, run["id"]).runtime_metadata["model_inflight"] is True
        return evidence()
    monkeypatch.setattr(WebSearchService, "search", search)
    done = complete(client, database, run)
    assert done["status"] == "cancelled", done
    assert not provider.requests
    with database.session() as session:
        assert not session.scalars(select(ContextSnapshot)).all()


def test_uncertain_web_call_is_not_replayed_after_lease_expiry(runtime_env, monkeypatch):
    client, database, provider = runtime_env
    run = create_web(client)
    calls = []
    async def interrupt():
        entered = asyncio.Event()
        async def search(self, query):
            calls.append(query)
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(WebSearchService, "search", search)
        task = asyncio.create_task(process_one(database))
        await asyncio.wait_for(entered.wait(), timeout=10)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    asyncio.run(interrupt())
    with database.session() as session:
        stored = session.get(AdvisorRun, run["id"])
        assert stored.runtime_metadata["model_inflight"] is True
        stored.lease_until = utcnow() - timedelta(seconds=1)
        session.commit()
    assert not asyncio.run(process_one(database))
    assert client.get(f"/api/advisor/runs/{run['id']}").json()["status"] == "blocked"
    assert calls == [PUBLIC_QUERY] and not provider.requests


@pytest.mark.parametrize("query", [None, "", "   "])
def test_enabled_search_requires_explicit_nonblank_query(runtime_env, query):
    client, _, _ = runtime_env
    response = client.post("/api/advisor/conversations/1/runs", json={
        "request_id": "missing-public-query", "message": "검색해줘", "web_search": True, "web_query": query})
    assert response.status_code == 422
