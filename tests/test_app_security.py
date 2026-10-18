"""Synthetic local authentication boundary and session revocation regressions."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.modules.database.model import AppOwner, AppSession
from app.modules.database.model.base import utcnow
from app.modules.security import session_manager as auth


@pytest.fixture
def locked_client(session, monkeypatch):
    from app.main import app
    from app.modules.documents import document_manager

    async def idle(_db, stop):
        await stop.wait()
    monkeypatch.setattr(document_manager, "process_pending", idle)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.headers["Origin"] = settings.frontend_url
        yield client


def setup(client):
    response = client.post("/api/security/setup", json={"password": "synthetic-password-123"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def test_private_api_and_openapi_require_owner_session(locked_client):
    assert locked_client.get("/api/health").status_code == 200
    assert locked_client.get("/api/security/status").json()["configured"] is False
    assert locked_client.get("/api/dashboard").status_code == 401
    assert locked_client.get("/openapi.json").status_code == 401
    setup(locked_client)
    assert locked_client.get("/api/settings/ai-provider").status_code == 200
    assert locked_client.get("/openapi.json").status_code == 200
    assert locked_client.post("/api/security/setup", json={"password": "different-password"}).status_code == 409


def test_passwords_and_bearer_tokens_are_not_stored_in_plaintext(locked_client, session):
    response = setup(locked_client)
    assert "HttpOnly" in response.headers["set-cookie"]
    owner = session.get(AppOwner, 1)
    assert owner.password_hash.startswith("scrypt$")
    assert "synthetic-password" not in owner.password_hash
    record = session.scalars(select(AppSession)).one()
    assert record.token_hash != locked_client.cookies[auth.COOKIE]
    assert auth.verify_password("synthetic-password-123", owner.password_hash)


def test_csrf_requires_matching_token_and_exact_origin(locked_client):
    setup(locked_client)
    token = locked_client.headers.pop("X-CSRF-Token")
    assert locked_client.post("/api/security/activity").status_code == 403
    locked_client.headers["X-CSRF-Token"] = token
    assert locked_client.post("/api/security/activity", headers={"Origin": "http://localhost:9999"}).status_code == 403
    assert locked_client.post("/api/security/activity").status_code == 200


def test_all_tabs_lock_and_old_session_cannot_be_replayed(locked_client):
    setup(locked_client)
    cookie = locked_client.cookies[auth.COOKIE]
    assert locked_client.post("/api/security/lock").status_code == 204
    locked_client.cookies.set(auth.COOKIE, cookie)
    assert locked_client.get("/api/settings/ai-provider").status_code == 401
    assert locked_client.get("/auth/callback?state=stale&code=ignored").status_code == 401
    response = locked_client.post("/api/security/unlock", json={"password": "synthetic-password-123"})
    assert response.status_code == 200
    assert response.json()["authenticated"]


def test_polling_does_not_renew_idle_timeout(locked_client, session):
    setup(locked_client)
    record = session.scalars(select(AppSession)).one()
    initial = record.last_activity_at
    assert locked_client.get("/api/security/status").json()["authenticated"]
    session.refresh(record)
    assert record.last_activity_at == initial
    record.last_activity_at = utcnow() - timedelta(minutes=16)
    session.commit()
    assert locked_client.get("/api/settings/ai-provider").status_code == 401
    assert not locked_client.get("/api/security/status").json()["authenticated"]


def test_login_attempts_are_rate_limited(locked_client):
    setup(locked_client)
    locked_client.post("/api/security/lock")
    for _ in range(5):
        assert locked_client.post("/api/security/unlock", json={"password": "incorrect-password"}).status_code == 401
    assert locked_client.post("/api/security/unlock", json={"password": "synthetic-password-123"}).status_code == 429


def test_oauth_bound_to_live_session_and_one_time_browser_proof(locked_client, session):
    setup(locked_client)
    token = locked_client.cookies[auth.COOKIE]
    proof = auth.bind_oauth(session, token, "synthetic-state", "chatgpt")
    assert not auth.consume_oauth(session, token, "synthetic-state", "chatgpt", "wrong")
    assert auth.consume_oauth(session, token, "synthetic-state", "chatgpt", proof)
    assert not auth.consume_oauth(session, token, "synthetic-state", "chatgpt", proof)
    auth.bind_oauth(session, token, "stale-state", "chatgpt")
    locked_client.post("/api/security/lock")
    assert not auth.consume_oauth(session, token, "stale-state", "chatgpt", proof)


@pytest.mark.parametrize("failure_mode", ["lock", "database_unavailable"])
def test_lock_cancels_provider_stream_even_without_next_delta(session, monkeypatch, failure_mode):
    import asyncio
    from app.modules.security.app_auth_middleware import AppAuthMiddleware

    async def scenario():
        token = auth.new_session(session)
        started = asyncio.Event()
        cancelled = asyncio.Event()
        sent = []

        async def provider_app(scope, receive, send):
            try:
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"text/event-stream")]})
                started.set()
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            sent.append(message)

        middleware = AppAuthMiddleware(provider_app, settings.frontend_url)
        scope = {"type": "http", "path": "/api/advisor/stream", "method": "GET", "scheme": "http",
                 "headers": [(b"cookie", f"{auth.COOKIE}={token}".encode())]}
        task = asyncio.create_task(middleware(scope, receive, send))
        await started.wait()
        if failure_mode == "lock":
            auth.revoke_all(session)
        else:
            from sqlalchemy.exc import OperationalError
            def unavailable(*_):
                raise OperationalError("SELECT", {}, RuntimeError("synthetic database outage"))
            monkeypatch.setattr(auth, "active_session", unavailable)
        await asyncio.wait_for(task, timeout=2)
        assert cancelled.is_set()
        assert b"app_locked" in sent[-1]["body"]
        assert not sent[-1]["more_body"]

    asyncio.run(scenario())


def test_production_services_cannot_be_redirected_to_remote_hosts():
    from app.modules.security.deployment_checks import validate_local_services
    validate_local_services("postgresql+psycopg://user@db/personal", "http://embeddings:11434")
    validate_local_services("sqlite:///local.db", "http://127.0.0.1:11434")
    with pytest.raises(ValueError):
        validate_local_services("postgresql://user@remote.example/db", "http://embeddings:11434")
    with pytest.raises(ValueError):
        validate_local_services("sqlite:///local.db", "https://remote.example/embed")


def test_wsl_and_container_diagnostics_never_infer_host_protection(tmp_path):
    from app.modules.security.diagnostics import diagnose
    def forbidden_run(_):
        raise AssertionError("Container observations cannot establish host protection")
    for release, container in [("6.6-microsoft-standard-WSL2", False), ("6.6-linux", True)]:
        result = diagnose(tmp_path, run=forbidden_run, release=release, container=container)
        assert all(check["state"] == "unverified" for check in result["checks"])
        assert result["host_settings_modified"] is False


def test_native_diagnostics_keep_storage_unknown_and_report_observed_firewall(tmp_path):
    from app.modules.security.diagnostics import diagnose
    def run(command):
        return '{"filesystems":[{"fstype":"ext4"}]}' if command[0] == "findmnt" else "Status: inactive"
    result = diagnose(tmp_path, run=run, release="6.6-linux", container=False)
    assert result["checks"][0]["state"] == "unverified"
    assert result["checks"][1]["state"] == "action_needed"


@pytest.mark.parametrize("provider", ["chatgpt", "google"])
def test_lock_during_oauth_exchange_prevents_credential_persistence(session, provider):
    import asyncio
    from urllib.parse import parse_qs, urlsplit
    import httpx
    from cryptography.fernet import Fernet
    from fastapi import HTTPException
    from app.config import Settings
    from app.modules.auth.crypto import TokenCipher
    from app.modules.auth.oauth_manager import OAuthManager
    from app.modules.auth.google_oauth_manager import GoogleOAuthManager
    from app.modules.database.model import GoogleOAuthConnection, OAuthCredential

    token = auth.new_session(session)
    def handler(_request):
        auth.revoke_all(session)
        return httpx.Response(200, json={"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                                       "id_token": "synthetic-identity", "expires_in": 3600,
                                       "scope": "openid email chatgpt.tokens.use.direct https://www.googleapis.com/auth/drive.file"})
    kwargs = {"cipher": TokenCipher(Fernet.generate_key()),
              "http_factory": lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
              "id_token_verifier": lambda token, aud, nonce: {"iss": "https://accounts.google.com" if provider == "google" else "https://auth.openai.com",
                                               "aud": aud, "nonce": nonce, "sub": "synthetic-user",
                                               "email": "test@example.com", "email_verified": True}}
    config = Settings(google_oauth_client_id="synthetic-client", google_oauth_client_secret="synthetic-secret")
    manager = GoogleOAuthManager(config, **kwargs) if provider == "google" else OAuthManager(config, **kwargs)
    login = manager.start_login(session)
    url, binding = login if provider == "google" else (login, None)
    state = parse_qs(urlsplit(url).query)["state"][0]
    params = {"state": state, "code": "synthetic-code", "client_id": "synthetic-client"}
    args = (session, params, binding) if provider == "google" else (session, params)
    with pytest.raises(HTTPException) as error:
        asyncio.run(manager.handle_callback(*args, authorization_guard=lambda: auth.guard_oauth_commit(session, token)))
    assert error.value.status_code == 401
    session.rollback()
    assert session.scalar(select(OAuthCredential)) is None
    assert session.scalar(select(GoogleOAuthConnection)) is None


def test_same_account_oauth_reconnect_requires_new_transfer_confirmation(locked_client, session, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    import httpx
    from cryptography.fernet import Fernet
    from app.config import Settings
    from app.modules.auth.crypto import TokenCipher
    from app.modules.auth.oauth_manager import OAuthManager
    from app.modules.database import db
    from app.modules.llm import transfer_policy
    from app.router import ai_provider_router, oauth_callback_router

    setup(locked_client)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "id_token": "synthetic-id",
        "expires_in": 3600, "scope": "openid email chatgpt.tokens.use.direct"}))
    manager = OAuthManager(Settings(), TokenCipher(Fernet.generate_key()),
        http_factory=lambda: httpx.AsyncClient(transport=transport),
        id_token_verifier=lambda token, aud, nonce: {"iss": "https://auth.openai.com", "sub": "synthetic-same-user",
                                                   "aud": aud, "nonce": nonce})
    monkeypatch.setattr(ai_provider_router, "oauth_manager", manager)
    monkeypatch.setattr(oauth_callback_router, "oauth_manager", manager)

    def reconnect():
        response = locked_client.post("/api/settings/ai-provider/chatgpt/login")
        assert response.status_code == 200
        state = parse_qs(urlsplit(response.json()["authorize_url"]).query)["state"][0]
        callback = locked_client.get("/auth/callback", params={"state": state, "code": "synthetic-code", "client_id": "synthetic-client"}, follow_redirects=False)
        assert callback.status_code == 303
        assert "chatgpt=connected" in callback.headers["location"]

    reconnect()
    transfer_policy.confirm(session, "chatgpt_plan", True, True)
    assert transfer_policy.status(session, "chatgpt_plan")["confirmed"]
    reconnect()
    with db.session() as check:
        assert not transfer_policy.status(check, "chatgpt_plan")["confirmed"]


def test_global_lock_waits_for_inflight_password_check_and_revokes_new_session(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    from threading import Event
    import pytest
    from app.modules.database.database import Database
    from app.modules.database.model import AppOwner
    from app.modules.security import session_manager as auth

    database = Database()
    database.init(f"sqlite:///{tmp_path / 'concurrent-auth.db'}")
    database.create_schema()
    with database.session() as session:
        session.add(AppOwner(id=1, password_hash="synthetic-test-only"))
        session.commit()
    checking, release, locking = Event(), Event(), Event()

    def paused_password_check(*_args):
        checking.set()
        assert release.wait(5)
        return True

    def unlock():
        with database.session() as session:
            return auth.authenticate(session, "synthetic-test-password")

    def lock():
        locking.set()
        with database.session() as session:
            auth.revoke_all(session)

    monkeypatch.setattr(auth, "verify_password", paused_password_check)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            login = pool.submit(unlock)
            assert checking.wait(5)
            revocation = pool.submit(lock)
            assert locking.wait(5)
            try:
                # Revocation must not finish then allow the paused login to create
                # an authenticated session after the user's global lock.
                with pytest.raises(FutureTimeout):
                    revocation.result(timeout=0.1)
            finally:
                release.set()
            token = login.result(timeout=5)
            revocation.result(timeout=5)
        with database.session() as session:
            assert auth.active_session(session, token) is None
    finally:
        release.set()
        database.engine.dispose()
