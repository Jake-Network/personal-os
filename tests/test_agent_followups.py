"""Procedure evidence boundaries, session search, batch approvals and usage-driven learning.

Assertions about sharing inspect what the fake provider actually received.
"""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update

from app.modules.agent import briefing, reflection
from app.modules.context.record_privacy import set_record_policy
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import (
    AdvisorConversation, AdvisorMessage, AdvisorRecommendation, ContextSnapshot, InboxItem, LLMUsageEvent,
    PersonalMemory, PlaybookRevision, PlaybookUsage, ProposedAction,
)
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.review_jobs import BackgroundJob, JobSchedule
from test_agent_loop import FINAL, PLAN, REFLECTION, add_playbook, consult, env, outbound, package  # noqa: F401

REVIEW = {"valid": True, "issues": [], "retry_tasks": []}


def answer_message(database, run):
    with database.session() as session:
        return session.get(AdvisorMessage, session.get(AdvisorRun, run["id"]).assistant_message_id)


# --- a procedure is not personal evidence ---------------------------------------------------


def test_deleting_a_used_playbook_keeps_the_answers_evidence(env):
    client, database, provider = env
    playbook = add_playbook(client)
    run, requests = consult(client, database, provider, "used", "이직 준비해도 될까?")
    assert "data" in package(requests[0]) and package(requests[0])["data"]["playbooks"]["items"]
    message = answer_message(database, run)
    assert client.delete(f"/api/playbooks/{playbook['id']}").status_code == 204
    with database.session() as session:
        snapshot = session.get(ContextSnapshot, message.context_snapshot_id)
        assert not snapshot.payload.get("source_purged")
        assert session.get(AdvisorMessage, message.id).context_purged is False
        ref = [{"table": "advisor_messages", "id": message.id}]
        assert source_allowed(session, ref)
        # The deleted procedure's origin categories still taint what used it.
        from app.enums.context_category import Category
        assert not source_allowed(session, ref, frozenset({Category.CAREER}))
    # A later turn still replays the answer, and the deleted procedure is never sent again.
    _, requests = consult(client, database, provider, "after-delete", "이직 준비 이어서 정리해 줘")
    assert "합성 상담 결과입니다." in outbound(requests[0])
    assert "생활비로 쓸 수 있는 현금과 런웨이를 확인한다" not in outbound(requests[0])


def test_a_catalog_listing_is_not_evidence_of_later_answers(env):
    from app.modules.database.model import Playbook
    client, database, provider = env
    playbook = add_playbook(client, slug="일반-절차", triggers=["카탈로그전용"])
    run, requests = consult(client, database, provider, "listed", "현재 상황을 심층 분석해 줘",
                            replies=(PLAN, REVIEW, FINAL), depth="deep")
    assert run["status"] == "completed", run
    assert package(requests[0])["data"]["playbook_catalog"]["items"]
    message = answer_message(database, run)
    with database.session() as session:
        plan_snapshot = session.get(ContextSnapshot, requests[0].source_snapshot_id)
        offered = [ref for ref in plan_snapshot.record_references if ref["table"] == "playbook_revisions"]
        assert offered and all(ref["role"] == "catalog" for ref in offered)
        session.get(Playbook, playbook["id"]).external_allowed = False
        session.commit()
        assert source_allowed(session, [{"table": "advisor_messages", "id": message.id}])


# --- worker and run-now state -----------------------------------------------------------------


def test_the_job_worker_leaves_interrupted_reflections_to_their_own_warning(env):
    from app.modules.crud import review_jobs_handler
    client, database, provider = env
    run, _ = consult(client, database, provider, "interrupted", "퇴사해도 될까?")
    response = client.post(f"/api/advisor/messages/{run['result']['message_id']}/reflect", json={"request_id": "x"})
    now = datetime.now(UTC)
    with database.session() as session:
        job_id = response.json()["id"]
        session.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(
            status="running", attempts=1, lease_owner="gone", lease_until=now - timedelta(seconds=1)))
        session.commit()
        review_jobs_handler.expire_exhausted(session, now)
        session.commit()
        assert session.get(BackgroundJob, job_id).status == "running"
        assert reflection.claim(session, "next") is None
        session.commit()
        job = session.get(BackgroundJob, job_id)
        assert (job.status, job.last_error) == ("failed", "interrupted") and job.completed_at is not None
        assert session.scalar(select(InboxItem).where(InboxItem.dedupe_key == f"reflection-failed:{job_id}"))


