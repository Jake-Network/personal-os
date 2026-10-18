"""Single owner application lock. Operating-system encryption is a separate control."""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.database import get_session
from app.modules.database.model import AppOwner
from app.modules.database.model.base import utcnow
from app.modules.security import session_manager as auth
from app.schema.security_schema import PasswordInput, SecurityStatus

router = APIRouter(prefix="/api/security", tags=["security"])


def _cookie(response: Response, token: str):
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", path="/",
                        secure=urlsplit(settings.frontend_url).scheme == "https")
    response.headers["Cache-Control"] = "no-store"


@router.get("/status", response_model=SecurityStatus)
def security_status(request: Request, response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    return auth.status(session, request.cookies.get(auth.COOKIE))


@router.post("/setup", response_model=SecurityStatus)
def setup_security(body: PasswordInput, response: Response, session: Session = Depends(get_session)):
    if session.get(AppOwner, 1):
        raise HTTPException(409, "소유자 비밀번호가 이미 설정되어 있습니다.")
    session.add(AppOwner(id=1, password_hash=auth.hash_password(body.password)))
    try:
        session.flush()
        token = auth.new_session(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "소유자 비밀번호가 이미 설정되어 있습니다.") from exc
    _cookie(response, token)
    return auth.status(session, token)


@router.post("/unlock", response_model=SecurityStatus)
def unlock_security(body: PasswordInput, response: Response, session: Session = Depends(get_session)):
    token = auth.authenticate(session, body.password)
    _cookie(response, token)
    return auth.status(session, token)


@router.post("/lock", status_code=204)
def lock_security(response: Response, session: Session = Depends(get_session)):
    auth.revoke_all(session)
    response.delete_cookie(auth.COOKIE, path="/", httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"


@router.post("/activity", response_model=SecurityStatus)
def security_activity(request: Request, response: Response, session: Session = Depends(get_session)):
    token = request.cookies.get(auth.COOKIE)
    record = auth.active_session(session, token)
    if not record:
        raise HTTPException(401, "앱 잠금을 해제하세요.")
    record.last_activity_at = utcnow()
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return auth.status(session, token)


@router.get("/diagnostics")
def security_diagnostics(response: Response):
    from app.modules.security.diagnostics import diagnose
    response.headers["Cache-Control"] = "no-store"
    return diagnose(settings.data_dir)
