"""Inference providers behind one interface (PRD §2.3).

ChatGPTPlanProvider is the default. The API-key and Codex app-server providers exist only
as explicit user choices; nothing in this module switches providers on failure.
"""

import json
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Protocol

import httpx
from sqlalchemy.orm import Session

from app.modules.llm.errors import (
    AdvisorError,
    AuthRequired,
    IncompleteResponse,
    ProviderUnavailable,
    QuotaExceeded,
    ScopeNotAuthorized,
    UsageUnavailable,
)
from app.modules.llm.types import LLMRequest, StreamEvent

if TYPE_CHECKING:
    from app.modules.auth.oauth_manager import OAuthManager


class LLMProvider(Protocol):
    name: str

    async def list_models(self, session: Session) -> list[str]: ...

    def stream(self, session: Session, request: LLMRequest) -> AsyncIterator[StreamEvent]: ...


def map_provider_error(status: int | None, code: str | None, message: str | None = None) -> AdvisorError:
    if code == "subscription_sharing_usage_limit_exceeded":
        return QuotaExceeded(message, provider_code=code)
    if code == "subscription_sharing_usage_unavailable":
        return UsageUnavailable(message, provider_code=code)
    if code in ("chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context"):
        return ScopeNotAuthorized(message, provider_code=code)
    if code in ("subscription_sharing_invalid_user", "token_expired") or status == 401:
        return AuthRequired(message, provider_code=code)
    if status == 403:
        return ScopeNotAuthorized(message, provider_code=code)
    if status == 429:
        # Any 429 on the plan path is treated as a hard stop, never a cue to switch billing.
        return QuotaExceeded(message, provider_code=code)
    return ProviderUnavailable(message, provider_code=code)


def _error_fields(body: dict) -> tuple[str | None, str | None]:
    err = body.get("error") or (body.get("response") or {}).get("error") or {}
    if isinstance(err, dict):
        return err.get("code"), err.get("message")
    return str(err), None