def test_run_now_on_a_paused_briefing_keeps_the_users_pause(env):
    from app.modules.database.model import Interview, JobApplication
    client, database, provider = env
    with database.session() as session:
        application = JobApplication(company="합성로보틱스", role="합성 엔지니어", status="interviewing")
        session.add(application)
        session.flush()
        session.add(Interview(application_id=application.id, stage="1차", starts_at=datetime.now(UTC) + timedelta(days=2)))
        session.commit()
    created = client.post("/api/jobs/briefings", json={"name": "아침 브리핑", "local_time": "08:00",
                                                       "llm_enabled": True, "enabled": True}).json()
    assert client.patch(f"/api/jobs/schedules/{created['id']}", json={"enabled": False}).status_code == 200
    result = client.post(f"/api/jobs/briefings/{created['id']}/run-now", json={"request_id": "paused"}).json()
    assert result["state"] == "signals" and result["model"] == "schedule_disabled"
    with database.session() as session:
        schedule = session.get(JobSchedule, created["id"])
        assert schedule.paused_reason is None
        assert session.scalar(select(InboxItem).where(InboxItem.kind == "schedule_paused")) is None
    assert not provider.requests


def test_activity_counts_only_provider_failures_as_failed(env):
    client, database, provider = env
    with database.session() as session:
        for outcome in ("completed", "cancelled", "blocked", "failed", "quota_exceeded"):
            session.add(LLMUsageEvent(provider="chatgpt_plan", model="fake-model", outcome=outcome))
        session.commit()
    activity = client.get("/api/agent/activity").json()
    assert activity["model_calls"] == 5 and activity["failed_calls"] == 2


def test_plan_without_a_catalog_does_not_report_a_refused_procedure(env):
    client, database, provider = env
    chosen = add_playbook(client)
    run, _ = consult(client, database, provider, "explicit-deep", "이직 커리어 장단점을 심층 분석해 줘",
                     replies=({**PLAN, "playbooks": ["이직-점검"]}, REVIEW, FINAL), depth="deep",
                     playbook_ids=[chosen["id"]])
    assert run["status"] == "completed", run
    assert "승인된 플레이북 목록에 없는 절차는 사용하지 않았습니다." not in run["result"]["limitations"]


# --- reflection on a withheld source --------------------------------------------------------


def test_reflection_on_a_withheld_answer_cites_only_current_evidence(env):
    client, database, provider = env
    run, _ = consult(client, database, provider, "withheld", "퇴사하고 이직 준비해도 될까?")
    message = answer_message(database, run)
    with database.session() as session:
        set_record_policy(session, "advisor_messages", message.id, False)
    provider.replies.append(REFLECTION)
    response = client.post(f"/api/advisor/messages/{message.id}/reflect", json={"request_id": "withheld-learn"})
    assert asyncio.run(reflection.process_one(database))
    assert "합성 상담 결과입니다." not in outbound(provider.requests[-1])
    with database.session() as session:
        job = session.get(BackgroundJob, response.json()["id"])
        assert job.status == "completed" and job.result["source_withheld"] is True
        assert job.result["memory_ids"] == []
        revision = session.get(PlaybookRevision, job.result["playbook_revision_ids"][0])
        assert not any(ref["table"] == "advisor_messages" for ref in revision.source_references)


# --- session search ---------------------------------------------------------------------------


def past_session(database, question="퇴사 시점을 언제로 잡을지 고민돼", answer="PAST_SESSION_CONCLUSION 석 달 뒤로 미루자는 결론"):
    with database.session() as session:
        conversation = AdvisorConversation(title="예전 상담")
        session.add(conversation)
        session.flush()
        asked = AdvisorMessage(conversation_id=conversation.id, role="user", content=question, status="complete")
        session.add(asked)
        session.flush()
        answered = AdvisorMessage(conversation_id=conversation.id, role="assistant", content=answer, status="complete")
        session.add(answered)
        session.commit()
        return asked.id, answered.id


SEARCH_PLAN = {**PLAN, "tasks": [{"id": "s1", "tool": "search_sessions", "query": "퇴사 시점"}]}


def derived_research(request):
    content = next(item["content"] for item in request.input if item["role"] == "developer"
                   and item["content"].startswith("이번 실행의 파생 분석"))
    return json.loads(content.split("\n", 1)[1])["research"]


def test_planner_searches_past_sessions_as_question_answer_pairs(env):
    client, database, provider = env
    asked, answered = past_session(database)
    run, requests = consult(client, database, provider, "recall", "지난번 퇴사 시점 상담에서 어떤 결론이었지?",
                            replies=(SEARCH_PLAN, FINAL))
    assert run["status"] == "completed", run
    assert "search_sessions" in requests[0].instructions
    found = derived_research(requests[-1])["s1"]["data"]
    assert found["interpretation"] == "past_sessions_not_current_facts"
    pair = found["sessions"][0]["messages"]
    assert [item["ref"] for item in pair] == [f"advisor_messages:{asked}", f"advisor_messages:{answered}"]
    assert all(item["historical"] for item in pair) and "PAST_SESSION_CONCLUSION" in pair[1]["content"]
    with database.session() as session:
        snapshot = session.get(ContextSnapshot, derived_research(requests[-1])["s1"]["snapshot_id"])
        assert {ref["id"] for ref in snapshot.record_references if ref["table"] == "advisor_messages"} >= {asked, answered}


