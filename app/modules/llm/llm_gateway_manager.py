"""PRD LLMGateway: one entry point for inference, usage accounting and model choice.

The active provider is whatever the user selected (default: ChatGPT plan). Failures are
recorded and re-raised; the gateway never retries on a different, billable provider.
"""

import os
import time
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.auth.oauth_manager import oauth_manager
from app.modules.crud import app_setting_handler, audit_log_handler, llm_usage_event_handler
from app.modules.database.model import LLMUsageEvent
from app.modules.llm.errors import AdvisorError, AuthRequired, QuotaExceeded, ScopeNotAuthorized
from app.modules.llm.providers import (
    ApiKeyProvider,
    ChatGPTPlanProvider,
    CodexAppServerProvider,
    LLMProvider,
    ResponsesApiClient,
)
from app.modules.llm.types import LLMRequest, StreamEvent

PROVIDER_KEY = "llm.provider"
MODEL_KEY = "llm.model"
DEFAULT_PROVIDER = "chatgpt_plan"


class LLMGatewayManager:
    def __init__(self, providers: dict[str, LLMProvider], default_model: str = ""):
        self.providers = providers
        self.default_model = default_model

    def provider_name(self, session: Session) -> str:
        name = (app_setting_handler.get_value(session, PROVIDER_KEY) or {}).get("name")
        return name if name in self.providers else DEFAULT_PROVIDER

    def provider(self, session: Session) -> LLMProvider:
        return self.providers[self.provider_name(session)]

    async def list_models(self, session: Session) -> list[str]:
        return await self.provider(session).list_models(session)

    async def resolve_model(self, session: Session) -> str:
        chosen = (app_setting_handler.get_value(session, MODEL_KEY) or {}).get("name")
        if chosen:
            return chosen
        if self.default_model:
            return self.default_model
        models = await self.list_models(session)
        if not models:
            raise AdvisorError("no models available for this account", provider_code="no_models")
        return models[0]

    async def stream(
        self, session: Session, request: LLMRequest, conversation_id: int | None = None
    ) -> AsyncIterator[StreamEvent]:
        provider = self.provider(session)
        started = time.monotonic()
        record: dict = {
            "provider": provider.name, "model": request.model, "conversation_id": conversation_id,
            "context_chars": sum(len(str(i.get("content", ""))) for i in request.input),
            "outcome": None, "error_code": None,
        }
        try:
            async for chunk in provider.stream(session, request):
                if chunk.type == "completed":
                    record["input_tokens"] = chunk.usage.get("input_tokens")
                    record["output_tokens"] = chunk.usage.get("output_tokens")
                    record["outcome"] = "completed"
                yield chunk
        except AdvisorError as exc:
            record["outcome"] = {
                QuotaExceeded: "quota_exceeded", AuthRequired: "auth_error", ScopeNotAuthorized: "auth_error",
            }.get(type(exc), "failed")
            record["error_code"] = exc.provider_code or exc.code
            raise
        finally:
            record["outcome"] = record["outcome"] or "failed"
            record["latency_ms"] = int((time.monotonic() - started) * 1000)
            llm_usage_event_handler.create(session, record)
            session.commit()

    def select(self, session: Session, provider: str, model: str | None) -> None:
        """Explicit user choice; the only way a non-plan provider becomes active."""
        if provider not in self.providers:
            raise ValueError(f"unknown provider {provider}")
        app_setting_handler.set_value(session, PROVIDER_KEY, {"name": provider})
        app_setting_handler.set_value(session, MODEL_KEY, {"name": model} if model else {})
        audit_log_handler.record(session, "user", "llm.select_provider", detail={"provider": provider, "model": model})
        session.commit()

    @staticmethod
    def recent_usage(session: Session, limit: int = 50) -> list[LLMUsageEvent]:
        return llm_usage_event_handler.get_recent(session, limit)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(20, read=180))


_responses = ResponsesApiClient(settings.openai_api_base, _http)

llm_gateway_manager = LLMGatewayManager(
    providers={
        "chatgpt_plan": ChatGPTPlanProvider(oauth_manager, _responses),
        # Read from the environment only; never persisted, never chosen automatically.
        "openai_api_key": ApiKeyProvider(lambda _session: os.environ.get("OPENAI_API_KEY"), _responses),
        "codex_app_server": CodexAppServerProvider(),
    },
    default_model=settings.default_model,
)
