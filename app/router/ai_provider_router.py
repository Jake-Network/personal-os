"""Settings → AI Provider (PRD §2.1). Never returns tokens."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from urllib.parse import urlsplit, parse_qs
from app.modules.security import session_manager as app_auth
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.auth.oauth_manager import oauth_manager
from app.modules.database import get_session
from app.modules.llm.llm_gateway_manager import MODEL_KEY, llm_gateway_manager
from app.modules.crud import app_setting_handler
from app.schema.llm_schema import ProviderSelection, UsageEventItem
from app.schema.oauth_schema import AIProviderStatus, LoginStartResponse

router = APIRouter(prefix="/api/settings/ai-provider", tags=["ai-provider"])


@router.get("", response_model=AIProviderStatus)
def get_status(session: Session = Depends(get_session)):
    status = oauth_manager.status(session)
    model = (app_setting_handler.get_value(session, MODEL_KEY) or {}).get("name")
    return AIProviderStatus(**status, provider=llm_gateway_manager.provider_name(session), model=model,
                            configuration_complete=llm_gateway_manager.configuration_complete(session))


@router.post("/chatgpt/login", response_model=LoginStartResponse)
def start_login(request: Request, response: Response, force_consent: bool = False, session: Session = Depends(get_session)):
    """`Continue with ChatGPT` / 재인증. The browser opens authorize_url; tokens stay server-side."""
    url = oauth_manager.start_login(session, force_consent=force_consent)
    state = parse_qs(urlsplit(url).query)["state"][0]
    proof = app_auth.bind_oauth(session, request.cookies[app_auth.COOKIE], state, "chatgpt")
    response.set_cookie("personal_os_oauth_chatgpt", proof, httponly=True, samesite="lax", max_age=600, path="/",
                        secure=urlsplit(settings.frontend_url).scheme == "https")
    return LoginStartResponse(authorize_url=url)


@router.delete("/chatgpt", status_code=204)
async def disconnect(session: Session = Depends(get_session)):
    await oauth_manager.disconnect(session)


@router.get("/models", response_model=list[str])
async def list_models(session: Session = Depends(get_session)):
    return await llm_gateway_manager.list_models(session)


@router.put("/selection", status_code=204)
def select_provider(body: ProviderSelection, session: Session = Depends(get_session)):
    try:
        llm_gateway_manager.select(session, body.provider, body.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/usage-events", response_model=list[UsageEventItem])
def usage_events(limit: int = 50, session: Session = Depends(get_session)):
    return [
        UsageEventItem(id=e.id, provider=e.provider, model=e.model, outcome=e.outcome, error_code=e.error_code,
                       input_tokens=e.input_tokens, output_tokens=e.output_tokens, latency_ms=e.latency_ms,
                       created_at=e.created_at.isoformat())
        for e in llm_gateway_manager.recent_usage(session, limit)
    ]


from app.modules.llm import connection_test
from app.schema.llm_schema import ConnectionTestResult


@router.post("/test", response_model=ConnectionTestResult)
async def test_connection(session: Session = Depends(get_session)):
    """One fixed sentence, only when the user presses the button; no personal data is sent."""
    return await connection_test.run(session)
