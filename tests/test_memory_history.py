"""Payload-level regressions for memory versions, live provenance and request budgets."""
import asyncio
import json
from datetime import UTC, datetime

from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.memory_history_manager import memory_history_manager, relevant_memories, source_allowed
from app.modules.advisor.memory_manager import memory_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.database.model import PersonalMemory
from app.schema.advisor_schema import MemoryCreate, MemoryRevisionCreate, SummaryCreate


def ask(session, conversation, query):
    async def run():
        return [e async for e in advisor_manager.ask(session, conversation, query)]
    return asyncio.run(run())


def payload(provider):
    return json.dumps(provider.requests[-1].input, ensure_ascii=False)


def test_revision_history_and_local_only_revocation(session, fake_provider):
    memory = memory_manager.create(session, MemoryCreate(kind="constraint", content="REVISION_SECRET"))
    conv = advisor_manager.create_conversation(session, "revision")
    assert ask(session, conv, "현재 제약은?")[-1]["type"] == "done"
    assert "REVISION_SECRET" in payload(fake_provider)
    revision = memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(
        expected_revision=0, kind="constraint", content="REPLACED_SECRET", external_allowed=False))
    assert revision.revision == 1
    assert [r.content for r in memory_history_manager.revisions(session, memory.id)] == ["REVISION_SECRET", "REPLACED_SECRET"]
    assert ask(session, conv, "제약을 다시 확인")[-1]["type"] == "done"
    assert "REVISION_SECRET" not in payload(fake_provider)
    assert "REPLACED_SECRET" not in payload(fake_provider)


def test_memory_source_cannot_reenter_after_category_revocation(session, fake_provider):
    conv = advisor_manager.create_conversation(session, "financial")
    fake_provider.reply = '학습\n```memory\n{"kind":"constraint","content":"DERIVED_FINANCE_SECRET"}\n```'
    ask(session, conv, "재무 자산 상태")
    # Store a derived record with the exact source, as extraction does.
    message = conv.messages[-1]
    memory = PersonalMemory(kind="constraint", content="DERIVED_FINANCE_SECRET", status="confirmed", source="advisor", source_message_id=message.id)
    session.add(memory)
    session.commit()
    privacy_manager.set_excluded(session, [Category.FINANCIAL])
    fresh = advisor_manager.create_conversation(session, "career")
    ask(session, fresh, "면접 제약 검토")
    assert "DERIVED_FINANCE_SECRET" not in payload(fake_provider)


def test_revision_validity_and_scope(session):
    memory = memory_manager.create(session, MemoryCreate(kind="constraint", content="original"))
    memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=0,
        kind="constraint", content="future project", scope="project-a",
        valid_from=datetime(2030, 1, 1, tzinfo=UTC), valid_until=datetime(2031, 1, 1, tzinfo=UTC)))
    at = datetime(2030, 6, 1, tzinfo=UTC)
    all_categories = frozenset(Category)
    assert relevant_memories(session, "project-b", all_categories, at) == []
    selected = relevant_memories(session, "project-a", all_categories, at)
    assert selected[0][1].content == "future project"


def test_cross_conversation_retrieval_and_deleted_source(session, fake_provider):
    old = advisor_manager.create_conversation(session, "past")
    fake_provider.reply = "projectalpha 과거 결정은 유지한다."
    ask(session, old, "projectalpha 경험 기록")
    new = advisor_manager.create_conversation(session, "new")
    ask(session, new, "projectalpha 과거 경험은?")
    assert "과거 결정은 유지한다" in payload(fake_provider)
    advisor_manager.delete_conversation(session, old.id)
    ask(session, new, "projectalpha 후속 질문")
    # The second turn's reply is derived from the now-deleted past conversation too.
    assert "과거 결정은 유지한다" not in payload(fake_provider)


def test_summary_draft_provenance(session, fake_provider):
    conversation = advisor_manager.create_conversation(session, "summary")
    ask(session, conversation, "기록 요약")
    draft = memory_history_manager.summarize(session, conversation.id, SummaryCreate())
    assert draft.status == "draft"
    assert len(draft.source_references) == 2
    assert source_allowed(session, [{"table": "conversation_summaries", "id": draft.id}])
    source = session.get(__import__('app.modules.database.model', fromlist=['AdvisorMessage']).AdvisorMessage, draft.first_message_id)
    source.context_purged = True
    session.commit()
    assert not source_allowed(session, [{"table": "conversation_summaries", "id": draft.id}])


