"""Context package errors."""

from app.modules.llm.errors import AdvisorError


class BudgetExceeded(AdvisorError):
    code = "context_over_budget"
    http_status = 422
    user_message = "필수 재무 수치와 확인된 제약을 보존하면 Context 길이 제한을 넘어 요청을 보내지 않았습니다."
