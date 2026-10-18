"""Private Sheets OAuth: browser-bound PKCE, encrypted tokens, and server-side refresh."""
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from typing import Literal

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.modules.auth.crypto import TokenCipher, load_or_create_key
from app.modules.auth.errors import GoogleOAuthError
from app.modules.auth.google_checks import READ_SCOPE, WRITE_SCOPE, check_identity, granted_scopes, setup_diagnostics
from app.modules.auth.pkce import pkce_challenge, sha256_hex
from app.modules.crud import audit_log_handler
from app.modules.database.model.google_oauth import GoogleOAuthConnection, GoogleOAuthPending

SCOPES = ("openid", "email", READ_SCOPE)
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PENDING_TTL = 600


def verify_google_id_token(token: str, audience: str, nonce: str) -> dict:
    claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience)
    if (not claims.get("sub") or claims.get("email_verified") is not True
            or not secrets.compare_digest(str(claims.get("nonce", "")), nonce)):
        raise GoogleOAuthError("invalid_identity")
    return claims


class GoogleOAuthManager:
    def __init__(self, settings: Settings, cipher: TokenCipher | None = None,
                 http_factory: Callable = lambda: httpx.AsyncClient(timeout=20),
                 id_token_verifier: Callable | None = None,
                 request_factory: Callable = GoogleRequest):
        self.settings = settings
        self._cipher = cipher
        self.http_factory = http_factory
        self.verify_id_token = id_token_verifier or verify_google_id_token
        self.request_factory = request_factory

    @property
    def cipher(self) -> TokenCipher:
        if self._cipher is None:
            self._cipher = TokenCipher(load_or_create_key(self.settings.secret_key, self.settings.data_dir))
        return self._cipher

    @property
    def configured(self) -> bool:
        return bool(self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret)

    @staticmethod
    def current(session: Session) -> GoogleOAuthConnection | None:
        return session.get(GoogleOAuthConnection, 1)

    def source_identity(self, session: Session) -> str:
        conn = self.current(session)
        return f"oauth:{conn.subject or 'disconnected'}:{self.settings.google_oauth_client_id}" if conn else "adc"

    def setup(self) -> dict:
        return setup_diagnostics(self.settings)

    def status(self, session: Session) -> dict:
        conn = session.get(GoogleOAuthConnection, 1)
        return {"configured": self.configured, "connected": bool(conn and conn.status == "connected"),
                "status": conn.status if conn else "not_connected", "email": conn.email if conn else None,
                "scopes": conn.scopes if conn else [],
                "can_write": bool(conn and conn.status == "connected" and WRITE_SCOPE in conn.scopes),
                "access_expires_at": conn.access_expires_at.isoformat() if conn and conn.access_expires_at else None,
                "last_error_code": conn.last_error_code if conn else None,
                "credential_source": "oauth" if conn and conn.status == "connected" else (
                    "none" if conn else "application_default"), "setup": self.setup()}

    def start_login(self, session: Session, write_access: bool = False,
                    return_to: Literal["finance", "holdings"] = "finance") -> tuple[str, str]:
        if return_to not in {"finance", "holdings"}:
            raise GoogleOAuthError("invalid_return_target")
        if not self.configured:
            raise GoogleOAuthError("not_configured")
        setup = self.setup()
        if not setup["redirect_uri_supported"]:
            raise GoogleOAuthError("unsupported_redirect_uri")
        if not setup["callback_host_matches_frontend"]:
            raise GoogleOAuthError("callback_host_mismatch")
        required_scope = WRITE_SCOPE if write_access else READ_SCOPE
        requested_scopes = ("openid", "email", required_scope)
        state, binding, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(4))
        challenge = pkce_challenge(verifier)
        session.execute(delete(GoogleOAuthPending).where(GoogleOAuthPending.expires_at < datetime.now(UTC)))
        session.add(GoogleOAuthPending(state_hash=sha256_hex(state), binding_hash=sha256_hex(binding),
                    ciphertext=self.cipher.encrypt({"verifier": verifier, "nonce": nonce,
                                                    "required_scope": required_scope, "return_to": return_to}),
                    expires_at=datetime.now(UTC) + timedelta(seconds=PENDING_TTL)))
        session.commit()
        params = {"client_id": self.settings.google_oauth_client_id, "redirect_uri": self.settings.google_oauth_redirect_uri,
                  "response_type": "code", "scope": " ".join(requested_scopes), "state": state, "nonce": nonce,
                  "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline",
                  "prompt": "consent", "include_granted_scopes": "false"}
        return f"{AUTHORIZE_URL}?{urlencode(params)}", binding

    async def handle_callback(self, session: Session, params: dict, browser_binding: str | None) -> GoogleOAuthConnection:
        if not browser_binding or not params.get("state"):
            raise GoogleOAuthError("invalid_state")
        # DELETE RETURNING atomically consumes the state across workers and restarts.
        pending = session.execute(delete(GoogleOAuthPending).where(
            GoogleOAuthPending.state_hash == sha256_hex(params["state"]),
            GoogleOAuthPending.binding_hash == sha256_hex(browser_binding),
            GoogleOAuthPending.expires_at > datetime.now(UTC),
        ).returning(GoogleOAuthPending.ciphertext)).scalar_one_or_none()
        # Keep a different, non-authorizable marker while the network exchange is in
        # flight. Disconnect removes it, cancelling an already consumed callback.
        marker = secrets.token_hex(32)  # No browser-known preimage can authorize this marker.
        if pending is not None and not params.get("error") and params.get("code"):
            session.add(GoogleOAuthPending(state_hash=marker, binding_hash=sha256_hex(browser_binding),
                        ciphertext=pending, expires_at=datetime.now(UTC) + timedelta(seconds=PENDING_TTL)))
        session.commit()
        if pending is None:
            raise GoogleOAuthError("invalid_state")
        if params.get("error") or not params.get("code"):
            raise GoogleOAuthError("consent_declined")
        secret = self.cipher.decrypt(pending)
        try:
            async with self.http_factory() as http:
                response = await http.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": params["code"],
                    "client_id": self.settings.google_oauth_client_id, "client_secret": self.settings.google_oauth_client_secret,
                    "redirect_uri": self.settings.google_oauth_redirect_uri, "code_verifier": secret["verifier"]})
            response.raise_for_status()
            tokens = response.json()
            claims = self.verify_id_token(tokens["id_token"], self.settings.google_oauth_client_id, secret["nonce"])
            check_identity(claims, self.settings.google_oauth_client_id, secret["nonce"])
            scopes = granted_scopes(tokens, secret.get("required_scope", READ_SCOPE))
            if not tokens.get("access_token") or not tokens.get("refresh_token"):
                raise GoogleOAuthError("missing_refresh_token")
            expires = datetime.now(UTC) + timedelta(seconds=int(tokens["expires_in"]))
        except GoogleOAuthError:
            session.execute(delete(GoogleOAuthPending).where(GoogleOAuthPending.state_hash == marker))
            session.commit()
            raise
        except Exception as exc:
            session.execute(delete(GoogleOAuthPending).where(GoogleOAuthPending.state_hash == marker))
            session.commit()
            raise GoogleOAuthError("authorization_failed") from exc
        authorized = session.execute(delete(GoogleOAuthPending).where(
            GoogleOAuthPending.state_hash == marker,
            GoogleOAuthPending.expires_at > datetime.now(UTC),
        ).returning(GoogleOAuthPending.state_hash)).scalar_one_or_none()
        if authorized is None:
            session.rollback()
            raise GoogleOAuthError("login_cancelled")
        # The marker delete and credential write are one transaction. Disconnect's
        # marker deletion serializes against this transaction before clearing tokens.
        conn = session.get(GoogleOAuthConnection, 1)
        if conn is None:
            conn = GoogleOAuthConnection(id=1)
            session.add(conn)
        conn.subject, conn.email = claims["sub"], claims.get("email")
        conn.status, conn.scopes = "connected", scopes
        conn.ciphertext = self.cipher.encrypt({"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"]})
        conn.access_expires_at, conn.last_error_code = expires, None
        audit_log_handler.record(session, "user", "google_oauth.connect", "google_oauth_connections:1", {"scopes": scopes})
        session.commit()
        conn._google_return_to = secret.get("return_to", "finance")
        return conn

    def get_credentials(self, session: Session, require_write: bool = False) -> Credentials | None:
        conn = session.scalar(select(GoogleOAuthConnection).where(GoogleOAuthConnection.id == 1).with_for_update()
                              .execution_options(populate_existing=True))
        if conn is None:
            if require_write:
                raise GoogleOAuthError("write_access_required")
            return None  # Existing explicitly configured service-account/ADC deployments remain supported.
        if conn.status != "connected" or not conn.ciphertext:
            raise GoogleOAuthError("needs_reauth" if conn.status == "needs_reauth" else "disconnected")
        if require_write and WRITE_SCOPE not in conn.scopes:
            raise GoogleOAuthError("write_access_required")
        if not self.configured:
            raise GoogleOAuthError("not_configured")
        try:
            tokens = self.cipher.decrypt(conn.ciphertext)
            expiry = conn.access_expires_at.replace(tzinfo=None) if conn.access_expires_at else None
            credentials = Credentials(token=tokens["access_token"], refresh_token=tokens["refresh_token"],
                token_uri=TOKEN_URL, client_id=self.settings.google_oauth_client_id,
                client_secret=self.settings.google_oauth_client_secret, scopes=conn.scopes, expiry=expiry)
            # Bind this request to the principal whose encrypted token was read. A refresh
            # commits before Sheets I/O; a later account switch must not relabel its results.
            credentials._personal_os_source_identity = (
                f"oauth:{conn.subject or 'disconnected'}:{self.settings.google_oauth_client_id}")
            if not credentials.valid:
                credentials.refresh(self.request_factory())
                conn.ciphertext = self.cipher.encrypt({"access_token": credentials.token,
                                                       "refresh_token": credentials.refresh_token})
                conn.access_expires_at = credentials.expiry.replace(tzinfo=UTC) if credentials.expiry else None
                conn.last_error_code = None
                session.commit()
            return credentials
        except RefreshError as exc:
            # Fixed code only; Google exception strings can contain token response contents.
            invalid = any(isinstance(arg, dict) and arg.get("error") == "invalid_grant" for arg in exc.args)
            if invalid:
                conn.status, conn.ciphertext = "needs_reauth", None
                conn.last_error_code = "refresh_rejected"
                audit_log_handler.record(session, "system", "google_oauth.needs_reauth", "google_oauth_connections:1")
            else:
                conn.last_error_code = "refresh_failed"
            session.commit()
            raise GoogleOAuthError(conn.last_error_code) from exc
        except Exception as exc:
            conn.last_error_code = "credentials_unavailable"
            session.commit()
            raise GoogleOAuthError("credentials_unavailable") from exc

    async def disconnect(self, session: Session) -> None:
        session.execute(delete(GoogleOAuthPending))
        conn = session.scalar(select(GoogleOAuthConnection).where(GoogleOAuthConnection.id == 1)
                              .with_for_update().execution_options(populate_existing=True))
        # Persist a tombstone so disconnect can never silently fall back to ADC.
        if conn is None:
            conn = GoogleOAuthConnection(id=1)
            session.add(conn)
        ciphertext = conn.ciphertext
        conn.status, conn.ciphertext = "disconnected", None
        conn.email, conn.subject, conn.scopes = None, None, []
        conn.access_expires_at, conn.last_error_code = None, None
        audit_log_handler.record(session, "user", "google_oauth.disconnect", "google_oauth_connections:1")
        session.commit()
        if ciphertext:
            try:
                tokens = self.cipher.decrypt(ciphertext)
                async with self.http_factory() as http:
                    await http.post("https://oauth2.googleapis.com/revoke", data={"token": tokens["refresh_token"]})
            except Exception:
                pass  # Local credentials are removed even when provider revocation is unavailable.


google_oauth_manager = GoogleOAuthManager(settings)