def test_session_search_never_sends_a_restricted_past_answer(env):
    client, database, provider = env
    _, answered = past_session(database)
    with database.session() as session:
        set_record_policy(session, "advisor_messages", answered, False)
    _, requests = consult(client, database, provider, "recall-restricted", "지난번 퇴사 시점 상담에서 어떤 결론이었지?",
                          replies=(SEARCH_PLAN, FINAL))
    assert all("PAST_SESSION_CONCLUSION" not in outbound(request) for request in requests)


# --- batch approvals --------------------------------------------------------------------------


def test_batch_decisions_apply_each_item_independently(env):
    from app.modules.advisor import approval_manager
    from app.modules.playbooks.playbook_manager import playbook_manager
    from app.schema.approval_schema import ApprovalBatch
    client, database, provider = env
    with database.session() as session:
        action = ProposedAction(action="create_task", payload={"title": "합성 할 일"}, status="pending")
        memory = PersonalMemory(kind="preference", content="결론을 먼저 듣고 싶어 한다", status="proposed", source="advisor")
        decided = PersonalMemory(kind="preference", content="이미 처리됨", status="rejected", source="advisor")
        session.add_all([action, memory, decided])
        session.flush()
        revision = playbook_manager.propose(session, slug="합성-절차", base_revision_id=None, title="합성 절차",
            summary="합성 요약", body="1. 근거를 확인한다.", triggers=[], categories=[], rationale="",
            source_references=[], job_id=None)
        session.commit()
        batch = ApprovalBatch(items=[
            {"kind": "action", "id": action.id, "decision": "approve"},
            {"kind": "memory", "id": memory.id, "decision": "approve"},
            {"kind": "memory", "id": decided.id, "decision": "approve"},
            {"kind": "playbook", "id": revision.id, "decision": "reject"}])
        result = approval_manager.decide(session, batch)
        assert (result.succeeded, result.failed) == (3, 1)
        assert [outcome.ok for outcome in result.results] == [True, True, False, True]
        session.expire_all()
        assert session.get(ProposedAction, action.id).status == "approved"
        assert session.get(PersonalMemory, memory.id).status == "confirmed"
        assert session.get(PlaybookRevision, revision.id).status == "rejected"


def test_batch_refuses_the_same_item_twice():
    import pytest
    from pydantic import ValidationError
    from app.schema.approval_schema import ApprovalBatch
    with pytest.raises(ValidationError):
        ApprovalBatch(items=[{"kind": "memory", "id": 1, "decision": "approve"},
                             {"kind": "memory", "id": 1, "decision": "reject"}])


# --- usage outcomes feed learning -------------------------------------------------------------


def test_negative_feedback_on_a_procedure_answer_queues_learning_with_its_outcomes(env):
    client, database, provider = env
    add_playbook(client)
    run, _ = consult(client, database, provider, "pb-feedback", "이직 준비해도 될까?")
    message = answer_message(database, run)
    with database.session() as session:
        assert session.scalar(select(PlaybookUsage.id)) is not None
        rating = AdvisorRecommendation(message_id=message.id, summary="합성", user_rating=-1)
        session.add(rating)
        session.flush()
        reflection.after_feedback(session, message.id, rating.id, -1)
        session.commit()
        # Learning is off by default: nothing is queued.
        assert session.scalar(select(BackgroundJob.id).where(BackgroundJob.kind == "advisor_reflection")) is None
    client.put("/api/agent/settings", json={"learning": {"enabled": True}})
    with database.session() as session:
        reflection.after_feedback(session, message.id, rating.id, -1)
        session.commit()
        job = session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "advisor_reflection"))
        assert job.payload["automatic"] is True and job.request_id == f"reflect:feedback:{rating.id}"
    provider.replies.append({"nothing_to_learn": True, "playbooks": [], "memories": []})
    assert asyncio.run(reflection.process_one(database))
    with database.session() as session:
        finished = session.get(BackgroundJob, job.id)
        assert finished.status == "completed", (finished.status, finished.last_error, finished.result)
    counts = package(provider.requests[-1])["data"]["playbook_usage"]["이직-점검"]
    assert (counts["uses"], counts["negative_ratings"]) == (1, 1)
    playbook = client.get("/api/playbooks").json()[0]
    assert playbook["outcomes"]["uses"] == 1 and playbook["outcomes"]["negative_ratings"] == 1


def test_a_correction_reviews_the_procedure_the_previous_answer_used(env):
    from app.modules.playbooks.usage import used_by_previous_answer
    client, database, provider = env
    add_playbook(client)
    consult(client, database, provider, "pb-first", "이직 준비해도 될까?")
    run, _ = consult(client, database, provider, "pb-correct", "아니야, 그게 아니라 다시 생각해 줘")
    with database.session() as session:
        current = session.get(AdvisorRun, run["id"])
        assert used_by_previous_answer(session, 1, current.user_message_id) == ["이직-점검"]
