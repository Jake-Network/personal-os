"""Revoking scheduled inference and delivering terminal state, on disposable data."""
import asyncio
from datetime import date, timedelta

import pytest
from alembic import command
from sqlalchemy import select

from app.modules.agent import briefing
from app.modules.agent.inbox_manager import mark
from app.modules.database.database import Database
from app.modules.database.migration_manager import alembic_config
from app.modules.database.model import InboxItem, JobApplication, Interview
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import JobSchedule
from app.modules.llm import transfer_policy
from app.modules.llm.errors import AdvisorError
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.router.jobs_router import create_briefing_schedule, update_briefing_schedule
from app.schema.review_jobs_schema import BriefingCreate


@pytest.fixture
def database(tmp_path, monkeypatch):
    database = Database()
    url = f"sqlite:///{tmp_path / 'briefing.db'}"
    command.upgrade(alembic_config(url), "head")
    database.init(url)
    monkeypatch.setattr(transfer_policy, "account_binding", lambda session, provider: "synthetic-account")
    monkeypatch.setattr(llm_gateway_manager, "resolve_model", synthetic_model)
    with database.session() as session:
        transfer_policy.confirm(session, "chatgpt_plan", True, True)
    yield database
    database.engine.dispose()


async def synthetic_model(session):
    return "fake-model"


def queue_briefing(database):
    with database.session() as session:
        application = JobApplication(company="합성 회사", role="합성 직무", status="interviewing")
        session.add(application)
        session.flush()
        session.add(Interview(application_id=application.id, stage="합성 면접", starts_at=utcnow() + timedelta(days=1)))
        session.commit()
        body = BriefingCreate(name="합성 브리핑", local_time="08:00", enabled=True, llm_enabled=True)
        schedule = asyncio.run(create_briefing_schedule(body, session))
        queued = briefing.run(session, schedule, date.today(), key=f"briefing:{schedule.id}:one")
        assert queued["state"] == "queued", queued
        session.commit()
        return schedule.id, queued["run_id"], body


def test_turning_off_ai_withdraws_already_queued_briefing(database):
    schedule_id, run_id, body = queue_briefing(database)
    with database.session() as session:
        asyncio.run(update_briefing_schedule(schedule_id, body.model_copy(update={"llm_enabled": False}), session))
        assert session.get(AdvisorRun, run_id).status == "cancelled"


@pytest.mark.parametrize("change", [{"llm_enabled": False}, {"categories": ["health"]}])
def test_send_boundary_rechecks_current_schedule_options(database, change):
    schedule_id, run_id, _ = queue_briefing(database)
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        briefing.require_run_authorized(session, run)
        schedule = session.get(JobSchedule, schedule_id)
        schedule.options = {**schedule.options, **change}
        session.commit()
        with pytest.raises(AdvisorError) as error:
            briefing.require_run_authorized(session, run)
        assert error.value.provider_code == "run_authorization_changed"


def test_legacy_briefing_without_consent_snapshot_fails_closed(database):
    _, run_id, _ = queue_briefing(database)
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        run.runtime_metadata = {key: value for key, value in run.runtime_metadata.items() if key != "schedule_options"}
        with pytest.raises(AdvisorError):
            briefing.require_run_authorized(session, run)


def test_completion_updates_preparing_notice_after_it_was_read(database):
    _, run_id, _ = queue_briefing(database)
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        notice = session.scalar(select(InboxItem).where(InboxItem.dedupe_key == f"briefing:{run.request_id}"))
        mark(session, notice.id, "read")
        run.status = "completed"
        briefing.after_run(session, run)
        session.commit()
        assert notice.title == "브리핑이 준비되었습니다"
        assert notice.status == "unread" and notice.read_at is None
        mark(session, notice.id, "read")
        briefing.after_run(session, run)
        session.commit()
        assert notice.status == "read", "Repeated completion must not alert twice"


@pytest.mark.parametrize("status,kind", [("failed", "job_failed"), ("blocked", "job_failed"),
                                         ("cancelled", "briefing_ready"), ("waiting_input", "briefing_ready")])
def test_terminal_and_waiting_states_replace_preparing_notice(database, status, kind):
    _, run_id, _ = queue_briefing(database)
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        run.status = status
        briefing.after_run(session, run)
        session.commit()
        notice = session.scalar(select(InboxItem).where(InboxItem.dedupe_key == f"briefing:{run.request_id}"))
        assert notice.kind == kind and notice.links["run_status"] == status
        assert "준비하고 있습니다" not in notice.title


def test_editing_shared_categories_also_revokes_running_briefing(database):
    schedule_id, run_id, body = queue_briefing(database)
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        run.status = "running"
        session.commit()
        asyncio.run(update_briefing_schedule(schedule_id, body.model_copy(update={"categories": ["health"]}), session))
        assert run.status == "cancel_requested"