def test_total_request_budget_rejects_before_send(session, fake_provider, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(type(settings), "request_char_limit", property(lambda self: 200))
    conversation = advisor_manager.create_conversation(session, "budget")
    events = ask(session, conversation, "hello")
    assert events[-1]["type"] == "error"
    assert not fake_provider.requests
    assert conversation.messages == []


def test_index_hybrid_semantic_retrieval_and_fallback(session, fake_provider, monkeypatch):
    from app.modules.advisor.memory_history_manager import index_history
    from app.modules.documents import embedding
    from app.config import settings
    monkeypatch.setattr(type(settings), "embedding_dimensions", property(lambda self: 2), raising=False)
    async def vectors(texts):
        return [[1., 0.] for _ in texts]
    monkeypatch.setattr(embedding, "embed_texts", vectors)
    monkeypatch.setattr(embedding, "embed_query", lambda query: [1., 0.])
    first = advisor_manager.create_conversation(session, "first")
    fake_provider.reply = "퇴사 결정에서 안전한 생활비 확보"
    ask(session, first, "작년 경험")
    assert asyncio.run(index_history(session))["indexed"] == 2
    second = advisor_manager.create_conversation(session, "second")
    ask(session, second, "totally unrelated keyword")
    assert "안전한 생활비 확보" in payload(fake_provider)
    def unavailable(query):
        raise OSError("local embedder offline")
    monkeypatch.setattr(embedding, "embed_query", unavailable)
    third = advisor_manager.create_conversation(session, "third")
    events = ask(session, third, "생활비 확보")
    assert "안전한 생활비 확보" in payload(fake_provider)
    assert any(f["code"] == "history_embedding_unavailable" for f in events[0]["data_quality_flags"])


def test_revision_cannot_drop_inherited_provenance(session, fake_provider):
    from app.modules.database.model import AdvisorMessage
    conversation = advisor_manager.create_conversation(session, "source")
    ask(session, conversation, "재무 상태")
    source = conversation.messages[-1]
    memory = PersonalMemory(kind="constraint", content="derived", status="confirmed", source="advisor", source_message_id=source.id)
    session.add(memory)
    session.commit()
    revision = memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=0,
        kind="constraint", content="updated", source_references=[]))
    assert any(ref["table"] == "advisor_messages" and ref["id"] == source.id for ref in revision.source_references)
    source.context_purged = True
    session.commit()
    assert not source_allowed(session, [{"table": "memory_revisions", "id": revision.id}])


def test_live_request_check_rejects_new_revocation(session, fake_provider):
    from app.modules.advisor.memory_history_manager import require_live_request_sources
    from app.modules.advisor.requests import build_request
    from app.modules.advisor.types import AskOptions
    from app.modules.llm.errors import AdvisorError
    import pytest
    memory = memory_manager.create(session, MemoryCreate(kind="constraint", content="SECRET"))
    route, package, options, prepared = advisor_manager.prepare_context(session, "제약", None, AskOptions())
    request = build_request("fake", prepared.decision(), package, "제약", frozenset())
    session.commit()
    memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=0,
        kind="constraint", content="SECRET", external_allowed=False))
    with pytest.raises(AdvisorError):
        require_live_request_sources(session, request)


def test_essential_memory_constraints_never_trimmed_or_dropped(session):
    import pytest
    from app.modules.context.budget import fit_to_budget
    from app.modules.context.errors import BudgetExceeded
    original = "critical " * 2000
    body = {"data": {"get_profile": {"confirmed_memories": [{"kind": "constraint", "content": original}]}}, "data_quality_flags": []}
    with pytest.raises(BudgetExceeded):
        fit_to_budget(body, "", 1000)
    fitted = fit_to_budget(body, "", 20000)
    assert fitted["data"]["get_profile"]["confirmed_memories"][0]["content"] == original


def test_local_only_account_omits_aggregate_and_derived_history(seeded, fake_provider):
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.database.model import Account
    from sqlalchemy import select
    conv = advisor_manager.create_conversation(seeded, "account privacy")
    ask(seeded, conv, "순자산 계좌")
    assert "급여통장" in payload(fake_provider)
    account = seeded.scalar(select(Account).where(Account.name == "급여통장"))
    set_record_policy(seeded, "accounts", account.id, False)
    events = ask(seeded, conv, "순자산 계좌 다시 확인")
    assert "급여통장" not in payload(fake_provider)
    assert "12000000" not in payload(fake_provider)
    assert any(flag["code"] == "records_excluded_by_user" for flag in events[0]["data_quality_flags"])
    # Local dashboard/database remains intact after external-sharing revocation.
    assert seeded.get(Account, account.id).name == "급여통장"
    from app.modules.dashboard.dashboard_manager import dashboard_manager
    local = dashboard_manager.summary(seeded)
    assert "급여통장" in json.dumps(local, ensure_ascii=False)
    assert "get_accounts_summary" in local["data"]
    assert not any(f["code"] == "records_excluded_by_user" for f in local["data_quality_flags"])


def test_record_sharing_api_does_not_mutate_source(client, session):
    memory = memory_manager.create(session, MemoryCreate(kind="constraint", content="private record"))
    result = client.put(f"/api/settings/privacy/records/personal_memories/{memory.id}", json={"external_allowed": False})
    assert result.status_code == 200
    assert client.get("/api/settings/privacy/records").json()["local_only_records"]["personal_memories"] == [str(memory.id)]
    assert session.get(PersonalMemory, memory.id).content == "private record"


