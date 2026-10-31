"""An explicit, user-pressed check that the selected provider answers.

It sends one fixed sentence with no personal data. It takes the same global one-call slot
as consultations and model jobs: a running-job row of an LLM kind, claimed under the shared
gate, keeps workers from starting a model call meanwhile. Nothing is retried or switched.
"""
import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow
from app.modules.database.model.review_jobs import BackgroundJob
from app.modules.llm.errors import AdvisorError
from app.modules.llm.types import LLMRequest

KIND = "connection_test"
TIMEOUT_SECONDS = 45
PROMPT = "연결 확인입니다. '연결됨'이라고만 답하세요."


def _claim(session: Session) -> int | None:
    from app.modules.advisor.runtime.persistence import llm_job_running, take_runtime_gate
    take_runtime_gate(session)
    now = utcnow()
    if session.scalar(select(AdvisorRun.id).where(AdvisorRun.status.in_(["running", "cancel_requested"]),
                                                  AdvisorRun.lease_until > now).limit(1)) or llm_job_running(session, now):
        session.rollback()
        return None
    job = BackgroundJob(request_id=f"{KIND}:{uuid4()}", kind=KIND, enabled=False, status="running", payload={},
                        lease_owner=str(uuid4()), lease_until=now + timedelta(seconds=TIMEOUT_SECONDS + 15))
    session.add(job)
    session.commit()
    return job.id


async def run(session: Session) -> dict:
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager
    job_id = _claim(session)
    if job_id is None:
        return {"ok": False, "code": "busy", "message": "다른 분석이 실행 중입니다. 끝난 뒤 다시 확인하세요."}
    provider = llm_gateway_manager.provider_name(session)
    model = None
    try:
        model = await llm_gateway_manager.resolve_model(session)
        request = LLMRequest(model=model, instructions="짧게 답합니다.", input=[{"role": "user", "content": PROMPT}])

        async def call() -> str:
            text = ""
            async for event in llm_gateway_manager.stream(session, request):
                if event.type == "delta":
                    text += event.text
            return text

        text = await asyncio.wait_for(call(), TIMEOUT_SECONDS)
        ok = bool(text.strip())
        return {"ok": ok, "code": "ok" if ok else "empty_response", "provider": provider, "model": model,
                "message": "AI가 답했습니다." if ok else "AI가 빈 답을 보냈습니다."}
    except TimeoutError:
        return {"ok": False, "code": "timeout", "provider": provider, "model": model,
                "message": f"{TIMEOUT_SECONDS}초 안에 답이 없었습니다."}
    except AdvisorError as exc:
        return {"ok": False, "code": exc.provider_code or exc.code, "provider": provider, "model": model,
                "message": (exc.detail or exc.user_message) if type(exc) is AdvisorError else exc.user_message}
    finally:
        session.rollback()
        session.execute(delete(BackgroundJob).where(BackgroundJob.id == job_id))
        session.commit()
