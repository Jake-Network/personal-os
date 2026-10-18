"""Privacy settings govern the whole outbound request, including replayed conversation history."""
import asyncio
import json

import pytest

from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.context.history_privacy_manager import HistoryPrivacyManager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.crud.advisor_handler import context_snapshot_handler, message_handler
from app.modules.database.model import AdvisorMessage
from app.modules.llm.errors import AdvisorError
from app.modules.advisor.types import AskOptions

# Values that only exist in the financial category of the `seeded` fixture or in answers built on it.
FINANCIAL_SECRETS = ("12000000", "12,000,000", "급여통장", "9,100,000", "9100000", "신용대출")
FIRST_ANSWER = "급여통장 잔고 12,000,000원 기준 순자산은 9,100,000원입니다."


def sse(client, conversation_id: int, message: str) -> list[dict]:
    res = client.post(f"/api/advisor/conversations/{conversation_id}/messages", json={"message": message})
    assert res.status_code == 200
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def outbound(request) -> str:
    return json.dumps([request.instructions, request.input], ensure_ascii=False)


def run(session, conv, text, options=None):
    async def collect():
        return [e async for e in advisor_manager.ask(session, conv, text, options)]
    return asyncio.run(collect())


def test_disabling_financial_after_a_consultation_withholds_old_turns(client, seeded, fake_provider):
    """Integration path: API consult → privacy API → follow-up; inspect what the provider received."""
    conv = client.post("/api/advisor/conversations", json={"title": "재무"}).json()
    fake_provider.reply = FIRST_ANSWER
    first = sse(client, conv["id"], "현재 내 순자산은?")
    assert first[-1]["type"] == "done"
    assert "12000000" in outbound(fake_provider.requests[0])  # financial data was shared while allowed

    assert client.put("/api/settings/privacy", json={"excluded_categories": ["financial"]}).status_code == 200
    fake_provider.reply = "알겠습니다."
    events = sse(client, conv["id"], "그럼 그 다음은?")
    assert events[0]["history_withheld_messages"] == 2
    assert events[0]["history_withheld_categories"] == ["financial"]

    sent = outbound(fake_provider.requests[1])
    for secret in FINANCIAL_SECRETS:
        assert secret not in sent, secret
    assert "현재 내 순자산은?" not in sent  # the restricted turn's question is withheld with its answer
    roles = [i["role"] for i in fake_provider.requests[1].input]
    assert roles == ["developer", "developer", "user"]  # withheld-history notice, package, question
    package = json.loads(fake_provider.requests[1].input[1]["content"].split("\n", 1)[1])
    assert "financial" not in package["categories"]


