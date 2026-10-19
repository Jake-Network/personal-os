"""Google authorization for Sheets; credentials never leave the backend."""
from urllib.parse import urlsplit, parse_qs
from app.modules.security import session_manager as app_auth
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.auth.errors import GoogleOAuthError
from app.modules.auth.google_oauth_manager import PENDING_TTL, google_oauth_manager
from app.modules.database import get_session

router = APIRouter(prefix="/api/finance/google", tags=["google-sheets"])
COOKIE = "google_oauth_binding"
COOKIE_PATH = "/api/finance/google"


def _check_origin(request: Request) -> None:
    # Browser POSTs may only originate from this application; non-browser clients have no Origin.
    origin = request.headers.get("origin")
    frontend = urlsplit(settings.frontend_url)
    allowed = {f"{frontend.scheme}://{frontend.netloc}", str(request.base_url).rstrip("/")}
    if origin and origin not in allowed:
        raise HTTPException(403, f"Google 로그인은 {settings.frontend_url.rstrip('/')}/settings/market 에서 시작하세요.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request is not allowed")


@router.get("/status", operation_id="get_google_status")
def get_status(response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    return google_oauth_manager.status(session)


@router.post("/login", operation_id="start_google_login")
def start_login(request: Request, response: Response, write_access: bool = False,
                return_to: Literal["finance", "holdings"] = "finance", session: Session = Depends(get_session)):
    _check_origin(request)
    try:
        authorize_url, binding = google_oauth_manager.start_login(session, write_access=write_access, return_to=return_to)
    except GoogleOAuthError as exc:
        raise HTTPException(400, exc.code) from exc
    state = parse_qs(urlsplit(authorize_url).query)["state"][0]
    proof = app_auth.bind_oauth(session, request.cookies[app_auth.COOKIE], state, "google")
    response.set_cookie("personal_os_oauth_google", proof, httponly=True, samesite="lax", max_age=600, path="/",
                        secure=urlsplit(settings.google_oauth_redirect_uri).scheme == "https")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(COOKIE, binding, httponly=True, samesite="lax", max_age=PENDING_TTL,
                        secure=urlsplit(settings.google_oauth_redirect_uri).scheme == "https", path=COOKIE_PATH)
    return {"authorize_url": authorize_url}


@router.get("/callback", include_in_schema=False)
async def callback(request: Request, session: Session = Depends(get_session)):
    # `return_to` keeps its API values; they name the screen that started the connection.
    result, target = "error", "/settings/market"
    try:
        conn = await google_oauth_manager.handle_callback(session, dict(request.query_params), request.cookies.get(COOKIE),
            authorization_guard=lambda: app_auth.guard_oauth_commit(session, request.cookies.get(app_auth.COOKIE)))
        result = "connected"
        target = {"finance": "/settings/market", "holdings": "/finance/investments"}.get(
            getattr(conn, "_google_return_to", "finance"), "/settings/market")
    except Exception:
        session.rollback()
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{target}?google_oauth={result}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, samesite="lax",
                           secure=urlsplit(settings.google_oauth_redirect_uri).scheme == "https")
    return response


@router.post("/disconnect", status_code=204, operation_id="disconnect_google")
async def disconnect(request: Request, response: Response, session: Session = Depends(get_session)):
    _check_origin(request)
    await google_oauth_manager.disconnect(session)
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, samesite="lax")
