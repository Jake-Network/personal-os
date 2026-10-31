"""Learning loop: after a consultation or a decision outcome, propose reusable lessons.

Hermes reviews its own work in the background and saves skills. Here the same review only
*proposes*: playbook revisions and memory candidates stay pending until the user approves
them. The request goes through ContextAssembler, so current sharing filters, withheld
history, budgets and snapshots apply exactly as in a consultation.

Execution rules: one model-calling job or run at a time (shared runtime gate), authority
pinned at enqueue time, consent re-read before the call, no automatic re-call once the
model may have been reached, and no exception text persisted.
"""
import asyncio
import json
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud.review_jobs_handler import LLM_KINDS, by_request
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob
from app.modules.llm.errors import AdvisorError
from app.modules.playbooks.usage import CORRECTION

logger = logging.getLogger(__name__)
KIND = "advisor_reflection"
LEASE = timedelta(seconds=90)

REFLECTION_PROMPT = (
    "이번 요청은 답변이 아니라 학습 회고입니다. 위 상담(또는 결정의 기대 결과와 실제 결과)을 돌아보고, 다음 상담에서 "
    "재사용할 '절차'만 제안하세요. 플레이북은 사람의 기록이 아니라 교훈입니다: 금액·잔고·특정 날짜·레코드 ref·"
    "개인 사실을 넣지 말고, 어떤 근거를 어떤 순서로 확인하고 무엇을 주의할지 단계로 쓰세요. "
    "기존 플레이북을 고칠 때는 existing_playbooks에 있는 slug와 active_revision_id를 base_revision_id로 그대로 쓰고 "
    "전체 수정본을 body에 쓰세요. 새 플레이북은 playbook_catalog에 없는 slug(소문자·숫자·한글·하이픈)를 쓰세요. "
    "playbook_usage는 기존 플레이북을 쓴 최근 답변의 결과 집계(평가·다음 턴 정정·회고한 결정 수)입니다. 정정이나 "
    "낮은 평가가 반복된 절차는 원인이 된 단계를 고치는 patch를 우선 검토하고, 건수가 적으면 단정하지 마세요. "
    "사용자가 명시한 장기 선호·제약이 있을 때만 memories 후보를 만드세요. 재사용할 교훈이 없으면 "
    "nothing_to_learn=true로 비워 두세요. 모든 제안은 사용자가 승인해야 적용됩니다.")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaybookDraft(StrictModel):
    action: Literal["create", "patch"]
    slug: str = Field(min_length=2, max_length=40)
    base_revision_id: int | None = None
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=300)
    triggers: list[str] = Field(default_factory=list, max_length=12)
    categories: list[str] = Field(default_factory=list, max_length=7)
    body: str = Field(min_length=1, max_length=8000)
    rationale: str = Field(default="", max_length=1000)


class MemoryDraft(StrictModel):
    kind: Literal["profile", "preference", "constraint", "priority"]
    content: str = Field(min_length=1, max_length=1000)


class Reflection(StrictModel):
    nothing_to_learn: bool = False
    playbooks: list[PlaybookDraft] = Field(default_factory=list, max_length=2)
    memories: list[MemoryDraft] = Field(default_factory=list, max_length=3)


# --- enqueue -------------------------------------------------------------------------------