def test_final_model_boundary_blocks_consent_change_during_assembly(database, monkeypatch):
    from test_agent_loop import ScriptedProvider
    from app.modules.advisor.runtime.context import ContextAssembler
    from app.modules.advisor.runtime.worker import process_one

    schedule_id, run_id, _ = queue_briefing(database)
    provider = ScriptedProvider()
    provider.replies.append({"answer": "합성 브리핑", "proposals": [], "memories": []})
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    original = ContextAssembler.validate_interfaces

    async def withdraw_before_send(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        with database.session() as changing:
            schedule = changing.get(JobSchedule, schedule_id)
            schedule.options = {**schedule.options, "llm_enabled": False}
            changing.commit()

    monkeypatch.setattr(ContextAssembler, "validate_interfaces", withdraw_before_send)
    assert asyncio.run(process_one(database))
    assert provider.requests == [], "Consent changed after assembly must prevent provider transmission"
    with database.session() as session:
        run = session.get(AdvisorRun, run_id)
        assert run.status == "blocked"
        notice = session.scalar(select(InboxItem).where(InboxItem.dedupe_key == f"briefing:{run.request_id}"))
        assert notice.kind == "job_failed" and notice.links["run_status"] == "blocked"


def test_model_briefing_keeps_other_domain_signal_predicates_local(database, monkeypatch):
    from app.modules.advisor.runtime.worker import process_one
    from test_agent_loop import ScriptedProvider, outbound
    found = [
        {"kind": "exercise", "count": 1, "title": "일주일 넘게 운동 기록이 없습니다"},
        {"kind": "interviews", "count": 2, "title": "PRIVATE_INTERVIEW_SIGNAL"},
        {"kind": "expenses", "count": 1, "title": "PRIVATE_SPENDING_SIGNAL"},
    ]
    monkeypatch.setattr(briefing.briefing_signals, "collect", lambda session, now: found)
    with database.session() as session:
        body = BriefingCreate(name="합성 브리핑", local_time="08:00", enabled=True, llm_enabled=True, categories=["health"])
        schedule = asyncio.run(create_briefing_schedule(body, session))
        result = briefing.run(session, schedule, date.today(), key="briefing:1:private-signals")
        assert result["state"] == "queued"
        session.commit()
        notice = session.scalar(select(InboxItem).where(InboxItem.kind == "signal"))
        assert "PRIVATE_INTERVIEW_SIGNAL" in notice.summary
        run = session.get(AdvisorRun, result["run_id"])
        assert run.input_payload["categories"] == ["health"]
    provider = ScriptedProvider()
    provider.replies.append({"answer": "합성 건강 브리핑", "proposals": [], "memories": []})
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    assert asyncio.run(process_one(database))
    assert provider.requests
    sent = outbound(provider.requests[-1])
    assert "PRIVATE_INTERVIEW_SIGNAL" not in sent and "PRIVATE_SPENDING_SIGNAL" not in sent


@pytest.mark.parametrize("restriction", ["category", "record"])
def test_hidden_interview_signal_neither_wakes_model_nor_sends_queued_run(database, monkeypatch, restriction):
    from app.enums.context_category import Category
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.context.record_privacy import set_record_policy
    from app.modules.advisor.runtime.worker import process_one
    from test_agent_loop import ScriptedProvider

    schedule_id, run_id, _ = queue_briefing(database)
    with database.session() as session:
        if restriction == "category":
            privacy_manager.set_excluded(session, [Category.CAREER])
        else:
            interview_id = session.scalar(select(Interview.id))
            set_record_policy(session, "interviews", interview_id, False)
        schedule = session.get(JobSchedule, schedule_id)
        result = briefing.run(session, schedule, date.today(), key=f"briefing:{schedule_id}:after-privacy-change")
        assert result["state"] == "signals" and result["model"] == "no_shared_category"
        session.commit()
    provider = ScriptedProvider()
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    assert asyncio.run(process_one(database))
    assert provider.requests == []
    with database.session() as session:
        assert session.get(AdvisorRun, run_id).status == "blocked"


def test_partial_signal_category_whitelist_does_not_wake_model(database):
    schedule_id, _, _ = queue_briefing(database)
    with database.session() as session:
        schedule = session.get(JobSchedule, schedule_id)
        schedule.options = {**schedule.options, "categories": ["career"]}
        result = briefing.run(session, schedule, date.today(), key=f"briefing:{schedule_id}:partial")
        assert result["state"] == "signals" and result["model"] == "no_shared_category"
        assert session.scalar(select(AdvisorRun.id).where(AdvisorRun.request_id.endswith(":partial"))) is None
