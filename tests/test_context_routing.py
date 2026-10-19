import pytest

from app.enums.context_category import Category as C
from app.modules.context.routing import context_router as router


def test_prd_examples():
    assert {C.INVESTMENT, C.FINANCIAL} <= router.route("현재 포트폴리오가 너무 공격적인지 분석해 줘").selected
    assert {C.CAREER, C.CALENDAR, C.GOALS} <= router.route("면접 준비 어떻게 하지").selected
    assert {C.FINANCIAL, C.CAREER, C.GOALS} <= router.route("지금 회사를 퇴사하고 3개월 쉬어도 괜찮을까?").selected
    assert {C.CALENDAR, C.GOALS} <= router.route("다음 주 계획 세워줘").selected
    assert {C.FINANCIAL, C.INVESTMENT} <= router.route("현재 내 순자산은?").selected


def test_unrelated_categories_are_not_selected():
    assert C.HEALTH not in router.route("현재 내 순자산은?").selected
    assert C.CAREER not in router.route("포트폴리오 비중 알려줘").selected


def test_exclusions_win_and_are_reported():
    d = router.route("퇴사해도 될까", excluded=frozenset({C.FINANCIAL}))
    assert C.FINANCIAL not in d.selected
    assert d.excluded == frozenset({C.FINANCIAL})


def test_follow_up_reuses_previous_categories():
    d = router.route("그럼 그 다음은?", previous=frozenset({C.CAREER}))
    assert d.reason == "previous_turn" and C.CAREER in d.selected


@pytest.mark.parametrize("query", [
    "하프 마라톤 1시간 35분 하는건 좀 무리일까?",
    "토요일에 마라톤 훈련 했고 일요일에는 8km 5분 30초 훈련 했어",
    "내가 토요일에 10km를 어떻게 훈련했지?",
])
def test_running_questions_select_workout_records(query):
    # Calendar words and a previous non-health scope must not hide workout data.
    decision = router.route(query, previous=frozenset({C.CALENDAR, C.GOALS}))
    assert C.HEALTH in decision.selected
    blocked = router.route(query, excluded=frozenset({C.HEALTH}))
    assert C.HEALTH not in blocked.selected
    assert C.HEALTH in blocked.excluded
