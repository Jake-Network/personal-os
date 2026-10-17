"""Provider error taxonomy. Each maps to a distinct, user-facing recovery path.

None of these trigger a fallback to a paid API provider (PRD §2.3, AC-17).
"""


class AdvisorError(Exception):
    code = "advisor_error"
    http_status = 502
    user_message = "AI 응답을 생성하지 못했습니다."

    def __init__(self, detail: str | None = None, provider_code: str | None = None):
        super().__init__(detail or self.user_message)
        self.detail = detail
        self.provider_code = provider_code

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.user_message, "provider_code": self.provider_code}


class NotConnected(AdvisorError):
    code = "not_connected"
    http_status = 409
    user_message = "ChatGPT 계정이 연결되어 있지 않습니다. Settings → AI Provider에서 연결하세요."


class AuthRequired(AdvisorError):
    code = "reauth_required"
    http_status = 401
    user_message = "ChatGPT 인증이 만료되었거나 철회되었습니다. 다시 로그인하세요."


class ConsentDeclined(AdvisorError):
    code = "consent_declined"
    http_status = 403
    user_message = "ChatGPT 로그인 또는 구독 사용 권한 동의가 취소되었습니다."


class ScopeNotAuthorized(AdvisorError):
    code = "plan_usage_not_authorized"
    http_status = 403
    user_message = "ChatGPT 구독 사용 권한(chatgpt.tokens.use.direct)이 승인되지 않았습니다. 권한을 포함해 다시 연결하세요."


class QuotaExceeded(AdvisorError):
    code = "plan_usage_limit_exceeded"
    http_status = 429
    user_message = "ChatGPT 구독 사용량 한도에 도달했습니다. 유료 API로 자동 전환하지 않습니다. ChatGPT 설정 → Usage에서 확인하세요."


class UsageUnavailable(AdvisorError):
    code = "plan_usage_unavailable"
    http_status = 503
    user_message = "현재 ChatGPT 구독 사용량을 이용할 수 없습니다. 잠시 후 다시 시도하세요."


class IncompleteResponse(AdvisorError):
    code = "response_incomplete"
    http_status = 502
    user_message = "AI 응답이 중간에 끊겼습니다. 부분 응답은 미완료로 저장됩니다."


class ProviderUnavailable(AdvisorError):
    code = "provider_unavailable"
    http_status = 502
    user_message = "AI 제공자에 연결하지 못했습니다."
