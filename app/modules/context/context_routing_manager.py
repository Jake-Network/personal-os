"""PRD ContextRouter: pick the data categories a question needs (PRD §3.3).

Deterministic keyword rules, not an LLM call: routing must be explainable in the Context
Inspector and must not spend plan usage. Each rule maps a trigger to a category bundle,
so "퇴사" pulls Financial + Career + Goals as the PRD examples require.
"""

from app.enums.context_category import Category
from app.schema.context_schema import RouteDecision

C = Category

RULES: tuple[tuple[tuple[str, ...], frozenset[Category]], ...] = (
    (("퇴사", "퇴직", "쉬어도", "쉬면", "그만두", "quit", "sabbatical"),
     frozenset({C.FINANCIAL, C.CAREER, C.GOALS})),
    (("순자산", "net worth", "wealth", "assets", "지난달", "자산 이력"), frozenset({C.FINANCIAL, C.INVESTMENT})),
    (("돈", "재정", "재무", "잔고", "예금", "적금", "현금", "자산", "부채", "대출", "빚", "지출", "생활비", "저축",
      "비상금", "비상자금", "수입", "소득", "월급", "cash", "savings", "budget", "debt", "expense", "money"),
     frozenset({C.FINANCIAL})),
    (("투자", "포트폴리오", "주식", "종목", "보유", "매수", "매도", "etf", "코인", "시세", "환율", "비중", "공격적",
      "portfolio", "stock", "invest"),
     frozenset({C.INVESTMENT, C.FINANCIAL})),
    (("면접", "interview"), frozenset({C.CAREER, C.CALENDAR, C.GOALS})),
    (("커리어", "회사", "채용", "지원", "이직", "오퍼", "연봉", "직무", "포지션", "jd", "career", "job", "offer"),
     frozenset({C.CAREER, C.GOALS})),
    (("일정", "스케줄", "다음 주", "다음주", "이번 주", "이번주", "내일", "오늘", "주말", "약속", "마감", "할 일",
      "할일", "작업", "병행", "시간", "calendar", "schedule", "week", "deadline", "task"),
     frozenset({C.CALENDAR, C.GOALS})),
    (("운동", "건강", "헬스", "러닝", "회복", "수면", "체중", "workout", "health", "exercise"),
     frozenset({C.HEALTH, C.GOALS})),
    (("목표", "우선순위", "인생", "장기", "개월", "goal", "priorit"), frozenset({C.GOALS})),
)

DOMAIN_DEFAULTS: dict[str, frozenset[Category]] = {
    "financial": frozenset({C.FINANCIAL}),
    "investment": frozenset({C.INVESTMENT, C.FINANCIAL}),
    "career": frozenset({C.CAREER, C.GOALS}),
    "calendar": frozenset({C.CALENDAR, C.GOALS}),
    "health": frozenset({C.HEALTH, C.GOALS}),
}


class ContextRoutingManager:
    def route(
        self,
        query: str,
        excluded: frozenset[Category] = frozenset(),
        override: frozenset[Category] | None = None,
        previous: frozenset[Category] | None = None,
        domain: str | None = None,
    ) -> RouteDecision:
        matched: list[str] = []
        if override is not None:
            requested, reason = override, "override"
        else:
            text = query.lower()
            requested = frozenset()
            for terms, bundle in RULES:
                hits = [t for t in terms if t in text]
                if hits:
                    matched += hits
                    requested |= bundle
            reason = "keyword"
            if not requested and previous:
                requested, reason = previous, "previous_turn"  # follow-up like "그럼 6개월이면?"
            if not requested and domain in DOMAIN_DEFAULTS:
                requested, reason = DOMAIN_DEFAULTS[domain], "domain"
            if not requested:
                requested, reason = frozenset({C.GOALS}), "fallback"
        # The user's own preferences are small and shape every answer.
        requested |= {C.PROFILE}
        return RouteDecision(
            requested=requested,
            selected=requested - excluded,
            excluded=requested & excluded,
            matched_terms=tuple(matched),
            reason=reason,
        )


context_routing_manager = ContextRoutingManager()
