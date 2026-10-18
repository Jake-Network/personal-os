"""PRD OAuthAuthService: Sign in with ChatGPT for open-source apps (PRD §2.2).

Implements the documented loopback flow: dynamic client registration on first sign-in,
PKCE S256, state + nonce, ID token verification against OpenAI's JWKS, an explicit
`chatgpt.tokens.use.direct` grant check, serialized refresh with rotation, and revocation.
Tokens live only in `oauth_credentials`, encrypted; they never reach the browser or logs.
"""

import asyncio
import base64
import hashlib
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.modules.auth.crypto import TokenCipher, load_or_create_key
from app.modules.crud.app_setting_handler import app_setting_handler
from app.modules.crud.audit_log_handler import audit_log_handler
from app.modules.crud.oauth_handler import oauth_connection_handler, oauth_credential_handler
from app.modules.database.model import OAuthConnection
from app.modules.llm.errors import AuthRequired, ConsentDeclined, NotConnected
from app.modules.auth.types import PendingLogin

IDENTITY_SCOPES = ("openid", "profile", "email")
PLAN_SCOPES = ("offline_access", "resource.invoke", "chatgpt.tokens.use.direct")
PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"
DYNAMIC_CLIENT = "dynamic_agent_client"
HOST_ID_KEY = "oauth.ext_agent_host_id"
PENDING_TTL = 600
REFRESH_SKEW = timedelta(seconds=90)
REAUTH_CODES = {"invalid_grant", "refresh_token_invalidated", "refresh_token_expired", "invalid_refresh_token",
                "token_expired"}

IdTokenVerifier = Callable[[str, str, str], dict]  # (id_token, audience, nonce) -> claims


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class JwksIdTokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks: jwt.PyJWKClient | None = None

    def __call__(self, id_token: str, audience: str, nonce: str) -> dict:
        if self._jwks is None:
            discovery = httpx.get(self.settings.oauth_discovery_url, timeout=10).raise_for_status().json()
            self._jwks = jwt.PyJWKClient(discovery["jwks_uri"])
        key = self._jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token, key.key, algorithms=["RS256", "ES256"], audience=audience,
            issuer=self.settings.oauth_issuer, options={"require": ["exp", "iss", "aud", "sub"]},
        )
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise jwt.InvalidTokenError("nonce mismatch")
        return claims