def enqueue(session: Session, *, request_id: str, source: str, run_id: str | None = None,
            decision_id: int | None = None, outcome_id: int | None = None, automatic: bool = False) -> BackgroundJob:
    """Pin run authority now; the caller commits. Raises when the source cannot be reflected on."""
    from app.modules.database.model import AdvisorConversation, DecisionJournalEntry
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.llm import run_policy
    if source == "run":
        run = session.get(AdvisorRun, run_id)
        if run is None:
            raise LookupError("상담 실행을 찾을 수 없습니다")
        if run.status != "completed" or not run.assistant_message_id:
            raise ValueError("완료된 상담 답변만 회고할 수 있습니다")
        conversation_id = run.conversation_id
    elif source == "decision_outcome":
        decision = session.get(DecisionJournalEntry, decision_id)
        if decision is None:
            raise LookupError("결정을 찾을 수 없습니다")
        if decision.conversation_id is None or session.get(AdvisorConversation, decision.conversation_id) is None:
            raise ValueError("상담과 연결된 결정만 회고할 수 있습니다")
        conversation_id = decision.conversation_id
    else:
        raise ValueError("unsupported reflection source")
    payload = {"source": source, "run_id": run_id, "decision_id": decision_id, "automatic": automatic,
               "conversation_id": conversation_id}
    existing = by_request(session, BackgroundJob, request_id)
    if existing is not None:
        if (existing.kind, existing.payload.get("source"), existing.payload.get("run_id"),
                existing.payload.get("decision_id")) != (KIND, source, run_id, decision_id):
            raise ValueError("같은 요청 ID에 다른 작업을 사용할 수 없습니다")
        if outcome_id is not None and existing.payload.get("outcome_id") != outcome_id:
            raise ValueError("같은 요청 ID에 다른 회고 결과를 사용할 수 없습니다")
        return existing
    if source == "decision_outcome":
        from app.modules.database.model.review_jobs import DecisionReviewRecord
        outcome = (session.get(DecisionReviewRecord, outcome_id) if outcome_id is not None else
                   session.scalar(select(DecisionReviewRecord).where(DecisionReviewRecord.decision_id == decision_id)
                                  .order_by(DecisionReviewRecord.id.desc()).limit(1)))
        if outcome_id is not None and (outcome is None or outcome.decision_id != decision_id):
            raise ValueError("결정에 연결된 회고 결과를 찾을 수 없습니다")
        # Freeze the append-only event now; a delayed job must never substitute a newer outcome.
        payload["outcome_id"] = outcome.id if outcome is not None else None
    payload["authorization"] = run_policy.capture(session)
    job = BackgroundJob(request_id=request_id, kind=KIND, enabled=True, payload=payload, max_attempts=1,
                        run_after=utcnow())
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return by_request(session, BackgroundJob, request_id)
    return job


def qualifies(state: dict) -> bool:
    """Hermes' triggers, adapted: real analysis work, recovery, or a user correction."""
    from app.modules.advisor.runtime.graph import needs_analysis
    if not needs_analysis(state):
        return False
    return (state.get("tool_calls", 0) >= 3 or state.get("replans", 0) >= 1
            or state.get("clarification_count", 0) >= 1 or bool(CORRECTION.search(state.get("query", ""))))


def after_run(session: Session, run_id: str, state: dict) -> None:
    """Optional automatic reflection; a consultation never fails because of it."""
    from app.modules.agent.settings_manager import learning
    from app.modules.database.model import AdvisorConversation
    from app.modules.database.model.advisor_runtime import AdvisorRun
    try:
        if not learning(session).enabled or not qualifies(state):
            return
        run = session.get(AdvisorRun, run_id)
        conversation = session.get(AdvisorConversation, run.conversation_id) if run else None
        if conversation is None or conversation.origin != "user":
            return
        with session.begin_nested():
            enqueue(session, request_id=f"reflect:run:{run_id}", source="run", run_id=run_id, automatic=True)
    except Exception as exc:  # consent, provider or source changes simply skip learning
        logger.info("Automatic reflection skipped: %s", type(exc).__name__)


def after_feedback(session: Session, message_id: int, recommendation_id: int, rating: int | None) -> None:
    """A negative rating of an answer that used a procedure is the clearest signal to revisit it."""
    from app.modules.agent.settings_manager import learning
    from app.modules.database.model.advisor_runtime import AdvisorRun
    try:
        if rating != -1 or not learning(session).enabled:
            return
        run = session.scalar(select(AdvisorRun).where(AdvisorRun.assistant_message_id == message_id,
                                                      AdvisorRun.status == "completed").limit(1))
        if run is None or not (run.result or {}).get("playbooks"):
            return
        with session.begin_nested():
            enqueue(session, request_id=f"reflect:feedback:{recommendation_id}", source="run", run_id=run.id,
                    automatic=True)
    except Exception as exc:
        logger.info("Feedback reflection skipped: %s", type(exc).__name__)


def after_outcome(session: Session, decision_id: int, review_id: int) -> None:
    from app.modules.agent.settings_manager import learning
    try:
        if not learning(session).enabled:
            return
        with session.begin_nested():
            enqueue(session, request_id=f"reflect:decision:{review_id}", source="decision_outcome",
                    decision_id=decision_id, outcome_id=review_id, automatic=True)
    except Exception as exc:
        logger.info("Automatic decision reflection skipped: %s", type(exc).__name__)


# --- execution -----------------------------------------------------------------------------


