"""PRD ContextRouter: pick the data categories a question needs (PRD §3.3).

Deterministic keyword rules, not an LLM call: routing must be explainable in the Context
Inspector and must not spend plan usage. Each rule maps a trigger to a category bundle,
so "퇴사" pulls Financial + Career + Goals as the PRD examples require.
"""

import re

from app.enums.context_category import Category
from app.modules.context.types import RouteDecision

C = Category

RULES: tuple[tuple[tuple[str, ...], frozenset[Category]], ...] = (
    (("퇴사", "퇴직", "쉬어도", "쉬면", "그만두", "quit", "sabbatical"),
     frozenset({C.FINANCIAL, C.INVESTMENT, C.CAREER, C.GOALS})),
    (("재무 상태", "재무상태", "재무 현황", "재무현황", "재정 상태", "재정상태", "자산 현황", "자산현황",
      "자산", "재무", "재정", "재산", "전체 자산", "전체자산", "총자산", "전재산", "financial overview", "financial health"),
     frozenset({C.FINANCIAL, C.INVESTMENT})),
    (("순자산", "net worth", "wealth", "assets", "자산 이력"), frozenset({C.FINANCIAL, C.INVESTMENT})),
    (("돈", "재정", "재무", "잔고", "예금", "적금", "현금", "자산", "부채", "대출", "빚", "지출", "생활비", "저축",
      "비상금", "비상자금", "수입", "소득", "월급", "cash", "savings", "budget", "debt", "expense", "money"),
     frozenset({C.FINANCIAL})),
    (("투자", "포트폴리오", "주식", "종목", "보유", "매수", "매도", "etf", "코인", "시세", "환율", "비중", "공격적",
      "portfolio", "stock", "invest"),
     frozenset({C.INVESTMENT, C.FINANCIAL})),
    (("면접", "interview"), frozenset({C.CAREER, C.CALENDAR, C.GOALS})),
    (("이력서", "경력기술서", "경력", "프로젝트", "기여", "재직", "피드백", "역량", "배운 점", "자기소개서", "자소서", "resume", "curriculum vitae", "커리어", "회사", "채용", "지원", "이직", "오퍼", "연봉", "직무", "포지션", "jd", "career", "job", "offer"),
     frozenset({C.CAREER, C.GOALS})),
    (("일정", "스케줄", "회의", "미팅", "meeting", "다음 주", "다음주", "이번 주", "이번주", "내일", "오늘", "주말", "약속", "마감", "할 일",
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

_CAREER_RECORD_TERMS = frozenset({"경력", "프로젝트", "기여", "재직", "피드백", "역량", "배운 점"})


def _matches_term(term: str, text: str) -> bool:
    # A document title such as 비밀프로젝트 is not an explicit request for career records.
    if term in _CAREER_RECORD_TERMS:
        return re.search(r"(?<!\w)" + re.escape(term), text) is not None
    return term in text


_CONTINUATION = re.compile(
    r"^\s*(?:그럼|그러면|그렇다면|그런 경우|이 경우|그 경우|그 조건|이 조건|그 기준|이 기준|"
    r"그중|그 중|그 회사|그 종목|그 일정|그 계획|그걸|이걸|그거|그렇게|그 상태|이 상태|"
    r"(?:then|what about|in that case|and if|how about|what if)\b)", re.IGNORECASE,
)
_TOPIC_RESET = re.compile(r"다른 질문|다른 얘기|주제 바꿔|새 질문|새로운 질문|new topic|unrelated question|switch topic", re.IGNORECASE)


class ContextRouter:
    def route(
        self,
        query: str,
        excluded: frozenset[Category] = frozenset(),
        override: frozenset[Category] | None = None,
        previous: frozenset[Category] | None = None,
        domain: str | None = None,
        entity_terms: tuple[str, ...] = (),
    ) -> RouteDecision:
        matched: list[str] = []
        if override is not None:
            requested, reason = override, "override"
        else:
            text = query.lower()
            requested = frozenset()
            for terms, bundle in RULES:
                hits = [t for t in terms if _matches_term(t, text)]
                if hits:
                    matched += hits
                    requested |= bundle
            reason = "keyword"
            if entity_terms:
                requested |= {C.INVESTMENT, C.FINANCIAL}
                matched += list(entity_terms)
            reset = bool(_TOPIC_RESET.search(query))
            if previous and not reset and _CONTINUATION.search(query):
                # A new time horizon or calendar facet does not erase the subject
                # of an explicit follow-up. Sharing exclusions still win below.
                requested |= previous
                reason = "previous_turn"
            if not requested and previous and not reset:
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
            matched_terms=tuple(dict.fromkeys(matched)),
            reason=reason,
        )


context_router = ContextRouter()
