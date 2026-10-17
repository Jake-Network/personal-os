import asyncio
import json

from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.crud.advisor_handler import llm_usage_event_handler, proposed_action_handler
from app.modules.database.model import AuditLog, Task
from app.modules.llm.errors import QuotaExceeded
from app.schema.advisor_schema import AskOptions


def run(session, conv, text, options=None):
    async def collect():
        return [e async for e in advisor_manager.ask(session, conv, text, options)]
    return asyncio.run(collect())


def context_of(request) -> dict:
    dev = next(i for i in request.input if i["role"] == "developer")
    return json.loads(dev["content"].split("\n", 1)[1])


def test_ac12_net_worth_is_computed_by_backend(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "순자산")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert [e["type"] for e in events][0] == "context" and events[-1]["type"] == "done"
    worth = context_of(fake_provider.requests[0])["data"]["get_accounts_summary"]["computed"]["net_worth"]
    # 12,000,000 + 1,000 USD * 1,400 + 10 * 70,000 − 5,000,000
    assert worth["net_worth"] == "9100000.00"
    assert worth["complete"] is True


def test_ac16_empty_data_is_flagged_not_invented(session, fake_provider):
    conv = advisor_manager.create_conversation(session, "빈 DB")
    run(session, conv, "퇴사하고 3개월 쉬어도 될까?")
    codes = {f["code"] for f in context_of(fake_provider.requests[0])["data_quality_flags"]}
    assert {"no_accounts", "monthly_expense_unknown", "no_active_applications"} <= codes


def test_ac19_excluded_category_never_reaches_the_model(seeded, fake_provider):
    privacy_manager.set_excluded(seeded, [Category.INVESTMENT])
    conv = advisor_manager.create_conversation(seeded, "투자")
    run(seeded, conv, "포트폴리오가 너무 공격적인지 분석해 줘")
    sent = json.dumps([i["content"] for i in fake_provider.requests[0].input], ensure_ascii=False)
    assert "005930" not in sent and "삼성전자" not in sent
    ctx = context_of(fake_provider.requests[0])
    assert "investment" in ctx["excluded_categories"]
    assert "get_portfolio_summary" not in ctx["data"]


def test_per_request_exclusion(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    run(seeded, conv, "퇴사해도 될까", AskOptions(exclude=frozenset({Category.CAREER})))
    sent = json.dumps([i["content"] for i in fake_provider.requests[0].input], ensure_ascii=False)
    assert "레인보우로보틱스" not in sent


def test_ac13_cross_domain_question_uses_both_domains(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    run(seeded, conv, "이직하면서 3개월 쉬면 생활비가 버틸까?")
    data = context_of(fake_provider.requests[0])["data"]
    assert "get_accounts_summary" in data and "get_job_applications" in data


def test_ac15_history_is_replayed_and_snapshot_reused(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    first = run(seeded, conv, "현재 내 순자산은?")
    second = run(seeded, conv, "그럼 그 다음은?")  # no keywords → previous categories
    roles = [i["role"] for i in fake_provider.requests[1].input]
    assert roles == ["user", "assistant", "developer", "user"]
    assert second[0]["context_reused"] is True
    assert second[-1]["context_snapshot_id"] == first[-1]["context_snapshot_id"]


def test_ac17_quota_exhaustion_fails_safely_without_paid_fallback(seeded, fake_provider):
    fake_provider.error = QuotaExceeded(provider_code="subscription_sharing_usage_limit_exceeded")
    conv = advisor_manager.create_conversation(seeded, "x")
    events = run(seeded, conv, "현재 내 순자산은?")
    assert events[-1]["type"] == "error" and events[-1]["code"] == "plan_usage_limit_exceeded"
    usage = llm_usage_event_handler.get_recent(seeded)
    assert [u.outcome for u in usage] == ["quota_exceeded"]
    assert all(u.provider == "chatgpt_plan" for u in usage)


def test_proposals_require_approval_and_are_audited(seeded, fake_provider):
    fake_provider.reply = (
        "면접 준비 시간을 확보하세요.\n```proposal\n"
        '{"action": "create_task", "payload": {"title": "기술면접 준비", "due_on": "2026-10-20"}}\n```'
    )
    conv = advisor_manager.create_conversation(seeded, "x")
    done = run(seeded, conv, "면접 준비 계획")[-1]
    assert len(done["proposals"]) == 1
    assert seeded.query(Task).count() == 0  # nothing applied yet

    ref = proposal_manager.approve(seeded, done["proposals"][0]["id"])
    assert seeded.get(Task, ref["id"]).title == "기술면접 준비"
    assert proposed_action_handler.get(seeded, done["proposals"][0]["id"]).status == "approved"
    assert seeded.query(AuditLog).filter(AuditLog.action == "approve.create_task").count() == 1


def test_financial_writes_cannot_be_proposed(seeded, fake_provider):
    fake_provider.reply = '```proposal\n{"action": "update_account", "payload": {"balance": 1}}\n```'
    conv = advisor_manager.create_conversation(seeded, "x")
    assert run(seeded, conv, "잔고 바꿔줘")[-1]["proposals"] == []


def test_failed_turn_is_not_replayed_as_history(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.error = QuotaExceeded()
    run(seeded, conv, "현재 내 순자산은?")
    fake_provider.error = None
    run(seeded, conv, "현재 내 순자산은?")
    assert [i["role"] for i in fake_provider.requests[1].input] == ["developer", "user"]


def test_client_disconnect_keeps_partial_answer_as_incomplete(seeded, fake_provider):
    from app.modules.crud.advisor_handler import message_handler

    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = "a" * 40

    async def go():
        gen = advisor_manager.ask(seeded, conv, "현재 내 순자산은?")
        async for event in gen:
            if event["type"] == "delta":
                break
        await gen.aclose()  # what Starlette does when the browser goes away
    asyncio.run(go())

    msgs = message_handler.get_by_conversation(seeded, conv.id)
    assert [(m.role, m.status) for m in msgs] == [("user", "failed"), ("assistant", "incomplete")]