def claim(session: Session, owner: str):
    from app.modules.advisor.runtime.persistence import take_runtime_gate
    from app.modules.database.model.advisor_runtime import AdvisorRun
    now = utcnow()
    # Idle polling stays read-only; only an actual candidate takes the shared write gate.
    if session.scalar(select(BackgroundJob.id).where(BackgroundJob.kind.in_(LLM_KINDS),
            BackgroundJob.status.in_(["pending", "running"])).limit(1)) is None:
        return None
    take_runtime_gate(session)
    # An interrupted call may have reached the provider: fail it for an explicit retry, never replay.
    expired = session.execute(update(BackgroundJob).where(BackgroundJob.kind.in_(LLM_KINDS), BackgroundJob.status == "running",
        BackgroundJob.lease_until <= now).values(status="failed", last_error="interrupted", completed_at=now,
            lease_owner=None, lease_until=None).returning(BackgroundJob.id, BackgroundJob.payload, BackgroundJob.kind)).all()
    from app.modules.agent.inbox_manager import notify
    for job_id, payload, kind in expired:
        if kind != "advisor_reflection":
            continue  # an interrupted connection test has no follow-up for the user
        notify(session, "job_failed", "학습 회고가 중단되었습니다", f"reflection-failed:{job_id}",
            summary="모델 호출의 완료 여부가 불확실해 자동으로 다시 실행하지 않습니다. 자동 작업에서 상태를 확인하세요.",
            severity="warning", links={"job_id": job_id, "conversation_id": payload.get("conversation_id")})
    if session.scalar(select(AdvisorRun.id).where(AdvisorRun.status.in_(["running", "cancel_requested"]),
                                                  AdvisorRun.lease_until > now).limit(1)):
        return None
    if session.scalar(select(BackgroundJob.id).where(BackgroundJob.kind.in_(LLM_KINDS),
            BackgroundJob.status == "running", BackgroundJob.lease_until > now).limit(1)):
        return None
    eligible = (BackgroundJob.kind.in_(LLM_KINDS), BackgroundJob.enabled.is_(True), BackgroundJob.status == "pending",
                BackgroundJob.attempts < BackgroundJob.max_attempts, BackgroundJob.run_after <= now)
    job_id = session.scalar(select(BackgroundJob.id).where(*eligible).order_by(BackgroundJob.run_after, BackgroundJob.id).limit(1))
    if job_id is None:
        return None
    changed = session.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, *eligible).values(
        status="running", lease_owner=owner, lease_until=now + LEASE, attempts=BackgroundJob.attempts + 1))
    if changed.rowcount != 1:
        return None
    session.flush()
    return session.get(BackgroundJob, job_id, populate_existing=True)


def _heartbeat(database, job_id, owner):
    with database.session() as session:
        changed = session.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status == "running",
            BackgroundJob.lease_owner == owner, BackgroundJob.lease_until > utcnow()).values(lease_until=utcnow() + LEASE))
        session.commit()
        return changed.rowcount == 1


def _finish(session: Session, job_id: int, owner: str, status: str, result: dict | None = None,
            error: str | None = None) -> bool:
    changed = session.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.status == "running",
        BackgroundJob.lease_owner == owner, BackgroundJob.lease_until > utcnow()).values(status=status, result=result, last_error=error,
                                                    completed_at=utcnow(), lease_owner=None, lease_until=None))
    return changed.rowcount == 1


async def process_one(database) -> bool:
    owner = str(uuid4())
    with database.session() as session:
        job = claim(session, owner)
        session.commit()
        if job is None:
            return False
        job_id, payload = job.id, dict(job.payload)

    async def beat():
        while True:
            await asyncio.sleep(5)
            if not await asyncio.to_thread(_heartbeat, database, job_id, owner):
                raise RuntimeError("lease_lost")

    pulse = asyncio.create_task(beat())
    with database.session() as session:
        try:
            work = asyncio.create_task(reflect(session, job_id, payload, owner=owner))
            done, _ = await asyncio.wait({work, pulse}, return_when=asyncio.FIRST_COMPLETED)
            if pulse in done:
                work.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await work
                pulse.result()
            status, result = work.result()
            if not _finish(session, job_id, owner, status, result):
                session.rollback()
                return True
            session.commit()
        except asyncio.CancelledError:
            work.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await work
            session.rollback()
            raise
        except AdvisorError as exc:
            session.rollback()
            _record_failure(session, job_id, owner, payload, exc.provider_code or exc.code)
        except Exception as exc:
            session.rollback()
            # Never persist exception text: it may contain personal data or credentials.
            _record_failure(session, job_id, owner, payload, type(exc).__name__)
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pulse
    return True


