"""Optional write grants require explicit consent and stay bound to the login state."""
import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.modules.auth.errors import GoogleOAuthError
from app.modules.auth.google_checks import READ_SCOPE, WRITE_SCOPE
from app.modules.database.model import GoogleOAuthConnection, GoogleOAuthPending
from test_google_oauth import make_manager


def begin(manager, session, write_access=False):
    url, binding = manager.start_login(session, write_access=write_access)
    query = {key: value[0] for key, value in parse_qs(urlparse(url).query).items()}
    return query, binding


def exchange(manager, session, query, binding, **params):
    return asyncio.run(manager.handle_callback(session, {"state": query["state"], "code": "code", **params}, binding))


def granting(scope):
    return lambda request: httpx.Response(200, json={
        "access_token": "access", "refresh_token": "refresh", "id_token": "identity", "expires_in": 3600,
        "scope": scope,
    })


def test_write_consent_is_optional_and_bound_to_encrypted_pending_state(session):
    manager = make_manager()
    query, _ = begin(manager, session)
    assert set(query["scope"].split()) == {"openid", "email", READ_SCOPE}
    pending = session.scalars(select(GoogleOAuthPending)).one()
    assert manager.cipher.decrypt(pending.ciphertext)["required_scope"] == READ_SCOPE
    query, _ = begin(manager, session, write_access=True)
    assert set(query["scope"].split()) == {"openid", "email", WRITE_SCOPE}
    pending = session.scalars(select(GoogleOAuthPending).where(
        GoogleOAuthPending.state_hash != pending.state_hash)).one()
    assert manager.cipher.decrypt(pending.ciphertext)["required_scope"] == WRITE_SCOPE


def test_write_request_rejects_readonly_grant_even_if_callback_claims_write(session):
    manager = make_manager(granting("openid email https://www.googleapis.com/auth/spreadsheets.readonly"))
    query, binding = begin(manager, session, write_access=True)
    with pytest.raises(GoogleOAuthError, match="missing_scope"):
        exchange(manager, session, query, binding, scope=f"openid email {WRITE_SCOPE}")
    assert session.get(GoogleOAuthConnection, 1) is None


def test_read_login_accepts_write_grant_and_exposes_capability(session):
    manager = make_manager(granting(f"openid https://www.googleapis.com/auth/userinfo.email {WRITE_SCOPE}"))
    query, binding = begin(manager, session)
    exchange(manager, session, query, binding)
    assert manager.status(session)["can_write"] is True
    assert manager.get_credentials(session, require_write=True).has_scopes([WRITE_SCOPE])
    asyncio.run(manager.disconnect(session))
    assert manager.status(session)["can_write"] is False


def test_explicit_write_login_accepts_requested_scope_when_response_omits_scope(session):
    manager = make_manager(lambda request: httpx.Response(200, json={
        "access_token": "access", "refresh_token": "refresh", "id_token": "identity", "expires_in": 3600,
    }))
    query, binding = begin(manager, session, write_access=True)
    exchange(manager, session, query, binding)
    assert manager.status(session)["can_write"] is True


def test_writer_never_falls_back_to_adc_or_readonly_oauth(session):
    manager = make_manager()
    with pytest.raises(GoogleOAuthError, match="write_access_required"):
        manager.get_credentials(session, require_write=True)
    query, binding = begin(manager, session)
    exchange(manager, session, query, binding)
    # A legacy broad readonly token cannot authorize the new quotes-only writer.
    session.get(GoogleOAuthConnection, 1).scopes = ["openid", "email", "https://www.googleapis.com/auth/spreadsheets.readonly"]
    session.commit()
    assert manager.status(session)["can_write"] is False
    with pytest.raises(GoogleOAuthError, match="write_access_required"):
        manager.get_credentials(session, require_write=True)
    assert manager.get_credentials(session) is not None


def test_login_route_accepts_explicit_write_access(client, monkeypatch):
    from app.router import google_oauth_router

    manager = make_manager()
    monkeypatch.setattr(google_oauth_router, "google_oauth_manager", manager)
    response = client.post("/api/finance/google/login?write_access=true")
    assert response.status_code == 200
    query = parse_qs(urlparse(response.json()["authorize_url"]).query)
    assert set(query["scope"][0].split()) == {"openid", "email", WRITE_SCOPE}


def test_holdings_return_target_is_bound_to_pending_state(client, monkeypatch):
    from app.router import google_oauth_router

    manager = make_manager(granting(f"openid email {WRITE_SCOPE}"))
    monkeypatch.setattr(google_oauth_router, "google_oauth_manager", manager)
    response = client.post("/api/finance/google/login?write_access=true&return_to=holdings")
    query = parse_qs(urlparse(response.json()["authorize_url"]).query)
    response = client.get("/api/finance/google/callback", params={
        "state": query["state"][0], "code": "code", "return_to": "https://attacker.invalid",
    }, follow_redirects=False)
    assert response.headers["location"].endswith("/finance/investments?google_oauth=connected")


def test_arbitrary_return_target_is_rejected(client, monkeypatch):
    from app.router import google_oauth_router

    manager = make_manager()
    monkeypatch.setattr(google_oauth_router, "google_oauth_manager", manager)
    assert client.post("/api/finance/google/login?return_to=https://attacker.invalid").status_code == 422
    with pytest.raises(GoogleOAuthError, match="invalid_return_target"):
        manager.start_login(None, return_to="https://attacker.invalid")
