"""Loopback redirect target. Registered redirect is http://127.0.0.1:<port>/auth/callback."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.auth.oauth_manager import oauth_manager
from app.modules.database import get_session
from app.modules.llm.errors import AdvisorError

router = APIRouter(tags=["oauth"])


@router.get("/auth/callback", include_in_schema=False)
async def oauth_callback(request: Request, session: Session = Depends(get_session)):
    try:
        conn = await oauth_manager.handle_callback(session, dict(request.query_params))
        result = {"chatgpt": "connected", "plan_usage": "enabled" if conn.plan_usage_enabled else "disabled"}
    except AdvisorError as exc:
        result = {"chatgpt": "error", "code": exc.provider_code or exc.code}
    # Only status flags go back to the browser; never codes or tokens.
    return RedirectResponse(f"{settings.frontend_url}/settings/ai-provider?{urlencode(result)}", status_code=303)
