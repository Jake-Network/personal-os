"""Product scenarios check the actual context sent to the model, not a canned answer."""
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.enums.context_category import Category as C
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.context.routing import context_router
from app.modules.context.privacy_manager import privacy_manager
from app.modules.database.model import Account, CalendarEvent
from app.modules.crud import message_handler
from app.modules.advisor.types import AskOptions


def ask(session, conversation, message, provider, options=None):
    async def collect():
        return [event async for event in advisor_manager.ask(session, conversation, message, options)]
    events = asyncio.run(collect())
    assert events[-1]["type"] == "done", events
    developer = next(item for item in provider.requests[-1].input if item["role"] == "developer"
                     and item["content"].startswith("Context Package"))
    return json.loads(developer["content"].split("\n", 1)[1])


def test_financial_overview_includes_registered_stocks_and_exact_totals(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "재무 상태")
    package = ask(seeded, conversation, "내 재무 상태를 평가해줘", fake_provider)
    data = package["data"]
    assert "get_portfolio_summary" in data
    assert data["get_accounts_summary"]["computed"]["net_worth"]["net_worth"] == "9100000.00"
    assert {"financial", "investment"} <= set(package["categories"])


def test_followup_keeps_domains_and_refreshes_changed_account(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "퇴사 검토")
    initial = ask(seeded, conversation, "퇴사해도 될까?", fake_provider)
    account = seeded.scalar(select(Account).where(Account.name == "급여통장"))
    account.balance = Decimal("7000000")
    seeded.commit()
    followup = ask(seeded, conversation, "그럼 6개월이면?", fake_provider)
    assert {"financial", "investment", "career"} <= set(followup["categories"])
    assert "get_cashflow_summary" in followup["data"]
    assert followup["data"]["get_accounts_summary"]["computed"]["net_worth"]["net_worth"] == "4100000.00"
    assert initial["context_snapshot_id"] != followup["context_snapshot_id"]
    assert any(item["role"] == "assistant" for item in fake_provider.requests[-1].input)


def test_overview_and_followup_respect_explicit_investment_exclusion(seeded, fake_provider):
    privacy_manager.set_excluded(seeded, [C.INVESTMENT])
    conversation = advisor_manager.create_conversation(seeded, "공유 범위")
    ask(seeded, conversation, "내 재무 상태를 평가해줘", fake_provider)
    package = ask(seeded, conversation, "그럼 6개월이면?", fake_provider)
    assert "get_accounts_summary" in package["data"]
    assert "get_portfolio_summary" not in package["data"]
    assert "investment" in package["excluded_categories"]
    sent = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert "005930" not in sent and "삼성전자" not in sent


def test_explicit_scope_still_wins_over_previous_turn(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "명시적 범위")
    ask(seeded, conversation, "내 재무 상태를 평가해줘", fake_provider)
    package = ask(seeded, conversation, "그럼 6개월이면?", fake_provider,
                  AskOptions(categories=frozenset({C.HEALTH})))
    assert set(package["categories"]) == {"health", "profile"}
    assert "get_accounts_summary" not in package["data"]


def test_new_topic_does_not_inherit_unrelated_financial_scope():
    route = context_router.route("오늘 운동 일정 알려줘", previous=frozenset({C.FINANCIAL, C.INVESTMENT}))
    assert C.CALENDAR in route.selected and C.HEALTH in route.selected
    assert C.FINANCIAL not in route.selected


def test_registered_stock_name_without_investment_keyword_reaches_model(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "등록 종목")
    package = ask(seeded, conversation, "삼성전자는 몇 개 있지?", fake_provider)
    holdings = package["data"]["get_portfolio_summary"]["holdings"]
    samsung = next(row for row in holdings if row["symbol"] == "005930")
    assert Decimal(samsung["quantity"]) == Decimal(10)
    assert samsung["ref"].startswith("holdings:")


def test_company_name_does_not_pollute_interview_or_calendar_with_holdings(seeded):
    for query in ("삼성전자 면접 준비해줘", "삼성전자 일정 알려줘", "지난달 일정 알려줘"):
        route = advisor_manager.route(seeded, query, None, AskOptions())
        assert C.CALENDAR in route.selected
        assert C.INVESTMENT not in route.selected and C.FINANCIAL not in route.selected
    mixed = advisor_manager.route(seeded, "삼성전자 주식이랑 면접 일정 알려줘", None, AskOptions())
    assert {C.INVESTMENT, C.FINANCIAL, C.CALENDAR, C.CAREER} <= mixed.selected


def test_next_month_events_reach_model_and_current_month_does_not(seeded, fake_provider):
    now = datetime.now(UTC)
    year, month = divmod(now.year * 12 + now.month, 12)
    event = CalendarEvent(title="다음 달 기록된 상담", starts_at=datetime(year, month + 1, 15, 10, tzinfo=UTC),
                          ends_at=datetime(year, month + 1, 15, 11, tzinfo=UTC))
    seeded.add_all([event, CalendarEvent(title="이번 달의 다른 일정", starts_at=now)])
    seeded.commit()
    conversation = advisor_manager.create_conversation(seeded, "일정 조회")
    package = ask(seeded, conversation, "다음 달 일정 알려줘", fake_provider)
    calendar = package["data"]["get_calendar_events"]
    assert calendar["window"]["status"] == "explicit"
    assert calendar["window"]["start"].startswith(f"{year:04d}-{month + 1:02d}-01")
    assert [row["ref"] for row in calendar["events"]] == [f"calendar_events:{event.id}"]
    blocked = ask(seeded, conversation, "그럼 다음 달 일정은?", fake_provider,
                  AskOptions(exclude=frozenset({C.CALENDAR})))
    assert "get_calendar_events" not in blocked["data"]
    assert "다음 달 기록된 상담" not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_latest_history_and_before_cursor_use_real_id_bounds(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "이력 조회")
    ask(seeded, conversation, "내 재무 상태 알려줘", fake_provider)
    ask(seeded, conversation, "그럼 6개월이면?", fake_provider)
    messages = message_handler.get_by_conversation(seeded, conversation.id)
    latest = message_handler.get_replayable_before(seeded, conversation.id, None)[-2:]
    earlier = message_handler.get_replayable_before(seeded, conversation.id, messages[2].id)
    assert [m.id for m in latest] == [m.id for m in messages[-2:]]
    assert [m.id for m in earlier] == [m.id for m in messages[:2]]
