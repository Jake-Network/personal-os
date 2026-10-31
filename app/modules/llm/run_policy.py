"""Pinned run authority checked at the final external transmission boundary."""
from app.modules.crud import app_setting_handler
from app.modules.llm import transfer_policy
from app.modules.llm.errors import AdvisorError

KEY = 'advisor.authorization_epoch'


def epoch(session):
    return (app_setting_handler.get_value(session, KEY) or {}).get('value', 0)


def capture(session):
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager, MODEL_KEY
    provider = llm_gateway_manager.provider_name(session)
    transfer_policy.require_confirmation(session, provider)
    return {'provider': provider, 'account_binding': transfer_policy.account_binding(session, provider),
            'epoch': epoch(session), 'model_selection': app_setting_handler.get_value(session, MODEL_KEY) or {}}


def require(session, authorization):
    session.expire_all()
    if authorization is not None and capture(session) != authorization:
        raise AdvisorError('실행 권한이 변경되었습니다. 연결과 공유 범위를 확인하고 다시 시도하세요.',
                           provider_code='run_authorization_changed')


def revoke(session):
    app_setting_handler.set_value(session, KEY, {'value': epoch(session) + 1})
    session.flush()


def require_execution(session, request):
    """Validate the caller's run/job lease at the final provider boundary."""
    if request.run_id:
        from app.modules.database.model.advisor_runtime import AdvisorRun
        from app.modules.database.model.base import utcnow
        from app.modules.agent.briefing import require_run_authorized
        run = session.get(AdvisorRun, request.run_id, populate_existing=True)
        if (run is None or run.status != "running" or not request.run_owner
                or run.lease_owner != request.run_owner or run.lease_generation != request.run_generation
                or run.lease_until is None or run.lease_until <= utcnow()):
            raise AdvisorError("상담 실행이 중지되었거나 변경되었습니다.", provider_code="run_authorization_changed")
        require_run_authorized(session, run)
    if request.background_job_id is not None:
        from app.modules.agent.reflection import require_job_authorized
        require_job_authorized(session, request.background_job_id, request.background_job_owner)