def _record_failure(session, job_id, owner, payload, code):
    from app.modules.agent.inbox_manager import notify
    changed = code == "run_authorization_changed"
    if _finish(session, job_id, owner, "cancelled" if changed else "failed",
               {"state": "authorization_changed"} if changed else None, str(code)[:100]):
        notify(session, "job_failed", "학습 회고를 마치지 못했습니다" if not changed
               else "연결이나 잠금 상태가 바뀌어 학습 회고를 멈췄습니다", f"reflection-failed:{job_id}",
               summary="모델 호출이 끝났는지 확실하지 않으면 자동으로 다시 실행하지 않습니다. 작업 목록에서 다시 시도할 수 있습니다."
               if not changed else "설정에서 연결과 공유 범위를 확인한 뒤 다시 요청하세요.",
               severity="warning", links={"job_id": job_id, "conversation_id": payload.get("conversation_id")})
        session.commit()
    else:
        session.rollback()


def require_job_authorized(session: Session, job_id: int, owner: str | None) -> None:
    """Re-read learning consent at the final provider boundary, after async assembly."""
    from app.modules.agent.settings_manager import learning
    job = session.get(BackgroundJob, job_id, populate_existing=True)
    if (job is None or job.kind != KIND or not owner or job.lease_owner != owner
            or job.status != "running" or not job.enabled or job.lease_until is None
            or job.lease_until <= utcnow()
            or (job.payload.get("automatic") and not learning(session).enabled)):
        raise AdvisorError("학습 회고의 실행 동의나 상태가 변경되었습니다.", provider_code="run_authorization_changed")


