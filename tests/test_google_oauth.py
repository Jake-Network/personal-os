"""Google linking regressions: synthetic OAuth responses and no live Google traffic."""
import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import Settings
from app.modules.auth.crypto import TokenCipher
from app.modules.auth.google_oauth_manager import GoogleOAuthManager
from app.modules.database.model import GoogleOAuthConnection, GoogleOAuthPending

READONLY = "https://www.googleapis.com/auth/drive.file"
SCOPES = f"openid email {READONLY}"


def make_manager(handler=None, verifier=None, **settings_overrides):
    def default_handler(request):
        return httpx.Response(200, json={
            "access_token": "google-access-secret", "refresh_token": "google-refresh-secret",
            "id_token": "signed-identity", "expires_in": 3600, "scope": SCOPES,
            "token_type": "Bearer",
        })

    def default_verifier(token, audience, nonce):
        return {"iss": "https://accounts.google.com", "sub": "google-user-1", "aud": audience,
                "email": "person@example.com", "email_verified": True, "nonce": nonce}

    settings = Settings(google_oauth_client_id="google-client", google_oauth_client_secret="client-secret",
                        **settings_overrides)
    return GoogleOAuthManager(
        settings, TokenCipher(Fernet.generate_key()),
        http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler or default_handler)),
        id_token_verifier=verifier or default_verifier,
    )


def start(manager, session):
    url, binding = manager.start_login(session)
    query = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
    return query, binding


def connect(manager, session):
    query, binding = start(manager, session)
    connection = asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "auth-code"}, binding))
    return query, binding, connection


def test_google_authorization_requests_only_identity_and_drive_file(session):
    manager = make_manager()
    query, binding = start(manager, session)
    assert query["response_type"] == "code"
    assert query["client_id"] == "google-client"
    assert set(query["scope"].split()) == {"openid", "email", READONLY}
    assert query["access_type"] == "offline"
    assert "consent" in query["prompt"].split()
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    assert query["nonce"] and binding
    pending = session.scalars(select(GoogleOAuthPending)).one()
    assert query["state"] != pending.state_hash and binding != pending.binding_hash
    assert b"code_verifier" not in pending.ciphertext


def test_google_callback_encrypts_tokens_and_submits_pkce_verifier(session):
    calls = []

    def handler(request):
        calls.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "google-access-secret", "refresh_token": "google-refresh-secret",
                                       "id_token": "signed-identity", "expires_in": 3600, "scope": SCOPES})

    manager = make_manager(handler)
    query, _, connection = connect(manager, session)
    assert connection.status == "connected" and connection.email == "person@example.com"
    form = calls[0]
    assert form["grant_type"] == ["authorization_code"]
    assert form["client_secret"] == ["client-secret"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
    assert expected == query["code_challenge"]
    assert b"google-access-secret" not in connection.ciphertext
    assert b"google-refresh-secret" not in connection.ciphertext
    status = json.dumps(manager.status(session), default=str)
    assert "google-access-secret" not in status and "google-refresh-secret" not in status
    assert "client-secret" not in status
    assert session.scalars(select(GoogleOAuthPending)).all() == []


def test_google_unknown_state_and_wrong_browser_never_exchange_code(session):
    def handler(request):
        pytest.fail("Invalid browser/state must never reach Google token endpoint")

    manager = make_manager(handler)
    query, binding = start(manager, session)
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": "forged", "code": "code"}, binding))
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code"}, "wrong-browser"))


def test_google_expired_login_and_callback_replay_rejected(session):
    manager = make_manager()
    query, binding = start(manager, session)
    pending = session.scalars(select(GoogleOAuthPending)).one()
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code"}, binding))
    query, binding, _ = connect(manager, session)
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code"}, binding))


def test_google_consent_cancel_consumes_state_without_storing_credentials(session):
    manager = make_manager()
    query, binding = start(manager, session)
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "error": "access_denied"}, binding))
    assert session.scalars(select(GoogleOAuthConnection)).all() == []
    assert session.scalars(select(GoogleOAuthPending)).all() == []


