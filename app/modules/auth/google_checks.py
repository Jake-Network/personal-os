"""Google OAuth checks that need no network: redirect setup, identity claims and granted scopes."""

import secrets
from ipaddress import ip_address
from urllib.parse import urlsplit

from app.config import Settings
from app.modules.auth.errors import GoogleOAuthError

READ_SCOPE = "https://www.googleapis.com/auth/drive.file"
WRITE_SCOPE = READ_SCOPE


def setup_diagnostics(settings: Settings) -> dict:
    """Public setup diagnostics, never client secrets or issued tokens."""
    frontend = urlsplit(settings.frontend_url)
    redirect = urlsplit(settings.google_oauth_redirect_uri)
    hostname = redirect.hostname
    try:
        loopback = bool(hostname and ip_address(hostname).is_loopback)
        raw_ip = True
    except ValueError:
        loopback, raw_ip = hostname == "localhost", False
    supported = bool(hostname and (redirect.scheme == "https" or (redirect.scheme == "http" and loopback))
                     and (not raw_ip or loopback) and not redirect.username and not redirect.password
                     and not redirect.query and not redirect.fragment
                     and redirect.path == "/api/finance/google/callback")
    return {"missing_fields": [name for name, value in (
                ("GOOGLE_OAUTH_CLIENT_ID", settings.google_oauth_client_id),
                ("GOOGLE_OAUTH_CLIENT_SECRET", settings.google_oauth_client_secret)) if not value],
            "frontend_url": settings.frontend_url,
            "login_url": f"{settings.frontend_url.rstrip('/')}/finance",
            "redirect_uri": settings.google_oauth_redirect_uri,
            "redirect_uri_supported": supported,
            "callback_host_matches_frontend": bool(hostname and hostname == frontend.hostname)}


def check_identity(claims: dict, client_id: str, nonce: str) -> None:
    """Reject ID token claims not issued by Google for this client, this login and a verified email."""
    if (claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
            or claims.get("aud") != client_id
            or claims.get("email_verified") is not True or not claims.get("sub")
            or not secrets.compare_digest(str(claims.get("nonce", "")), nonce)):
        raise GoogleOAuthError("invalid_identity")


def granted_scopes(tokens: dict, required_scope: str) -> list[str]:
    """Scopes the token response granted; raises unless identity and the required Sheets access are there."""
    # OAuth permits omitting scope when it matches the requested grant.
    scopes = tokens.get("scope", f"openid email {required_scope}").split()
    normalized = {"email" if scope == "https://www.googleapis.com/auth/userinfo.email" else scope for scope in scopes}
    allowed_sheets = {WRITE_SCOPE} if required_scope == WRITE_SCOPE else {READ_SCOPE, WRITE_SCOPE}
    if not {"openid", "email"}.issubset(normalized) or not allowed_sheets.intersection(normalized):
        raise GoogleOAuthError("missing_scope")
    return scopes
