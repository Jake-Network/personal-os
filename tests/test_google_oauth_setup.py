import json

import pytest

from app.config import Settings
from app.modules.auth.google_oauth_manager import GoogleOAuthManager
from app.modules.database.model import GoogleOAuthPending
from sqlalchemy import select


def test_missing_client_configuration_is_actionable_without_disclosing_credentials(session):
    manager = GoogleOAuthManager(Settings(google_oauth_client_id="", google_oauth_client_secret=""))
    status = manager.status(session)
    assert status["configured"] is False
    assert status["setup"]["missing_fields"] == ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"]
    assert status["setup"]["login_url"] == "http://127.0.0.1:5173/finance"
    assert status["setup"]["redirect_uri"] == "http://127.0.0.1:8000/api/finance/google/callback"
    configured = GoogleOAuthManager(Settings(google_oauth_client_id="private-client-id", google_oauth_client_secret="private-secret"))
    text = json.dumps(configured.status(session))
    assert "private-client-id" not in text and "private-secret" not in text


@pytest.mark.parametrize("redirect_uri", [
    "http://172.18.224.169:8000/api/finance/google/callback",
    "https://172.18.224.169/api/finance/google/callback",
    "http://example.com/api/finance/google/callback",
    "http://127.0.0.1:8000/wrong-callback",
])
def test_invalid_google_redirect_is_explained_and_rejected_before_authorization(session, redirect_uri):
    manager = GoogleOAuthManager(Settings(google_oauth_client_id="id", google_oauth_client_secret="secret",
                                         google_oauth_redirect_uri=redirect_uri))
    assert manager.setup()["redirect_uri_supported"] is False
    with pytest.raises(ValueError, match="unsupported_redirect_uri"):
        manager.start_login(session)
    assert session.scalars(select(GoogleOAuthPending)).all() == []


def test_wsl_frontend_cannot_start_cookie_bound_loopback_callback(session):
    manager = GoogleOAuthManager(Settings(google_oauth_client_id="id", google_oauth_client_secret="secret",
                                         frontend_url="http://172.18.224.169:5173"))
    assert manager.setup()["callback_host_matches_frontend"] is False
    with pytest.raises(ValueError, match="callback_host_mismatch"):
        manager.start_login(session)


def test_wsl_login_rejection_points_to_the_configured_frontend(client):
    # The local trust middleware refuses the foreign origin before the router runs.
    response = client.post("/api/finance/google/login", headers={"Origin": "http://172.18.224.169:5173"})
    assert response.status_code == 403
    assert "http://127.0.0.1:5173" in response.json()["detail"]