class OAuthManager:
    def __init__(
        self,
        settings: Settings,
        cipher: TokenCipher | None = None,
        http_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=20),
        id_token_verifier: IdTokenVerifier | None = None,
    ):
        self.settings = settings
        self._cipher = cipher
        self.http_factory = http_factory
        self.verify_id_token = id_token_verifier or JwksIdTokenVerifier(settings)
        self._pending: dict[str, PendingLogin] = {}
        self._refresh_lock = asyncio.Lock()

    @property
    def cipher(self) -> TokenCipher:
        # Lazy: creating the key file must not happen at import time.
        if self._cipher is None:
            self._cipher = TokenCipher(load_or_create_key(self.settings.secret_key, self.settings.data_dir))
        return self._cipher

    # --- connection state ----------------------------------------------------------------

    @staticmethod
    def current(session: Session) -> OAuthConnection | None:
        return oauth_connection_handler.get_active(session)

    def host_id(self, session: Session) -> str:
        value = app_setting_handler.get_value(session, HOST_ID_KEY)
        if value is None:
            value = {"id": f"urn:uuid:{uuid.uuid4()}"}
            app_setting_handler.set_value(session, HOST_ID_KEY, value)
            session.commit()
        return value["id"]

    def status(self, session: Session) -> dict:
        conn = self.current(session)
        if conn is None:
            return {"connected": False, "usage_url": self.settings.chatgpt_usage_url}
        return {
            "connected": conn.status == "connected",
            "status": conn.status,
            "email": conn.email,
            "display_name": conn.display_name,
            "plan_usage_enabled": conn.plan_usage_enabled,
            "scopes": conn.scopes,
            "access_expires_at": conn.access_expires_at.isoformat() if conn.access_expires_at else None,
            "last_error_code": conn.last_error_code,
            "usage_url": self.settings.chatgpt_usage_url,
        }

    # --- sign-in -------------------------------------------------------------------------

    def start_login(self, session: Session, force_consent: bool = False) -> str:
        self._gc_pending()
        previous = oauth_connection_handler.get_latest(session)
        client_id = previous.client_id if previous else DYNAMIC_CLIENT
        verifier, challenge = pkce_pair()
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        params = {
            "client_id": client_id,
            "ext_agent_host_id": self.host_id(session),
            "response_type": "code",
            "redirect_uri": self.settings.redirect_uri,
            "scope": " ".join(IDENTITY_SCOPES + PLAN_SCOPES),
            "resource": self.settings.oauth_resource,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if client_id == DYNAMIC_CLIENT:
            params["agent_name_hint"] = self.settings.oauth_app_name
        elif previous and previous.email:
            params["login_hint"] = previous.email
        if force_consent:
            params["prompt"] = "consent"
        self._pending[state] = PendingLogin(verifier, nonce, client_id, time.monotonic())
        return f"{self.settings.oauth_authorize_url}?{urlencode(params)}"

    async def handle_callback(self, session: Session, params: dict[str, str]) -> OAuthConnection:
        state = params.get("state", "")
        pending = self._pending.pop(state, None)
        if pending is None or time.monotonic() - pending.created > PENDING_TTL:
            raise ConsentDeclined("unknown or expired OAuth state")
        if params.get("error"):
            # access_denied: validate state (done above), stop, do not exchange.
            raise ConsentDeclined(params["error"], provider_code=params["error"])
        code = params.get("code")
        if not code:
            raise ConsentDeclined("missing authorization code")
        client_id = params.get("client_id") or pending.client_id
        if client_id == DYNAMIC_CLIENT:
            raise ConsentDeclined("registration did not return an issued client_id")

        async with self.http_factory() as http:
            resp = await http.post(self.settings.oauth_token_url, data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": pending.verifier,
                "redirect_uri": self.settings.redirect_uri,
                "resource": self.settings.oauth_resource,
            })
        if resp.status_code >= 400:
            raise ConsentDeclined("token exchange failed", provider_code=_error_code(resp))
        tokens = resp.json()
        try:
            claims = self.verify_id_token(tokens["id_token"], client_id, pending.nonce)
        except (KeyError, jwt.PyJWTError) as exc:
            raise ConsentDeclined(f"ID token rejected: {type(exc).__name__}") from exc

        granted = (tokens.get("scope") or params.get("scope") or "").split()
        # A valid ID token alone does not authorize plan usage.
        plan_usage = PLAN_USAGE_SCOPE in granted
        fields = {
            "status": "connected",
            "email": claims.get("email"),
            "display_name": claims.get("name"),
            "scopes": granted,
            "plan_usage_enabled": plan_usage,
            "last_error_code": None if plan_usage else "plan_usage_scope_not_granted",
        }
        conn = oauth_connection_handler.get_latest(session)
        if conn is None or conn.subject != claims["sub"] or conn.client_id != client_id:
            conn = oauth_connection_handler.create(session, {
                "provider": "chatgpt", "issuer": claims["iss"], "subject": claims["sub"], "client_id": client_id,
                "ext_agent_host_id": self.host_id(session), **fields,
            })
        else:
            oauth_connection_handler.update(session, conn, fields)
        self._store_tokens(session, conn, tokens)
        audit_log_handler.record(session, "user", "oauth.connect", f"oauth_connections:{conn.id}",
                                 {"plan_usage_enabled": plan_usage, "scopes": granted})
        session.commit()
        return conn

    # --- tokens --------------------------------------------------------------------------

    def _store_tokens(self, session: Session, conn: OAuthConnection, tokens: dict) -> None:
        cred = oauth_credential_handler.get(session, conn.id)
        previous = self.cipher.decrypt(cred.ciphertext) if cred else {}
        record = {
            "access_token": tokens["access_token"],
            # Rotation: always keep the latest refresh token; keep the old one if none returned.
            "refresh_token": tokens.get("refresh_token") or previous.get("refresh_token"),
            "id_token": tokens.get("id_token") or previous.get("id_token"),
            "token_type": tokens.get("token_type", "Bearer"),
        }
        expires_in = int(tokens.get("expires_in") or 3600)
        conn.access_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        oauth_credential_handler.upsert(session, conn.id, self.cipher.encrypt(record))

    def _load_tokens(self, session: Session, conn: OAuthConnection) -> dict:
        cred = oauth_credential_handler.get(session, conn.id)
        if cred is None:
            raise AuthRequired("no stored credentials")
        return self.cipher.decrypt(cred.ciphertext)

    async def access_token(self, session: Session, force_refresh: bool = False) -> tuple[OAuthConnection, str]:
        conn = self.current(session)
        if conn is None:
            raise NotConnected()
        if conn.status != "connected":
            raise AuthRequired(provider_code=conn.last_error_code)
        expires = conn.access_expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if force_refresh or expires is None or expires - datetime.now(UTC) < REFRESH_SKEW:
            await self._refresh(session, conn)
        return conn, self._load_tokens(session, conn)["access_token"]

    async def _refresh(self, session: Session, conn: OAuthConnection) -> None:
        async with self._refresh_lock:  # serialize: refresh tokens rotate
            session.refresh(conn)
            tokens = self._load_tokens(session, conn)
            if not tokens.get("refresh_token"):
                self._mark_reauth(session, conn, "no_refresh_token")
                raise AuthRequired(provider_code="no_refresh_token")
            try:
                async with self.http_factory() as http:
                    resp = await http.post(self.settings.oauth_token_url, data={
                        "grant_type": "refresh_token",
                        "client_id": conn.client_id,
                        "refresh_token": tokens["refresh_token"],
                        "resource": self.settings.oauth_resource,
                    })
            except httpx.TransportError as exc:
                # Temporary failure: keep credentials.
                raise AuthRequired("refresh network failure", provider_code="network") from exc
            if resp.status_code >= 400:
                code = _error_code(resp)
                if code in REAUTH_CODES or resp.status_code in (400, 401):
                    self._mark_reauth(session, conn, code)
                raise AuthRequired(provider_code=code)
            self._store_tokens(session, conn, resp.json())
            session.commit()

    def _mark_reauth(self, session: Session, conn: OAuthConnection, code: str | None) -> None:
        conn.status = "needs_reauth"
        conn.last_error_code = code
        audit_log_handler.record(session, "system", "oauth.needs_reauth", f"oauth_connections:{conn.id}",
                                 {"code": code})
        session.commit()

    def mark_plan_usage_disabled(self, session: Session, code: str | None) -> None:
        conn = self.current(session)
        if conn is not None:
            conn.plan_usage_enabled = False
            conn.last_error_code = code
            session.commit()

    async def disconnect(self, session: Session) -> None:
        conn = self.current(session)
        if conn is None:
            return
        try:
            tokens = self._load_tokens(session, conn)
        except AuthRequired:
            tokens = {}
        if tokens.get("refresh_token"):
            try:
                async with self.http_factory() as http:
                    discovery = (await http.get(self.settings.oauth_discovery_url)).json()
                    endpoint = discovery.get("revocation_endpoint")
                    if endpoint:
                        await http.post(endpoint, data={"token": tokens["refresh_token"],
                                                        "token_type_hint": "refresh_token",
                                                        "client_id": conn.client_id})
            except httpx.HTTPError:
                pass  # local credentials are removed regardless; revocation is best-effort
        cred = oauth_credential_handler.get(session, conn.id)
        if cred is not None:
            oauth_credential_handler.delete(session, cred)
        conn.status = "disconnected"
        conn.plan_usage_enabled = False
        audit_log_handler.record(session, "user", "oauth.disconnect", f"oauth_connections:{conn.id}")
        session.commit()

    def _gc_pending(self) -> None:
        cutoff = time.monotonic() - PENDING_TTL
        for state in [s for s, p in self._pending.items() if p.created < cutoff]:
            del self._pending[state]


def _error_code(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("code") or err.get("type")
    return err or body.get("code")


oauth_manager = OAuthManager(settings)
