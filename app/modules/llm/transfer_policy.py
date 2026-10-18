"""Account-bound user attestation, checked at the common inference boundary.

This records a user's verification, never claims to inspect provider settings.
Domain/record/document filtering remains the context builder's responsibility.
"""
import hashlib
import json
import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.crud import app_setting_handler, oauth_connection_handler
from app.modules.llm.errors import AdvisorError

KEY = "llm.transfer_confirmation"
POLICY_VERSION = "2026-10-18"


class TransferNotConfirmed(AdvisorError):
    code = "transfer_policy_unconfirmed"
    http_status = 403
    user_message = "현재 연결 계정의 학습 사용·보관 정책을 AI Provider 설정에서 확인하세요."


def account_binding(session: Session, provider: str) -> str | None:
    if provider == "chatgpt_plan":
        conn = oauth_connection_handler.get_active(session)
        if conn is None or conn.status != "connected":
            return None
        identity = [provider, conn.id, conn.issuer, conn.subject, conn.client_id]
    elif provider == "openai_api_key":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        identity = [provider, key]
    else:
        return None
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def status(session: Session, provider: str) -> dict:
    binding = account_binding(session, provider)
    saved = app_setting_handler.get_value(session, KEY) or {}
    valid = bool(binding and saved.get("account_binding") == binding
                 and saved.get("policy_version") == POLICY_VERSION
                 and saved.get("training_excluded") and saved.get("retention_understood"))
    return {"provider": provider, "account_available": binding is not None,
            "confirmed": valid, "verification": "user_confirmed" if valid else "unconfirmed",
            "confirmed_at": saved.get("confirmed_at") if valid else None,
            "store": False, "retention": "provider_policy_applies",
            "policy_version": POLICY_VERSION,
            "policy_url": "https://developers.openai.com/api/docs/guides/your-data"}


def confirm(session: Session, provider: str, training_excluded: bool, retention_understood: bool) -> dict:
    binding = account_binding(session, provider)
    if not binding or not training_excluded or not retention_understood:
        raise TransferNotConfirmed()
    app_setting_handler.set_value(session, KEY, {
        "account_binding": binding, "policy_version": POLICY_VERSION,
        "training_excluded": True, "retention_understood": True,
        "confirmed_at": datetime.now(UTC).isoformat(),
    })
    session.commit()
    return status(session, provider)


def invalidate(session: Session) -> None:
    app_setting_handler.set_value(session, KEY, {})
    session.flush()


def require_confirmation(session: Session, provider: str) -> None:
    if not status(session, provider)["confirmed"]:
        raise TransferNotConfirmed()