async def reflect(session: Session, job_id: int, payload: dict, *, owner: str) -> tuple[str, dict]:
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.context import ContextAssembler
    from app.modules.advisor.runtime.graph import structured_response
    from app.modules.agent.settings_manager import learning
    from app.modules.database.model import AdvisorConversation, ContextSnapshot, DecisionJournalEntry
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.review_jobs import DecisionReviewRecord
    from app.modules.llm import run_policy
    from app.schema.advisor_runtime_schema import RunCreate
    from app.modules.advisor.types import AskOptions

    authorization = payload["authorization"]
    run_policy.require(session, authorization)
    if payload.get("automatic") and not learning(session).enabled:
        return "cancelled", {"state": "consent_revoked"}
    conversation = session.get(AdvisorConversation, payload["conversation_id"])
    if conversation is None:
        return "cancelled", {"state": "source_deleted"}
    used_slugs, derived, message_id = [], {}, None
    source_flags = []
    if payload["source"] == "run":
        run = session.get(AdvisorRun, payload["run_id"])
        if run is None or run.status != "completed":
            return "cancelled", {"state": "source_deleted"}
        body = RunCreate.model_validate(run.input_payload)
        options, question = body.options(), body.message
        result = run.result or {}
        used_slugs = [item.get("slug") for item in result.get("playbooks", []) if item.get("slug")]
        if run.user_message_id and CORRECTION.search(question or ""):
            # A correction is feedback on the previous answer: review the procedures that answer used.
            from app.modules.playbooks.usage import used_by_previous_answer
            used_slugs = list(dict.fromkeys([*used_slugs, *used_by_previous_answer(
                session, conversation.id, run.user_message_id)]))
        message_id = run.assistant_message_id
        from app.modules.database.model.advisor_runtime import AdvisorWorkspace
        workspace = session.get(AdvisorWorkspace, conversation.id)
        derived = {"consultation_review": {
            "limitations": result.get("limitations", []), "model_calls": result.get("model_calls"),
            "tool_calls": result.get("tool_calls"), "clarified": bool(run.clarification),
            "playbooks_used": used_slugs, "problem_structure": sorted((workspace.problem or {}).keys()) if workspace else []}}
        sources = [{"table": "advisor_messages", "id": run.assistant_message_id}]
        if run.user_message_id:
            sources.append({"table": "advisor_messages", "id": run.user_message_id})
    else:
        decision = session.get(DecisionJournalEntry, payload["decision_id"])
        if decision is None:
            return "cancelled", {"state": "source_deleted"}
        if "outcome_id" not in payload:
            return "cancelled", {"state": "source_unknown"}
        outcome = session.get(DecisionReviewRecord, payload["outcome_id"]) if payload["outcome_id"] is not None else None
        if payload["outcome_id"] is not None and (outcome is None or outcome.decision_id != decision.id):
            return "cancelled", {"state": "source_deleted"}
        options, question = AskOptions(), f"결정 회고: {decision.title}"
        from app.modules.context.source_policy import source_allowed
        excluded = advisor_manager.sharing_exclusions(session, options)
        if not source_allowed(session, [{"table": "decision_journal", "id": decision.id}], excluded):
            return "cancelled", {"state": "source_restricted"}
        message_id = decision.source_message_id
        derived = {"decision_review": {"choice": decision.choice, "rationale": decision.rationale,
            "expected_outcome": outcome.expected_outcome if outcome else decision.expected_outcome,
            "alternatives": decision.alternatives,
            "actual_outcome": outcome.actual_outcome if outcome else None,
            "lessons": outcome.lessons if outcome else None, "historical": True}}
        sources = [{"table": "decision_journal", "id": decision.id}]
        if outcome is not None:
            sources.append({"table": "decision_reviews", "id": outcome.id})
    from app.modules.playbooks.selection import catalog_context, select_playbooks
    from app.modules.crud.playbook_handler import playbook_handler
    excluded = advisor_manager.sharing_exclusions(session, options)
    from app.modules.context.source_policy import source_allowed
    if payload["source"] == "run" and not source_allowed(session, sources, excluded,
            document_scope={"enabled": options.document_search, "document_ids": list(options.document_ids or [])}):
        # The old question and diagnostic strings may themselves contain revoked data.
        # Review only freshly assembled, permitted context in that case.
        question = "공유가 허용된 현재 기록에서 재사용할 상담 절차가 있는지 회고해 주세요."
        # Memory candidates need the user's own statement, which is exactly what is withheld;
        # nothing learned here may cite the restricted message as its source.
        derived, sources, used_slugs, message_id = {}, [], [], None
        source_flags.append({"code": "reflection_source_withheld", "category": "system",
            "detail": "공유 제한으로 선택한 과거 상담 대신 현재 공유된 기록만 회고했습니다."})
    elif payload["source"] == "run":
        from app.modules.database.model import AdvisorMessage
        # A selected old answer is mandatory learning evidence, regardless of the recent-history window.
        derived["source_messages"] = [{"ref": f"advisor_messages:{ref['id']}",
            "role": message.role, "content": message.content, "historical": True}
            for ref in sources if ref["table"] == "advisor_messages"
            if (message := session.get(AdvisorMessage, ref["id"])) is not None]
    from app.modules.playbooks.selection import eligible_revisions
    eligible = eligible_revisions(session, excluded)
    related, _ = select_playbooks(session, question, excluded, explicit_slugs=used_slugs, eligible=eligible)
    related_slugs = {}
    for revision in related:
        playbook = playbook_handler.get(session, revision.playbook_id)
        related_slugs[playbook.slug] = revision
    from app.modules.playbooks import usage
    # Counts only, over answers whose provenance the current sharing policy still allows.
    playbook_usage = usage.for_slugs(session, related_slugs, excluded)
    if playbook_usage:
        derived["playbook_usage"] = playbook_usage
    derived["existing_playbooks"] = [{"slug": slug, "active_revision_id": revision.id, "title": revision.title,
        "summary": revision.summary}
        for slug, revision in related_slugs.items()]
    from dataclasses import replace
    # Full procedures use the regular snapshot/budget path; discovery carries only bounded metadata.
    options = replace(options, playbook_ids=(), playbook_slugs=tuple(related_slugs))
    catalog, catalog_flags = catalog_context(session, excluded, question, exclude_slugs=related_slugs, eligible=eligible)
    derived["playbook_catalog"] = catalog
    catalog_flags = [*source_flags, *catalog_flags]
    sources.extend({"table": "playbook_revisions", "id": revision.id} for revision in related_slugs.values())

    guard_state = {"authorization": authorization}

    async def guard():
        run_policy.require(session, guard_state["authorization"])

    model = await advisor_manager.gateway.resolve_model(session)
    assembler = ContextAssembler(session, advisor_manager, conversation, options, model, guard=guard,
                                 authorization=authorization)
    schema_hint = "\nJSON 객체만 반환하세요. 스키마: " + json.dumps(Reflection.model_json_schema(), ensure_ascii=False)
    request, package = await assembler.assemble(question, instruction=REFLECTION_PROMPT + schema_hint,
                                                context_data=derived, record_sources=sources,
                                                context_flags=catalog_flags, structured_output=True)
    if payload.get("automatic") and not learning(session).enabled:
        return "cancelled", {"state": "consent_revoked"}
    request.background_job_id = job_id
    request.background_job_owner = owner
    chunks = []
    async for event in advisor_manager.gateway.stream(session, request, conversation_id=conversation.id):
        if event.type == "delta":
            chunks.append(event.text)
    try:
        reflection = structured_response("".join(chunks), Reflection)
    except ValueError as exc:
        raise AdvisorError("모델의 회고 결과 형식을 검증하지 못했습니다.", provider_code="invalid_structured_output") from exc
    snapshot = session.get(ContextSnapshot, package.snapshot_id)
    taint = set(snapshot.context_categories if snapshot else []) | set(
        (snapshot.payload if snapshot else {}).get("history_categories", [])) | set(
        (snapshot.payload if snapshot else {}).get("document_categories", []))
    # Lessons depend on every current record and catalog entry actually seen by this call,
    # including records added since the original consultation.
    lesson_sources = [*sources, {"table": "context_snapshots", "id": package.snapshot_id}]
    return "completed", record(session, job_id, payload, reflection, lesson_sources, taint, related_slugs,
                               message_id, snapshot_id=package.snapshot_id, source_withheld=bool(source_flags))


