"""Transactional persistence. Callers own the session and commit boundary."""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from app.modules.database.model import AdvisorConversation, AdvisorMessage
from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorRunEvent, AdvisorRunResponse, AdvisorScenario, AdvisorWorkspace, AdvisorRuntimeLock
from app.modules.database.model.base import utcnow
from app.schema.advisor_runtime_schema import RunCreate, RunView, RunEvent, WorkspaceView, ScenarioView

TERMINAL = frozenset({"completed", "cancelled", "failed"})

def llm_job_running(session, now):
    from app.modules.crud.review_jobs_handler import LLM_KINDS
    from app.modules.database.model.review_jobs import BackgroundJob
    return session.scalar(select(BackgroundJob.id).where(BackgroundJob.kind.in_(LLM_KINDS),
        BackgroundJob.status == "running", BackgroundJob.lease_until > now).limit(1)) is not None


def take_runtime_gate(session):
    """Serialize every model-calling claimer on one coordination row."""
    session.execute(insert(AdvisorRuntimeLock).values(id=1, generation=0).on_conflict_do_nothing())
    session.execute(update(AdvisorRuntimeLock).where(AdvisorRuntimeLock.id == 1)
                    .values(generation=AdvisorRuntimeLock.generation + 1))


class LeaseLost(RuntimeError):
    """The worker may no longer publish this run."""