@pytest.mark.parametrize("bad_claim", [
    {"nonce": "wrong"}, {"iss": "https://attacker.invalid"}, {"aud": "other-app"},
    {"email_verified": False}, {"sub": ""},
])
def test_google_untrusted_identity_claims_are_rejected(session, bad_claim):
    def verifier(token, audience, nonce):
        return {"iss": "https://accounts.google.com", "sub": "google-user-1", "aud": audience,
                "email": "person@example.com", "email_verified": True, "nonce": nonce, **bad_claim}

    manager = make_manager(verifier=verifier)
    query, binding = start(manager, session)
    with pytest.raises(ValueError):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code"}, binding))
    assert session.scalars(select(GoogleOAuthConnection)).all() == []


@pytest.mark.parametrize("scope", ["openid email", "openid email https://www.googleapis.com/auth/drive.readonly"])
def test_google_sheets_permission_must_be_granted(session, scope):
    manager = make_manager(lambda request: httpx.Response(200, json={
        "access_token": "access", "refresh_token": "refresh", "id_token": "identity",
        "expires_in": 3600, "scope": scope,
    }))
    with pytest.raises(ValueError, match="missing_scope"):
        connect(manager, session)
    assert session.scalars(select(GoogleOAuthConnection)).all() == []


def test_google_missing_client_configuration_cannot_start_authorization(session):
    manager = GoogleOAuthManager(Settings(google_oauth_client_id="", google_oauth_client_secret=""))
    assert manager.status(session)["configured"] is False
    with pytest.raises(ValueError, match="not_configured"):
        manager.start_login(session)
    assert session.scalars(select(GoogleOAuthPending)).all() == []


def test_google_refresh_persists_rotated_access_token_and_original_refresh(session, monkeypatch):
    manager = make_manager()
    _, _, connection = connect(manager, session)
    connection.access_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    session.commit()
    calls = []

    def refresh(credentials, request):
        calls.append(credentials.refresh_token)
        credentials.token = "refreshed-access-secret"
        credentials.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr("app.modules.auth.google_oauth_manager.Credentials.refresh", refresh)
    credentials = manager.get_credentials(session)
    assert calls == ["google-refresh-secret"]
    assert credentials.token == "refreshed-access-secret"
    assert credentials.refresh_token == "google-refresh-secret"
    persisted = manager.cipher.decrypt(session.get(GoogleOAuthConnection, 1).ciphertext)
    assert persisted == {"access_token": "refreshed-access-secret", "refresh_token": "google-refresh-secret"}
    assert manager.get_credentials(session).token == "refreshed-access-secret"
    assert calls == ["google-refresh-secret"]


def test_google_revoked_refresh_deletes_tokens_and_blocks_fallback(session, monkeypatch):
    from google.auth.exceptions import RefreshError

    manager = make_manager()
    _, _, connection = connect(manager, session)
    connection.access_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    session.commit()

    def refresh(credentials, request):
        raise RefreshError("response includes google-refresh-secret", {"error": "invalid_grant"})

    monkeypatch.setattr("app.modules.auth.google_oauth_manager.Credentials.refresh", refresh)
    with pytest.raises(ValueError, match="refresh_rejected"):
        manager.get_credentials(session)
    assert connection.status == "needs_reauth" and connection.ciphertext is None
    assert "google-refresh-secret" not in json.dumps(manager.status(session))
    with pytest.raises(ValueError, match="needs_reauth"):
        manager.get_credentials(session)


