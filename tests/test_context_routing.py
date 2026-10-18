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
