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
    chatgpt_usage_url: str = field(default_factory=lambda: _env("CHATGPT_USAGE_URL", "https://chatgpt.com/#settings"))

    openai_api_base: str = "https://api.openai.com/v1"
    default_model: str = field(default_factory=lambda: _env("ADVISOR_DEFAULT_MODEL", ""))

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