def test_google_transient_refresh_failure_preserves_tokens_and_reports_safe_error(session, monkeypatch):
    from google.auth.exceptions import RefreshError

    manager = make_manager()
    _, _, connection = connect(manager, session)
    connection.access_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    session.commit()
    original = connection.ciphertext

    def refresh(credentials, request):
        raise RefreshError("google-access-secret", {"error": "temporarily_unavailable"})

    monkeypatch.setattr("app.modules.auth.google_oauth_manager.Credentials.refresh", refresh)
    with pytest.raises(ValueError, match="refresh_failed"):
        manager.get_credentials(session)
    assert connection.status == "connected" and connection.ciphertext == original
    assert connection.last_error_code == "refresh_failed"


def test_google_disconnect_revokes_best_effort_and_keeps_chatgpt_independent(session):
    from app.modules.database.model import OAuthConnection

    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/revoke":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"access_token": "google-access-secret", "refresh_token": "google-refresh-secret",
                                       "id_token": "identity", "expires_in": 3600, "scope": SCOPES})

    manager = make_manager(handler)
    _, _, connection = connect(manager, session)
    chatgpt = OAuthConnection(provider="chatgpt", status="connected", issuer="https://auth.openai.com",
                             subject="chatgpt-user", client_id="chatgpt-client", ext_agent_host_id="host-id")
    session.add(chatgpt)
    session.commit()
    start(manager, session)
    asyncio.run(manager.disconnect(session))
    assert connection.status == "disconnected" and connection.ciphertext is None
    assert session.scalars(select(GoogleOAuthPending)).all() == []
    assert parse_qs(requests[-1].content.decode()) == {"token": ["google-refresh-secret"]}
    assert session.get(OAuthConnection, chatgpt.id).status == "connected"
    with pytest.raises(ValueError, match="disconnected"):
        manager.get_credentials(session)


def test_google_disconnect_before_first_login_disables_adc_fallback(session):
    manager = make_manager()
    assert manager.get_credentials(session) is None
    asyncio.run(manager.disconnect(session))
    with pytest.raises(ValueError, match="disconnected"):
        manager.get_credentials(session)


@pytest.fixture
def google_api(client, monkeypatch):
    from app.router import google_oauth_router

    manager = make_manager()
    monkeypatch.setattr(google_oauth_router, "google_oauth_manager", manager)
    return client, manager