def test_conversation_pagination_links_and_message_search(client):
    first = client.post("/api/advisor/conversations", json={"title": "first"}).json()
    second = client.post("/api/advisor/conversations", json={"title": "second"}).json()
    assert client.post(f"/api/advisor/conversations/{first['id']}/links", json={"kind": "company", "target": "Example"}).status_code == 201
    assert [c["id"] for c in client.get("/api/advisor/conversations?company=Example").json()] == [first["id"]]
    assert len(client.get("/api/advisor/conversations?limit=1&offset=1").json()) == 1
    assert client.get(f"/api/advisor/conversations/{second['id']}/messages?limit=1").json() == []
    assert client.get("/api/advisor/conversations?limit=0").status_code == 422


def test_deleted_financial_record_withholds_derived_history(seeded, fake_provider):
    from app.modules.database.model import Account
    from sqlalchemy import select
    conv = advisor_manager.create_conversation(seeded, "delete source")
    fake_provider.reply = "급여통장 잔고의 근거에서 파생된 고유결과"
    ask(seeded, conv, "순자산 계좌")
    account = seeded.scalar(select(Account).where(Account.name == "급여통장"))
    seeded.delete(account)
    seeded.commit()
    fake_provider.reply = "계속"
    ask(seeded, conv, "후속 질문")
    assert "파생된 고유결과" not in payload(fake_provider)


def test_expired_revision_does_not_resurrect_superseded_memory(session):
    memory = memory_manager.create(session, MemoryCreate(kind="constraint", content="superseded"))
    memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=0,
        kind="constraint", content="temporary", valid_from=datetime(2030, 1, 1, tzinfo=UTC),
        valid_until=datetime(2031, 1, 1, tzinfo=UTC)))
    assert relevant_memories(session, "", frozenset(Category), datetime(2032, 1, 1, tzinfo=UTC)) == []


def test_explicit_past_question_uses_valid_revision_in_actual_payload(session, fake_provider):
    memory = memory_manager.create(session, MemoryCreate(kind="preference", content="current placeholder"))
    memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=0,
        kind="constraint", content="PAST_VALID_CONSTRAINT", valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_until=datetime(2023, 1, 1, tzinfo=UTC)))
    memory_history_manager.revise(session, memory.id, MemoryRevisionCreate(expected_revision=1,
        kind="constraint", content="PRESENT_VALID_CONSTRAINT", valid_from=datetime(2023, 1, 1, tzinfo=UTC)))
    conversation = advisor_manager.create_conversation(session, "past preferences")
    ask(session, conversation, "2021-06-01 당시 제약을 알려줘")
    assert "PAST_VALID_CONSTRAINT" in payload(fake_provider)
    assert "PRESENT_VALID_CONSTRAINT" not in payload(fake_provider)


def test_deleted_recreated_record_id_cannot_resurrect_old_evidence(seeded, fake_provider):
    from app.modules.crud import account_handler
    from app.modules.database.model import Account
    from sqlalchemy import select
    from decimal import Decimal
    from datetime import date
    conversation = advisor_manager.create_conversation(seeded, "reused ID")
    fake_provider.reply = "OLD_ROW_DERIVED_SECRET"
    ask(seeded, conversation, "순자산 계좌")
    account = seeded.scalar(select(Account).where(Account.name == "급여통장"))
    original_id = account.id
    account_handler.delete(seeded, account)
    seeded.commit()
    seeded.add(Account(id=original_id, name="replacement", kind="checking", currency="KRW",
        balance=Decimal(100), balance_as_of=date.today(), is_liquid=True))
    seeded.commit()
    fake_provider.reply = "new"
    ask(seeded, conversation, "순자산 계좌 다시")
    assert "OLD_ROW_DERIVED_SECRET" not in payload(fake_provider)
    assert "replacement" in payload(fake_provider)


def test_new_conversation_retrieves_summary_and_decision_and_revocation(seeded, fake_provider):
    from app.modules.advisor.memory_manager import decision_journal_manager
    from app.schema.advisor_schema import DecisionCreate
    first = advisor_manager.create_conversation(seeded, "projectalpha source")
    fake_provider.reply = "projectalpha 과거 경험 요약 근거"
    result = ask(seeded, first, "projectalpha 순자산 계좌")
    summary = memory_history_manager.summarize(seeded, first.id, SummaryCreate())
    decision = decision_journal_manager.create(seeded, DecisionCreate(title="projectalpha 결정",
        choice="ALLOWED_DECISION_CHOICE", rationale="기록된 선택", conversation_id=first.id,
        context_snapshot_id=result[-1]["context_snapshot_id"]))
    second = advisor_manager.create_conversation(seeded, "new")
    ask(seeded, second, "projectalpha 과거 결정과 경험")
    sent = payload(fake_provider)
    assert f"conversation_summaries:{summary.id}" in sent
    assert "local_extractive_draft_not_confirmed_facts" in sent
    assert f"decision_journal:{decision.id}" in sent
    assert "ALLOWED_DECISION_CHOICE" in sent
    privacy_manager.set_excluded(seeded, [Category.FINANCIAL])
    third = advisor_manager.create_conversation(seeded, "after revoke")
    ask(seeded, third, "projectalpha 과거 결정과 경험")
    sent = payload(fake_provider)
    assert f"conversation_summaries:{summary.id}" not in sent
    assert f"decision_journal:{decision.id}" not in sent
    assert "ALLOWED_DECISION_CHOICE" not in sent