class ResponsesApiClient:
    """Streams the public Responses API. `store=false`, `stream=true` as the plan flow requires."""

    def __init__(self, base_url: str, http_factory: Callable[[], httpx.AsyncClient]):
        self.base_url = base_url.rstrip("/")
        self.http_factory = http_factory

    async def list_models(self, token: str) -> list[str]:
        async with self.http_factory() as http:
            resp = await http.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            code, msg = _error_fields(_json(resp))
            raise map_provider_error(resp.status_code, code, msg)
        models = _json(resp).get("data") or _json(resp).get("models") or []
        out = []
        for m in models:
            if m.get("visibility", "list") != "list":
                continue
            out.append(m.get("slug") or m.get("id"))
        return [m for m in out if m]

    async def stream(self, token: str, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        body = {"model": request.model, "instructions": request.instructions, "input": request.input,
                "store": False, "stream": True}
        if request.json_mode:
            # JSON syntax is constrained by the provider; domain schemas and
            # approval payloads still require the runtime's validation.
            body["text"] = {"format": {"type": "json_object"}}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "text/event-stream"}
        try:
            async with self.http_factory() as http:
                async with http.stream("POST", f"{self.base_url}/responses", json=body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        code, msg = _error_fields(_json(resp))
                        raise map_provider_error(resp.status_code, code, msg)
                    completed = False
                    async for event in _sse_events(resp):
                        kind = event.get("type")
                        if kind == "response.output_text.delta":
                            yield StreamEvent("delta", text=event.get("delta", ""))
                        elif kind == "response.completed":
                            completed = True
                            yield StreamEvent("completed", usage=(event.get("response") or {}).get("usage") or {})
                        elif kind == "response.incomplete":
                            reason = ((event.get("response") or {}).get("incomplete_details") or {}).get("reason")
                            raise IncompleteResponse(reason, provider_code=reason)
                        elif kind in ("response.failed", "error"):
                            code, msg = _error_fields(event)
                            raise map_provider_error(None, code, msg)
                    if not completed:
                        raise IncompleteResponse("stream ended before response.completed",
                                                 provider_code="stream_interrupted")
        except httpx.TransportError as exc:
            raise ProviderUnavailable(type(exc).__name__, provider_code="network") from exc


async def _sse_events(resp: httpx.Response) -> AsyncIterator[dict]:
    data_lines: list[str] = []
    async for line in resp.aiter_lines():
        if line == "":
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines = []
                if payload.strip() == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except ValueError:
                    continue
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            yield json.loads("\n".join(data_lines))
        except ValueError:
            pass


def _json(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


class ChatGPTPlanProvider:
    name = "chatgpt_plan"

    def __init__(self, oauth: "OAuthManager", client: ResponsesApiClient):
        self.oauth = oauth
        self.client = client

    async def _token(self, session: Session, force_refresh: bool = False) -> str:
        conn, token = await self.oauth.access_token(session, force_refresh=force_refresh)
        if not conn.plan_usage_enabled:
            raise ScopeNotAuthorized(provider_code=conn.last_error_code)
        return token

    async def list_models(self, session: Session) -> list[str]:
        try:
            return await self.client.list_models(await self._token(session))
        except AuthRequired:
            return await self.client.list_models(await self._token(session, force_refresh=True))

    async def stream(self, session: Session, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        from app.modules.llm.transfer_policy import account_binding
        expected_account = account_binding(session, self.name)
        token = await self._token(session)
        self._check_transfer(session, request, expected_account)
        emitted = False
        try:
            async for event in self.client.stream(token, request):
                emitted = True
                yield event
        except AuthRequired:
            if emitted:
                raise
            # One refresh-and-retry for an expired access token, before any output.
            token = await self._token(session, force_refresh=True)
            self._check_transfer(session, request, expected_account)
            async for event in self.client.stream(token, request):
                yield event
        except ScopeNotAuthorized as exc:
            self.oauth.mark_plan_usage_disabled(session, exc.provider_code)
            raise

    def _check_transfer(self, session: Session, request: LLMRequest, expected_account: str | None) -> None:
        # Refresh may await a network request while the user revokes sharing or
        # switches accounts. Recheck immediately before the personal payload leaves.
        from app.modules.llm.transfer_policy import account_binding, require_confirmation, TransferNotConfirmed
        from app.modules.context.source_policy import require_live_request_sources
        session.expire_all()
        from app.modules.llm.run_policy import require
        require(session, request.authorization)
        if not expected_account or account_binding(session, self.name) != expected_account:
            raise TransferNotConfirmed()
        require_confirmation(session, self.name)
        require_live_request_sources(session, request)


class ApiKeyProvider:
    """Optional, user-selected only. Bills the user's OpenAI API account."""

    name = "openai_api_key"

    def __init__(self, api_key_getter: Callable[[Session], str | None], client: ResponsesApiClient):
        self.api_key_getter = api_key_getter
        self.client = client

    def _key(self, session: Session) -> str:
        key = self.api_key_getter(session)
        if not key:
            raise ProviderUnavailable("API key not configured", provider_code="api_key_missing")
        return key

    async def list_models(self, session: Session) -> list[str]:
        return await self.client.list_models(self._key(session))

    async def stream(self, session: Session, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        from app.modules.llm.transfer_policy import require_confirmation
        from app.modules.context.source_policy import require_live_request_sources
        session.expire_all()
        from app.modules.llm.run_policy import require
        require(session, request.authorization)
        require_confirmation(session, self.name)
        require_live_request_sources(session, request)
        async for event in self.client.stream(self._key(session), request):
            yield event


class CodexAppServerProvider:
    """Placeholder for the Codex app-server runtime (JSON-RPC over stdio). Not wired in v0.2."""

    name = "codex_app_server"

    async def list_models(self, session: Session) -> list[str]:
        raise ProviderUnavailable("Codex app-server provider not implemented", provider_code="not_implemented")

    async def stream(self, session: Session, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        raise ProviderUnavailable("Codex app-server provider not implemented", provider_code="not_implemented")
        yield  # pragma: no cover  (makes this an async generator)


def local_url_allowed(url: str) -> bool:
    """Loopback, private-network or single-label (container service) hosts only: a "local" model must stay local."""
    import ipaddress
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host in ("localhost", "host.docker.internal") or "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


class LocalOpenAICompatibleProvider:
    """A model served on this machine (DenseCore, or another OpenAI-compatible `/v1/chat/completions`).

    Selected explicitly only and never a fallback. Requests still pass the same sharing,
    snapshot and transfer checks as remote providers. Before each call the server's loaded
    model must match the configured ID, because the `model` request field alone does not prove
    which weights answer.
    """

    name = "local_densecore"
    MODEL_CHECK_TTL_SECONDS = 30

    def __init__(self, base_url: Callable[[], str], model_id: Callable[[], str],
                 http_factory: Callable[[], httpx.AsyncClient]):
        self.base_url = base_url
        self.model_id = model_id
        self.http_factory = http_factory
        self._checked: dict[tuple[str, str], float] = {}

    def configured(self) -> bool:
        return bool(self.model_id()) and local_url_allowed(self.base_url())

    def _base(self) -> str:
        base = self.base_url().rstrip("/")
        if not self.model_id():
            raise ProviderUnavailable("LLM_LOCAL_MODEL_ID is not set", provider_code="local_model_unconfigured")
        if not local_url_allowed(base):
            raise ProviderUnavailable("LLM_LOCAL_URL must be a loopback or private address", provider_code="local_url_not_local")
        return base

    async def _models(self, http: httpx.AsyncClient, base: str) -> list[str]:
        resp = await http.get(f"{base}/v1/models")
        if resp.status_code >= 400:
            raise ProviderUnavailable(f"/v1/models returned {resp.status_code}", provider_code="local_models_failed")
        return [m.get("id") for m in _json(resp).get("data") or [] if isinstance(m, dict) and m.get("id")]

    async def list_models(self, session: Session) -> list[str]:
        base = self._base()
        try:
            async with self.http_factory() as http:
                return await self._models(http, base)
        except httpx.TransportError as exc:
            raise ProviderUnavailable(type(exc).__name__, provider_code="local_unreachable") from exc

    async def _check_loaded(self, http: httpx.AsyncClient, base: str) -> None:
        import time
        key = (base, self.model_id())
        if time.monotonic() - self._checked.get(key, float("-inf")) < self.MODEL_CHECK_TTL_SECONDS:
            return
        if self.model_id() not in await self._models(http, base):
            raise ProviderUnavailable("the local server has a different model loaded", provider_code="local_model_mismatch")
        self._checked[key] = time.monotonic()

    async def stream(self, session: Session, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        from app.modules.context.source_policy import require_live_request_sources
        from app.modules.llm.run_policy import require
        from app.modules.llm.transfer_policy import require_confirmation
        session.expire_all()
        require(session, request.authorization)
        require_confirmation(session, self.name)
        require_live_request_sources(session, request)
        base = self._base()
        messages = ([{"role": "system", "content": request.instructions}] if request.instructions else []) + [
            {"role": item.get("role", "user"), "content": item["content"] if isinstance(item.get("content"), str)
             else json.dumps(item.get("content"), ensure_ascii=False)} for item in request.input]
        body = {"model": self.model_id(), "messages": messages, "stream": True,
                "stream_options": {"include_usage": True}}
        if request.json_mode:
            # The server's grammar constrains JSON syntax; the runtime still validates every schema.
            body["response_format"] = {"type": "json_object"}
        try:
            async with self.http_factory() as http:
                await self._check_loaded(http, base)
                async with http.stream("POST", f"{base}/v1/chat/completions", json=body,
                                       headers={"Accept": "text/event-stream"}) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        code, msg = _error_fields(_json(resp))
                        raise ProviderUnavailable(msg or f"local server returned {resp.status_code}",
                                                  provider_code=code or f"local_http_{resp.status_code}")
                    finished, usage = False, {}
                    async for event in _sse_events(resp):
                        if event.get("error"):
                            code, msg = _error_fields(event)
                            raise ProviderUnavailable(msg, provider_code=code or "local_stream_error")
                        if event.get("usage"):
                            usage = {"input_tokens": event["usage"].get("prompt_tokens"),
                                     "output_tokens": event["usage"].get("completion_tokens")}
                        for choice in event.get("choices") or []:
                            # reasoning_content (thinking) is never part of the answer.
                            text = (choice.get("delta") or {}).get("content")
                            if text:
                                yield StreamEvent("delta", text=text)
                            reason = choice.get("finish_reason")
                            if reason == "length":
                                raise IncompleteResponse("max tokens reached", provider_code="max_output_tokens")
                            if reason:
                                finished = True
                    if not finished:
                        raise IncompleteResponse("stream ended before a finish reason", provider_code="stream_interrupted")
                    yield StreamEvent("completed", usage=usage)
        except httpx.TransportError as exc:
            raise ProviderUnavailable(type(exc).__name__, provider_code="local_unreachable") from exc
