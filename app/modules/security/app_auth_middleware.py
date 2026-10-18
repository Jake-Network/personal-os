"""Server enforced authentication and CSRF, including streamed response revocation."""
import hmac
import asyncio
from contextlib import suppress
from http.cookies import SimpleCookie

from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.modules.database import db
from app.modules.security import session_manager as auth

PUBLIC = frozenset({"/health", "/api/health", "/api/security/status", "/api/security/setup", "/api/security/unlock"})
BOOTSTRAP_WRITES = frozenset({"/api/security/setup", "/api/security/unlock"})
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CALLBACKS = {"/auth/callback": "chatgpt", "/api/finance/google/callback": "google"}


class AppAuthMiddleware:
    def __init__(self, app: ASGIApp, frontend_url: str):
        self.app = app
        self.frontend_origin = frontend_url.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, method = scope["path"].rstrip("/") or "/", scope["method"]
        app = scope.get("app")
        ready = getattr(getattr(app, "state", None), "security_schema_ready", True)
        if not ready and (path.startswith("/api/") and path != "/api/health" or path in CALLBACKS):
            await JSONResponse({"detail": "기존 DB를 백업한 후 명시적 마이그레이션을 실행하세요.",
                                "code": "schema_upgrade_required"}, status_code=503)(scope, receive, send)
            return
        private = (path.startswith("/api/") or path in CALLBACKS or path in {"/docs", "/redoc", "/openapi.json"}) and path not in PUBLIC
        if not private and path not in BOOTSTRAP_WRITES:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except Exception:
            pass
        token = cookie[auth.COOKIE].value if auth.COOKIE in cookie else None
        origin = headers.get("origin", "")
        if method in UNSAFE and origin != self.frontend_origin:
            await JSONResponse({"detail": "정확한 앱 Origin이 필요합니다."}, status_code=403)(scope, receive, send)
            return
        if path in BOOTSTRAP_WRITES:
            await self.app(scope, receive, send)
            return
        with db.session() as session:
            record = auth.active_session(session, token)
            if not record:
                await JSONResponse({"detail": "앱 잠금을 해제하세요.", "code": "app_locked"}, status_code=401)(scope, receive, send)
                return
            if method in UNSAFE and not hmac.compare_digest(headers.get("x-csrf-token", ""), record.csrf_token):
                await JSONResponse({"detail": "CSRF 검증에 실패했습니다."}, status_code=403)(scope, receive, send)
                return
            scope.setdefault("state", {})["app_session_hash"] = record.token_hash
            if path in CALLBACKS:
                from urllib.parse import parse_qs
                params = parse_qs(scope.get("query_string", b"").decode())
                provider = CALLBACKS[path]
                proof = cookie[f"personal_os_oauth_{provider}"].value if f"personal_os_oauth_{provider}" in cookie else None
                if not auth.consume_oauth(session, token, params.get("state", [""])[0], provider, proof):
                    await JSONResponse({"detail": "OAuth 브라우저 또는 세션이 만료되었습니다."}, status_code=403)(scope, receive, send)
                    return
        streaming = asyncio.Event()
        revoked = False
        completed = False

        async def guarded_send(message):
            nonlocal completed
            if message["type"] == "http.response.start":
                response_headers = message.get("headers", [])
                if any(k.lower() == b"content-type" and b"text/event-stream" in v for k, v in response_headers):
                    streaming.set()
                message["headers"] = [(k, v) for k, v in response_headers if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
            await send(message)

        application = asyncio.create_task(self.app(scope, receive, guarded_send))

        async def watch_session():
            nonlocal revoked
            await streaming.wait()
            while not application.done():
                try:
                    with db.session() as check:
                        valid = auth.active_session(check, token) is not None
                except SQLAlchemyError:
                    valid = False  # A failed authorization recheck must stop an outbound stream.
                if not valid:
                    revoked = True
                    application.cancel()
                    return
                await asyncio.sleep(0.25)

        watchdog = asyncio.create_task(watch_session())
        try:
            await application
        except asyncio.CancelledError:
            if not revoked:
                raise
            if not completed:
                await send({"type": "http.response.body", "body": b'event: error\ndata: {"code":"app_locked"}\n\n', "more_body": False})
        finally:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
