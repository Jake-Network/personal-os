import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.modules.auth.crypto import TokenCipher
from app.modules.auth.oauth_manager import OAuthManager
from app.modules.database.model import OAuthCredential
from app.modules.llm.errors import AuthRequired, ConsentDeclined


def make_manager(handler):
    transport = httpx.MockTransport(handler)
    return OAuthManager(
        Settings(),
        TokenCipher(Fernet.generate_key()),
        http_factory=lambda: httpx.AsyncClient(transport=transport),
        id_token_verifier=lambda token, aud, nonce: {
            "iss": "https://auth.openai.com", "sub": "user-1", "aud": aud, "email": "me@example.com", "nonce": nonce,
        },
    )


def token_endpoint(scope: str, calls: list):
    def handler(request: httpx.Request):
        form = parse_qs(request.content.decode())
        calls.append(form)
        n = len(calls)
        return httpx.Response(200, json={
            "access_token": f"at-{n}", "refresh_token": f"rt-{n}", "id_token": "idt", "expires_in": 3600,
            "scope": scope, "token_type": "Bearer",
        })
    return handler


def login(manager, session, **extra):
    url = manager.start_login(session)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    params = {"code": "c", "state": q["state"], "client_id": "issued-123", **extra}
    return q, asyncio.run(manager.handle_callback(session, params))


def test_authorize_url_follows_the_documented_flow(session):
    manager = make_manager(token_endpoint("", []))
    q = {k: v[0] for k, v in parse_qs(urlparse(manager.start_login(session)).query).items()}
    assert q["client_id"] == "dynamic_agent_client"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["resource"] == "https://api.openai.com/v1"
    assert set(q["scope"].split()) == {"openid", "profile", "email", "offline_access", "resource.invoke",
                                       "chatgpt.tokens.use.direct"}
    assert q["redirect_uri"].startswith("http://127.0.0.1:") and q["redirect_uri"].endswith("/auth/callback")
    assert q["ext_agent_host_id"].startswith("urn:uuid:")


def test_callback_stores_encrypted_tokens_and_enables_plan_usage(session):
    calls: list = []
    manager = make_manager(token_endpoint("openid profile email offline_access resource.invoke "
                                          "chatgpt.tokens.use.direct", calls))
    _, conn = login(manager, session)
    assert conn.plan_usage_enabled and conn.client_id == "issued-123"
    assert calls[0]["code_verifier"] and calls[0]["client_id"] == ["issued-123"]
    blob = session.get(OAuthCredential, conn.id).ciphertext
    assert b"at-1" not in blob and b"rt-1" not in blob
    status = json.dumps(manager.status(session))
    assert "at-1" not in status and "rt-1" not in status
    # Re-login reuses the issued client id.
    q = parse_qs(urlparse(manager.start_login(session)).query)
    assert q["client_id"] == ["issued-123"]


def test_missing_plan_scope_keeps_sign_in_but_disables_usage(session):
    manager = make_manager(token_endpoint("openid profile email", []))
    _, conn = login(manager, session)
    assert conn.status == "connected" and not conn.plan_usage_enabled


def test_unknown_state_and_access_denied_are_rejected(session):
    manager = make_manager(token_endpoint("", []))
    with pytest.raises(ConsentDeclined):
        asyncio.run(manager.handle_callback(session, {"state": "forged", "code": "c"}))
    url = manager.start_login(session)
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(ConsentDeclined):
        asyncio.run(manager.handle_callback(session, {"state": state, "error": "access_denied"}))


def test_expired_access_token_is_refreshed_with_rotation(session):
    calls: list = []
    manager = make_manager(token_endpoint("chatgpt.tokens.use.direct openid", calls))
    _, conn = login(manager, session)
    conn.access_expires_at = conn.access_expires_at.replace(year=2000)
    session.commit()
    _, token = asyncio.run(manager.access_token(session))
    assert token == "at-2"
    assert calls[1]["grant_type"] == ["refresh_token"] and calls[1]["refresh_token"] == ["rt-1"]
    assert manager._load_tokens(session, conn)["refresh_token"] == "rt-2"


def test_revoked_refresh_token_requires_reauth(session):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "id_token": "i",
                                             "expires_in": 1, "scope": "chatgpt.tokens.use.direct"})
        return httpx.Response(400, json={"error": "invalid_grant"})

    manager = make_manager(handler)
    _, conn = login(manager, session)
    with pytest.raises(AuthRequired):
        asyncio.run(manager.access_token(session))
    assert conn.status == "needs_reauth" and conn.last_error_code == "invalid_grant"


def test_disconnect_cancels_pending_login_even_without_existing_connection(session):
    manager = make_manager(token_endpoint("chatgpt.tokens.use.direct", []))
    state = parse_qs(urlparse(manager.start_login(session)).query)["state"][0]
    asyncio.run(manager.disconnect(session))
    with pytest.raises(ConsentDeclined):
        asyncio.run(manager.handle_callback(session, {"state": state, "code": "synthetic", "client_id": "synthetic"}))
    assert session.query(OAuthCredential).count() == 0


@pytest.mark.parametrize("during_refresh", [False, True])
def test_disconnect_during_token_exchange_cannot_restore_credentials(session, during_refresh):
    from app.modules.llm import transfer_policy
    from sqlalchemy import select

    interrupt = False
    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"revocation_endpoint": "https://auth.openai.com/revoke"})
        if request.url.path == "/revoke":
            return httpx.Response(200, json={})
        if interrupt:
            await manager.disconnect(session)
        return httpx.Response(200, json={"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                                       "id_token": "synthetic-id", "expires_in": 3600,
                                       "scope": "chatgpt.tokens.use.direct"})
    manager = make_manager(handler)
    _, conn = login(manager, session)
    transfer_policy.confirm(session, "chatgpt_plan", True, True)
    interrupt = True
    if during_refresh:
        operation = manager.access_token(session, force_refresh=True)
    else:
        state = parse_qs(urlparse(manager.start_login(session)).query)["state"][0]
        operation = manager.handle_callback(session, {"state": state, "code": "synthetic", "client_id": conn.client_id})
    with pytest.raises(ConsentDeclined, match="disconnect"):
        asyncio.run(operation)
    session.rollback()
    session.refresh(conn)
    assert conn.status == "disconnected"
    assert session.scalar(select(OAuthCredential)) is None
    assert not transfer_policy.status(session, "chatgpt_plan")["confirmed"]


def test_disconnect_commits_local_revocation_before_remote_request(session):
    from app.modules.database import db
    from app.modules.database.model import OAuthConnection
    from app.modules.llm import transfer_policy
    from sqlalchemy import select

    calls = []
    manager = make_manager(token_endpoint("chatgpt.tokens.use.direct", calls))
    _, conn = login(manager, session)
    transfer_policy.confirm(session, "chatgpt_plan", True, True)

    def unavailable(request):
        with db.session() as check:
            assert check.get(OAuthConnection, conn.id).status == "disconnected"
            assert check.scalar(select(OAuthCredential)) is None
            assert not transfer_policy.status(check, "chatgpt_plan")["confirmed"]
        raise httpx.ConnectError("synthetic provider unavailable", request=request)

    manager.http_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(unavailable))
    asyncio.run(manager.disconnect(session))
    assert not manager.status(session)["connected"]