def test_taint_propagates_to_later_turns_that_saw_restricted_history(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = FIRST_ANSWER
    run(seeded, conv, "현재 내 순자산은?")  # financial + investment
    fake_provider.reply = "면접 준비하는 동안 12,000,000원이면 충분합니다."  # career-only turn repeats a balance
    run(seeded, conv, "면접 준비 계획 세워줘")
    privacy_manager.set_excluded(seeded, [Category.FINANCIAL])
    fake_provider.reply = "ok"
    run(seeded, conv, "면접은 언제야?")
    sent = outbound(fake_provider.requests[2])
    assert "12,000,000" not in sent and "면접 준비 계획 세워줘" not in sent


def test_clean_prefix_before_the_restricted_turn_is_kept(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = "면접 답변"
    run(seeded, conv, "면접 준비 계획 세워줘")  # career/calendar/goals
    fake_provider.reply = FIRST_ANSWER
    run(seeded, conv, "현재 내 순자산은?")
    privacy_manager.set_excluded(seeded, [Category.FINANCIAL])
    run(seeded, conv, "면접은 언제야?")
    replayed = [(i["role"], i["content"]) for i in fake_provider.requests[2].input if i["role"] != "developer"]
    assert replayed == [("user", "면접 준비 계획 세워줘"), ("assistant", "면접 답변"), ("user", "면접은 언제야?")]


def test_unrelated_exclusion_keeps_full_history(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = FIRST_ANSWER
    run(seeded, conv, "현재 내 순자산은?")
    privacy_manager.set_excluded(seeded, [Category.HEALTH])
    run(seeded, conv, "그럼 그 다음은?")
    roles = [i["role"] for i in fake_provider.requests[1].input]
    assert roles == ["user", "assistant", "developer", "user"]


def test_per_request_exclusion_also_filters_history(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = FIRST_ANSWER
    run(seeded, conv, "현재 내 순자산은?")
    run(seeded, conv, "면접 일정은?", AskOptions(exclude=frozenset({Category.FINANCIAL})))
    assert "12,000,000" not in outbound(fake_provider.requests[1])


def test_turn_with_deleted_snapshot_is_never_replayed(seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = "목표 답변"
    done = run(seeded, conv, "목표 우선순위 정리해줘")[-1]  # goals only
    context_snapshot_handler.delete(seeded, context_snapshot_handler.get(seeded, done["context_snapshot_id"]))
    seeded.commit()
    fake_provider.reply = "ok"
    run(seeded, conv, "목표는?")
    assert "목표 답변" not in outbound(fake_provider.requests[1])  # deleted context is purged, even unrestricted
    privacy_manager.set_excluded(seeded, [Category.HEALTH])
    run(seeded, conv, "목표는?")
    assert "목표 답변" not in outbound(fake_provider.requests[2])


def test_preview_reports_withheld_history(client, seeded, fake_provider):
    conv = advisor_manager.create_conversation(seeded, "x")
    fake_provider.reply = FIRST_ANSWER
    run(seeded, conv, "현재 내 순자산은?")
    privacy_manager.set_excluded(seeded, [Category.FINANCIAL])
    preview = client.post("/api/advisor/context/preview",
                          json={"message": "그럼?", "conversation_id": conv.id}).json()
    assert preview["history_withheld_messages"] == 2


def test_decide_is_a_pure_prefix_rule():
    def msg(i, snap):
        return AdvisorMessage(id=i, conversation_id=1, role="user" if i % 2 else "assistant",
                              content=str(i), status="complete", context_snapshot_id=snap)

    cats = {"a": frozenset({Category.GOALS}), "b": frozenset({Category.FINANCIAL}),
            "c": frozenset({Category.CAREER})}
    messages = [msg(1, "a"), msg(2, "a"), msg(3, "b"), msg(4, "b"), msg(5, "c"), msg(6, "c")]
    d = HistoryPrivacyManager.decide(messages, cats, frozenset({Category.FINANCIAL}))
    assert [m.id for m in d.kept] == [1, 2] and d.withheld_ids == [3, 4, 5, 6]
    assert HistoryPrivacyManager.decide(messages, cats, frozenset()).withheld_ids == []


def test_outbound_guard_fails_closed_on_excluded_package_category(seeded):
    from app.modules.context.types import HistoryDecision
    from app.modules.context.types import ContextPackage

    package = ContextPackage("s", {}, False, ["financial"], [], {}, [], [])
    with pytest.raises(AdvisorError):
        advisor_manager.build_request("m", HistoryDecision([], [], []), package, "q",
                                      frozenset({Category.FINANCIAL}))


def test_history_limit_still_applies_after_filtering(seeded, fake_provider, monkeypatch):
    monkeypatch.setattr(advisor_manager, "history_limit", 2)
    conv = advisor_manager.create_conversation(seeded, "x")
    for q in ("목표 1", "목표 2", "목표 3"):
        run(seeded, conv, q)
    assert len(message_handler.get_replayable_before(seeded, conv.id, None)) == 6
    replayed = [i for i in fake_provider.requests[-1].input if i["role"] in ("user", "assistant")]
    assert len(replayed) == 3  # 2 history messages + the new question