def test_google_api_callback_sets_browser_binding_and_never_exposes_tokens(google_api):
    client, manager = google_api
    response = client.post("/api/finance/google/login")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/finance/google" in cookie
    query = parse_qs(urlparse(response.json()["authorize_url"]).query)
    response = client.get("/api/finance/google/callback", params={"state": query["state"][0], "code": "private-auth-code"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/finance?google_oauth=connected")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "Max-Age=0" in response.headers["set-cookie"]
    status = client.get("/api/finance/google/status")
    assert status.status_code == 200 and status.json()["connected"] is True
    assert status.headers["cache-control"] == "no-store"
    for secret in ("google-access-secret", "google-refresh-secret", "private-auth-code", "client-secret"):
        assert secret not in status.text + response.text + response.headers["location"]


def test_google_api_callback_without_browser_binding_fails_closed(google_api):
    client, manager = google_api
    response = client.post("/api/finance/google/login")
    query = parse_qs(urlparse(response.json()["authorize_url"]).query)
    client.cookies.clear()
    response = client.get("/api/finance/google/callback", params={"state": query["state"][0], "code": "stolen-code"},
                          follow_redirects=False)
    assert response.status_code == 401
    assert client.get("/api/finance/google/status").status_code == 401


@pytest.mark.parametrize("headers", [{"origin": "https://attacker.invalid"}, {"sec-fetch-site": "cross-site"}])
def test_google_api_login_and_disconnect_reject_cross_site_requests(google_api, headers):
    client, _ = google_api
    assert client.post("/api/finance/google/login", headers=headers).status_code == 403
    assert client.post("/api/finance/google/disconnect", headers=headers).status_code == 403


def test_google_api_disconnect_removes_credentials(google_api):
    client, manager = google_api
    response = client.post("/api/finance/google/login")
    state = parse_qs(urlparse(response.json()["authorize_url"]).query)["state"][0]
    assert client.get("/api/finance/google/callback", params={"state": state, "code": "code"},
                      follow_redirects=False).headers["location"].endswith("connected")
    assert client.post("/api/finance/google/disconnect").status_code == 204
    status = client.get("/api/finance/google/status").json()
    assert status["status"] == "disconnected" and status["credential_source"] == "none"


def test_google_normalized_email_scope_is_accepted(session):
    manager = make_manager(lambda request: httpx.Response(200, json={
        "access_token": "access", "refresh_token": "refresh", "id_token": "identity", "expires_in": 3600,
        "scope": f"openid https://www.googleapis.com/auth/userinfo.email {READONLY}",
    }))
    _, _, connection = connect(manager, session)
    assert connection.status == "connected"


def test_google_refresh_uses_official_credentials_and_saves_rotated_tokens(session):
    from types import SimpleNamespace

    manager = make_manager()
    _, _, connection = connect(manager, session)
    connection.access_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    session.commit()
    calls = []

    def request(url, method="GET", body=None, headers=None, **kwargs):
        calls.append((url, method, parse_qs(body.decode())))
        return SimpleNamespace(status=200, data=json.dumps({
            "access_token": "official-refreshed-access", "refresh_token": "official-rotated-refresh",
            "expires_in": 3600, "token_type": "Bearer", "scope": SCOPES,
        }).encode(), headers={})

    manager.request_factory = lambda: request
    credentials = manager.get_credentials(session)
    assert credentials.token == "official-refreshed-access"
    assert credentials.refresh_token == "official-rotated-refresh"
    assert len(calls) == 1
    url, method, form = calls[0]
    assert url == "https://oauth2.googleapis.com/token" and method == "POST"
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["google-refresh-secret"]
    assert manager.cipher.decrypt(connection.ciphertext) == {
        "access_token": "official-refreshed-access", "refresh_token": "official-rotated-refresh",
    }


def test_google_upstream_errors_are_sanitized_and_state_cannot_replay(session):
    manager = make_manager(lambda request: httpx.Response(400, json={
        "error": "invalid_grant", "error_description": "private-auth-code client-secret",
    }))
    query, binding = start(manager, session)
    with pytest.raises(ValueError, match="authorization_failed") as error:
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "private-auth-code"}, binding))
    assert str(error.value) == "authorization_failed"
    with pytest.raises(ValueError, match="invalid_state"):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "private-auth-code"}, binding))
    assert session.scalars(select(GoogleOAuthConnection)).all() == []


def test_google_callback_requires_refresh_token_for_server_side_sync(session):
    manager = make_manager(lambda request: httpx.Response(200, json={
        "access_token": "access", "id_token": "identity", "expires_in": 3600, "scope": SCOPES,
    }))
    with pytest.raises(ValueError, match="missing_refresh_token"):
        connect(manager, session)
    assert session.scalars(select(GoogleOAuthConnection)).all() == []


def test_google_disconnect_during_token_exchange_cancels_pending_callback(session):
    manager = None

    async def handler(request):
        # Token exchange is outside the DB transaction; simulate a concurrent disconnect.
        await manager.disconnect(session)
        return httpx.Response(200, json={
            "access_token": "late-access", "refresh_token": "late-refresh", "id_token": "identity",
            "expires_in": 3600, "scope": SCOPES,
        })

    manager = make_manager(handler)
    query, binding = start(manager, session)
    with pytest.raises(ValueError, match="login_cancelled"):
        asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code"}, binding))
    connection = session.get(GoogleOAuthConnection, 1)
    assert connection.status == "disconnected" and connection.ciphertext is None
    assert session.scalars(select(GoogleOAuthPending)).all() == []
    with pytest.raises(ValueError, match="disconnected"):
        manager.get_credentials(session)