class RunRepository:
    def __init__(self, session):
        self.session = session

    def get(self, run_id):
        row = self.session.get(AdvisorRun, run_id)
        if row is None:
            raise HTTPException(404, "상담 실행을 찾을 수 없습니다.")
        return row

    def view(self, run_id):
        return RunView.model_validate(self.get(run_id))

    def _conversation(self, conversation_id):
        if self.session.get(AdvisorConversation, conversation_id) is None:
            raise HTTPException(404, "상담을 찾을 수 없습니다.")

    def _lock(self, run_id):
        # An UPDATE fences concurrent response/cancel/event writers on the run row.
        found = self.session.execute(update(AdvisorRun).where(AdvisorRun.id == run_id)
            .values(revision=AdvisorRun.revision).returning(AdvisorRun.id)).scalar_one_or_none()
        if found is None:
            raise HTTPException(404, "상담 실행을 찾을 수 없습니다.")
        return self.session.get(AdvisorRun, run_id, populate_existing=True)

    def create(self, conversation_id: int, request: RunCreate):
        self._conversation(conversation_id)
        # Serialize duplicate submissions before checking idempotency or active runs.
        self.session.execute(update(AdvisorConversation).where(AdvisorConversation.id == conversation_id)
                             .values(updated_at=AdvisorConversation.updated_at))
        payload = request.model_dump(mode="json")
        existing = self.session.scalar(select(AdvisorRun).where(
            AdvisorRun.conversation_id == conversation_id, AdvisorRun.request_id == request.request_id))
        if existing:
            if existing.input_payload != payload:
                raise HTTPException(409, "같은 요청 ID의 내용이 다릅니다.")
            return existing
        active = self.session.scalar(select(AdvisorRun.id).where(
            AdvisorRun.conversation_id == conversation_id, AdvisorRun.status.not_in(TERMINAL)))
        if active:
            raise HTTPException(409, "진행 중인 상담 실행이 있습니다.")
        workspace = self.session.get(AdvisorWorkspace, conversation_id)
        if request.parent_revision is not None and request.parent_revision != (workspace.revision if workspace else 1):
            raise HTTPException(409, "상담 상태가 변경되었습니다.")
        if request.scenario_id:
            scenario = self.session.get(AdvisorScenario, request.scenario_id)
            if not scenario or scenario.conversation_id != conversation_id:
                raise HTTPException(404, "대안을 찾을 수 없습니다.")
            self._require_scenario_evidence(scenario)
        message = AdvisorMessage(conversation_id=conversation_id, role="user",
                                 content=request.message, status="pending")
        self.session.add(message)
        self.session.flush()
        row = AdvisorRun(id=str(uuid4()), conversation_id=conversation_id,
            request_id=request.request_id, input_payload=payload, depth=request.depth,
            status="queued", user_message_id=message.id)
        self.session.add(row)
        self.session.flush()
        self.append_event(row.id, "status", {"status": "queued"}, "created")
        return row

    def append_event(self, run_id, event_type, payload, event_key=None, *, worker_id=None, generation=None):
        row = self.fence(run_id, worker_id, generation) if worker_id is not None else self._lock(run_id)
        event_key = event_key or str(uuid4())
        existing = self.session.scalar(select(AdvisorRunEvent).where(
            AdvisorRunEvent.run_id == run_id, AdvisorRunEvent.event_key == event_key))
        if existing:
            return existing
        row.last_event_seq += 1
        event = AdvisorRunEvent(run_id=run_id, seq=row.last_event_seq,
            event_key=event_key, type=event_type, revision=row.revision, payload=payload)
        self.session.add(event)
        self.session.flush()
        return event

    def events(self, run_id, after_seq=0):
        self.get(run_id)
        return [RunEvent.model_validate(row) for row in self.session.scalars(select(AdvisorRunEvent)
            .where(AdvisorRunEvent.run_id == run_id, AdvisorRunEvent.seq > after_seq)
            .order_by(AdvisorRunEvent.seq)).all()]

    def claim(self, worker_id, lease_seconds=60):
        # Serialize claimers on a single coordination row: only one global run executes.
        take_runtime_gate(self.session)
        now = utcnow()
        running = self.session.scalar(select(AdvisorRun.id).where(
            AdvisorRun.status.in_(["running", "cancel_requested"]), AdvisorRun.lease_until > now))
        if running or llm_job_running(self.session, now):
            return None
        candidate = self.session.scalar(select(AdvisorRun).where(AdvisorRun.status == "queued")
                                        .order_by(AdvisorRun.created_at, AdvisorRun.id).limit(1))
        if not candidate:
            return None
        claimed = self.session.execute(update(AdvisorRun).where(
            AdvisorRun.id == candidate.id, AdvisorRun.status == "queued",
            AdvisorRun.lease_generation == candidate.lease_generation)
            .values(status="running", lease_owner=worker_id, lease_generation=AdvisorRun.lease_generation + 1,
                    lease_until=now + timedelta(seconds=lease_seconds), revision=AdvisorRun.revision + 1)
            .returning(AdvisorRun.id)).scalar_one_or_none()
        if not claimed:
            return None
        row = self.session.get(AdvisorRun, claimed, populate_existing=True)
        self.append_event(row.id, "status", {"status": "running"}, f"claimed:{row.lease_generation}")
        return row

    def fence(self, run_id, worker_id, generation):
        now = utcnow()
        found = self.session.execute(update(AdvisorRun).where(
            AdvisorRun.id == run_id, AdvisorRun.lease_owner == worker_id,
            AdvisorRun.lease_generation == generation, AdvisorRun.status == "running",
            AdvisorRun.lease_until > now).values(lease_generation=AdvisorRun.lease_generation)
            .returning(AdvisorRun.id)).scalar_one_or_none()
        if found is None:
            raise LeaseLost(run_id)
        return self.session.get(AdvisorRun, run_id, populate_existing=True)

    def heartbeat(self, run_id, worker_id, generation, lease_seconds=60):
        row = self.fence(run_id, worker_id, generation)
        row.lease_until = utcnow() + timedelta(seconds=lease_seconds)
        self.session.flush()
        return row

    def transition(self, run_id, status, *, worker_id, generation, result=None, clarification=None, error=None, checkpoint=None):
        row = self.fence(run_id, worker_id, generation)
        if status not in {"running", "waiting_input", "blocked", "completed", "failed"}:
            raise ValueError("Unsupported worker transition")
        row.status, row.error = status, error
        row.revision += 1
        if result is not None:
            row.result = result
        if checkpoint is not None:
            row.checkpoint = checkpoint
        row.clarification = clarification
        if status != "running":
            row.lease_owner, row.lease_until = None, None
        if status in {"failed", "blocked"}:
            user = self.session.get(AdvisorMessage, row.user_message_id)
            if user is not None and user.status == "pending":
                user.status = "failed"
        self.session.flush()
        self.append_event(run_id, "status", {"status": status}, f"state:{row.revision}")
        from app.modules.agent.briefing import after_run
        after_run(self.session, row)
        return row

    def respond(self, run_id, request):
        row = self._lock(run_id)
        existing = self.session.scalar(select(AdvisorRunResponse).where(
            AdvisorRunResponse.run_id == run_id, AdvisorRunResponse.request_id == request.request_id))
        if existing:
            if existing.question_id != request.question_id or existing.response != request.response:
                raise HTTPException(409, "같은 응답 ID의 내용이 다릅니다.")
            return row
        if row.status != "waiting_input" or row.revision != request.expected_revision or not row.clarification or row.clarification["id"] != request.question_id:
            raise HTTPException(409, "확인 질문 상태가 변경되었습니다.")
        self.session.add(AdvisorRunResponse(run_id=run_id, request_id=request.request_id,
            question_id=request.question_id, response=request.response))
        self.session.add(AdvisorMessage(conversation_id=row.conversation_id, role="user",
            content=request.response, status="complete",
            context_snapshot_id=(row.runtime_metadata or {}).get("question_snapshot_id")))
        row.checkpoint = {**row.checkpoint, "resume": request.response, "question_id": request.question_id}
        row.clarification = None
        row.status = "queued"
        row.revision += 1
        self.session.flush()
        self.append_event(run_id, "status", {"status": "queued"}, f"response:{request.request_id}")
        return row

    def cancel(self, run_id):
        row = self._lock(run_id)
        if row.status in TERMINAL or row.status == "cancel_requested":
            return row
        row.status = "cancel_requested" if row.status == "running" else "cancelled"
        row.revision += 1
        # Revoking generation prevents any later checkpoint/result from this worker.
        row.lease_generation += 1
        if row.status == "cancelled":
            user = self.session.get(AdvisorMessage, row.user_message_id)
            if user is not None and user.status == "pending":
                user.status = "failed"
        self.session.flush()
        self.append_event(run_id, "status", {"status": row.status}, f"cancel:{row.revision}")
        from app.modules.agent.briefing import after_run
        after_run(self.session, row)
        return row

    def acknowledge_cancel(self, run_id):
        row = self._lock(run_id)
        if row.status == "cancel_requested":
            row.status, row.lease_owner, row.lease_until = "cancelled", None, None
            row.revision += 1
            user = self.session.get(AdvisorMessage, row.user_message_id)
            if user is not None and user.status == "pending":
                user.status = "failed"
            self.session.flush()
            self.append_event(run_id, "status", {"status": "cancelled"}, f"cancelled:{row.revision}")
            from app.modules.agent.briefing import after_run
            after_run(self.session, row)
        return row

    def retry(self, run_id):
        row = self._lock(run_id)
        if row.status not in {"failed", "blocked"}:
            raise HTTPException(409, "재시도할 수 없는 상태입니다.")
        other = self.session.scalar(select(AdvisorRun.id).where(
            AdvisorRun.conversation_id == row.conversation_id, AdvisorRun.id != row.id,
            AdvisorRun.status.not_in(TERMINAL)))
        if other:
            raise HTTPException(409, "진행 중인 상담 실행이 있습니다.")
        row.status, row.error = "queued", None
        row.answer_revision += 1
        row.revision += 1
        row.lease_generation += 1
        row.lease_owner, row.lease_until = None, None
        self.session.flush()
        self.append_event(run_id, "status", {"status": "queued"}, f"retry:{row.revision}")
        return row

    def recover_expired(self):
        now = utcnow()
        rows = self.session.scalars(select(AdvisorRun).where(
            AdvisorRun.status.in_(["running", "cancel_requested"]),
            AdvisorRun.lease_until <= now)).all()
        for candidate in rows:
            row = self._lock(candidate.id)
            if row.status not in {"running", "cancel_requested"} or row.lease_until > now:
                continue
            if row.status == "cancel_requested":
                row.status = "cancelled"
            else:
                # Missing metadata belongs to an older/uncertain run and fails closed.
                row.status = "queued" if (row.runtime_metadata or {}).get("model_inflight") is False else "blocked"
            row.error = "중단된 외부 호출의 완료 여부를 확인할 수 없습니다. 명시적으로 재시도하세요." if row.status == "blocked" else None
            row.lease_generation += 1
            row.lease_owner, row.lease_until = None, None
            row.revision += 1
            user = self.session.get(AdvisorMessage, row.user_message_id)
            if user is not None and user.status == "pending" and row.status != "queued":
                user.status = "failed"
            self.session.flush()
            self.append_event(row.id, "status", {"status": row.status}, f"recovered:{row.revision}")
            from app.modules.agent.briefing import after_run
            after_run(self.session, row)
        return len(rows)

    def create_scenario(self, conversation_id, request, *, run_id=None, evidence=None, results=None, unknowns=None):
        self._conversation(conversation_id)
        self.session.execute(update(AdvisorConversation).where(AdvisorConversation.id == conversation_id)
                             .values(updated_at=AdvisorConversation.updated_at))
        if run_id and self.get(run_id).conversation_id != conversation_id:
            raise HTTPException(409, "실행과 대안의 상담이 다릅니다.")
        existing = self.session.scalar(select(AdvisorScenario).where(
            AdvisorScenario.conversation_id == conversation_id, AdvisorScenario.request_id == request.request_id))
        if existing:
            if existing.title != request.title or existing.assumptions != request.assumptions or existing.constraints != request.constraints or existing.parent_id != request.parent_id:
                raise HTTPException(409, "같은 대안 요청 ID의 내용이 다릅니다.")
            return existing
        parent = self.session.get(AdvisorScenario, request.parent_id) if request.parent_id else None
        if request.parent_id and (not parent or parent.conversation_id != conversation_id):
            raise HTTPException(404, "부모 대안을 찾을 수 없습니다.")
        if parent and request.parent_revision != parent.revision:
            raise HTTPException(409, "대안 버전이 변경되었습니다.")
        if parent and parent.evidence.get('source_purged'):
            raise HTTPException(409, '부모 대안의 근거가 삭제되었습니다. 새 조건으로 분석하세요.')
        row = AdvisorScenario(id=str(uuid4()), conversation_id=conversation_id,
            request_id=request.request_id, run_id=run_id, parent_id=request.parent_id,
            revision=parent.revision + 1 if parent else 1, title=request.title,
            assumptions=request.assumptions, constraints=request.constraints,
            evidence=(dict(parent.evidence) if parent is not None and evidence is None else evidence or {}),
            results=results or {}, unknowns=unknowns or [])
        self.session.add(row)
        self.session.flush()
        return row

    def _require_scenario_evidence(self, scenario):
        from app.modules.database.model import ContextSnapshot
        snapshot_id = scenario.evidence.get('snapshot_id')
        snapshot = self.session.get(ContextSnapshot, snapshot_id) if snapshot_id else None
        if (scenario.evidence.get('source_purged') or snapshot is None
                or snapshot.payload.get('source_purged')
                or snapshot.conversation_id != scenario.conversation_id):
            raise HTTPException(409, '대안의 근거가 없거나 삭제되었습니다. 새 조건으로 분석하세요.')

    def select_scenario(self, conversation_id, request):
        self._conversation(conversation_id)
        self.session.execute(update(AdvisorConversation).where(AdvisorConversation.id == conversation_id)
                             .values(updated_at=AdvisorConversation.updated_at))
        scenario = self.session.get(AdvisorScenario, request.scenario_id) if request.scenario_id is not None else None
        if request.scenario_id is not None and (not scenario or scenario.conversation_id != conversation_id):
            raise HTTPException(404, "대안을 찾을 수 없습니다.")
        if scenario is not None:
            self._require_scenario_evidence(scenario)
        workspace = self.session.get(AdvisorWorkspace, conversation_id)
        if workspace is None:
            workspace = AdvisorWorkspace(conversation_id=conversation_id)
            self.session.add(workspace)
            self.session.flush()
        changed = self.session.execute(update(AdvisorWorkspace).where(
            AdvisorWorkspace.conversation_id == conversation_id,
            AdvisorWorkspace.revision == request.expected_revision)
            .values(selected_scenario_id=scenario.id if scenario else None, revision=AdvisorWorkspace.revision + 1))
        if changed.rowcount != 1:
            raise HTTPException(409, "상담 상태가 변경되었습니다.")
        self.session.expire(workspace)
        return workspace

    def _run_view(self, row):
        """Mark receipts the user has since undone, the same way message items do."""
        view = RunView.model_validate(row)
        operations = view.result.data_operations if view.result else []
        ids = {op["receipt_id"] for op in operations if isinstance(op, dict) and isinstance(op.get("receipt_id"), int)}
        if not ids:
            return view
        from app.modules.advisor.commands.undo import undone_receipts
        undone = undone_receipts(self.session, ids)
        if not undone:
            return view
        marked = [{**op, "undone": True} if isinstance(op, dict) and op.get("receipt_id") in undone else op
                  for op in operations]
        return view.model_copy(update={"result": view.result.model_copy(update={"data_operations": marked})})

    def workspace(self, conversation_id):
        self._conversation(conversation_id)
        # Materialize everything in one read transaction; each run/event cursor comes from one row.
        workspace = self.session.get(AdvisorWorkspace, conversation_id)
        rows = self.session.scalars(select(AdvisorRun).where(
            AdvisorRun.conversation_id == conversation_id).order_by(AdvisorRun.created_at.desc(), AdvisorRun.id.desc())).all()
        latest = rows[0] if rows else None
        active = next((r for r in rows if r.status not in TERMINAL), None)
        scenarios = self.session.scalars(select(AdvisorScenario).where(
            AdvisorScenario.conversation_id == conversation_id).order_by(AdvisorScenario.created_at)).all()
        run_questions = {run.id: (run.input_payload or {}).get('message') for run in rows}
        scenario_views = []
        for scenario in scenarios:
            view = ScenarioView.model_validate(scenario)
            question = run_questions.get(scenario.run_id)
            if question and not view.evidence.get('question') and not view.evidence.get('source_purged'):
                # Enrich legacy read responses from their own run, never the latest
                # consultation or a mutation of the historical evidence record.
                view = view.model_copy(update={'evidence': {**view.evidence, 'question': question}})
            scenario_views.append(view)
        return WorkspaceView(conversation_id=conversation_id,
            revision=workspace.revision if workspace else 1, problem=workspace.problem if workspace else {},
            selected_scenario_id=workspace.selected_scenario_id if workspace else None,
            active_run=self._run_view(active) if active else None,
            latest_run=self._run_view(latest) if latest else None,
            scenarios=scenario_views,
            last_event_seq=(active or latest).last_event_seq if (active or latest) else 0)