def record(session, job_id, payload, reflection, sources, taint, related, message_id, *, snapshot_id=None,
           source_withheld=False) -> dict:
    """Stage drafts as proposals only. Invalid drafts are skipped with a code, not stored."""
    from app.modules.advisor.proposal_manager import proposal_manager
    from app.modules.agent.inbox_manager import notify
    from app.modules.playbooks.playbook_manager import StaleRevision, playbook_manager
    from app.modules.playbooks.validation import PlaybookInvalid
    revision_ids, skipped = [], []
    for draft in [] if reflection.nothing_to_learn else reflection.playbooks:
        base = None
        if draft.action == "patch":
            if draft.slug not in related or related[draft.slug].id != draft.base_revision_id:
                skipped.append("patch_without_provided_base")
                continue
            base = draft.base_revision_id
        try:
            with session.begin_nested():
                # Origin categories taint the procedure: excluding any of them stops it being sent.
                revision = playbook_manager.propose(session, slug=draft.slug, base_revision_id=base, title=draft.title,
                    summary=draft.summary, body=draft.body, triggers=draft.triggers,
                    categories=sorted(set(draft.categories) & _known_categories() | taint),
                    rationale=draft.rationale, source_references=sources, job_id=job_id)
            revision_ids.append(revision.id)
        except PlaybookInvalid as exc:
            skipped.extend(exc.codes)
        except (StaleRevision, ValueError):
            skipped.append("playbook_conflict")
    memories = [] if reflection.nothing_to_learn or message_id is None else [m.model_dump() for m in reflection.memories]
    _, saved = proposal_manager.record(session, payload["conversation_id"], message_id, [], memories,
        memory_sources=[{"table": "context_snapshots", "id": snapshot_id}] if snapshot_id else None)
    result = {"playbook_revision_ids": revision_ids, "memory_ids": [m.id for m in saved], "skipped": skipped,
              "nothing_to_learn": reflection.nothing_to_learn, "source_withheld": source_withheld}
    if revision_ids or saved or not payload.get("automatic"):
        notify(session, "learning_proposals",
               f"학습 제안 {len(revision_ids) + len(saved)}건" if revision_ids or saved else "이번 상담에서 새로 배울 절차가 없었습니다",
               f"reflection:{job_id}",
               summary=("과거 상담은 공유 제한으로 제외하고 현재 기록만 회고했습니다. " if source_withheld else "") +
                       (f"플레이북 {len(revision_ids)}건, 기억 후보 {len(saved)}건을 검토하세요. 승인하기 전에는 상담에 쓰이지 않습니다."
                        if revision_ids or saved else "제안된 내용이 없거나 저장 규칙에 맞지 않아 제외되었습니다."),
               links={"job_id": job_id, "conversation_id": payload.get("conversation_id"),
                      "playbook_revision_ids": revision_ids, "memory_ids": [m.id for m in saved]})
    return result


def _known_categories():
    from app.enums.context_category import ALL_CATEGORIES
    return {str(c) for c in ALL_CATEGORIES}


async def process_pending(database, stop):
    while not stop.is_set():
        try:
            if await process_one(database):
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Agent worker unavailable: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass
