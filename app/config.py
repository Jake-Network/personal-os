"""Runtime settings, read once from the environment."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("PERSONAL_OS_DATA_DIR", "./data")))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))
    # Fernet key (urlsafe base64, 32 bytes). Generated into data_dir when unset.
    secret_key: str = field(default_factory=lambda: _env("PERSONAL_OS_SECRET_KEY", ""))

    # Sign in with ChatGPT (open-source token sharing flow).
    oauth_issuer: str = "https://auth.openai.com"
    oauth_authorize_url: str = "https://auth.openai.com/api/accounts/authorize"
    oauth_token_url: str = "https://auth.openai.com/api/accounts/oauth/token"
    oauth_discovery_url: str = "https://auth.openai.com/.well-known/openid-configuration"
    oauth_resource: str = "https://api.openai.com/v1"
    oauth_app_name: str = "Personal OS"
    # Loopback redirect must be 127.0.0.1 and path /auth/callback; only the port may vary.
    oauth_callback_port: int = field(default_factory=lambda: int(_env("OAUTH_CALLBACK_PORT", "8000")))
    frontend_url: str = field(default_factory=lambda: _env("FRONTEND_URL", "http://127.0.0.1:5173"))
    # Extra hostnames the API answers to besides loopback and IP literals (comma-separated).
    # Not authentication: see LocalTrustMiddleware before exposing the API anywhere.
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: tuple(
        h for h in _env("PERSONAL_OS_ALLOWED_HOSTS", "").split(",") if h.strip()))
    chatgpt_usage_url: str = field(default_factory=lambda: _env("CHATGPT_USAGE_URL", "https://chatgpt.com/#settings"))

    openai_api_base: str = "https://api.openai.com/v1"
    default_model: str = field(default_factory=lambda: _env("ADVISOR_DEFAULT_MODEL", ""))

    # Private Google Sheets connection; separate from ChatGPT OAuth.
    google_oauth_client_id: str = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_ID", ""))
    google_oauth_client_secret: str = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    google_oauth_redirect_uri: str = field(default_factory=lambda: _env(
        "GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/finance/google/callback"))

    # Local document embeddings; no paid-provider fallback.
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "ollama"))
    embedding_url: str = field(default_factory=lambda: _env("EMBEDDING_URL", "http://127.0.0.1:11434"))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "bge-m3"))
    embedding_dimensions: int = field(default_factory=lambda: int(_env("EMBEDDING_DIMENSIONS", "1024")))
    embedding_densecore_model_id: str = field(default_factory=lambda: _env("EMBEDDING_DENSECORE_MODEL_ID", ""))

    # IANA zone for the user's calendar words (오늘, 이번 주, 다음 달); stored datetimes stay UTC.
    timezone: str = field(default_factory=lambda: _env("PERSONAL_OS_TIMEZONE", "Asia/Seoul"))

    # Context / history budgets.
    history_message_limit: int = 20
    context_char_limit: int = 24_000

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.oauth_callback_port}/auth/callback"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'personal_os.db'}"


settings = Settings()
