from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.enums.context_category import Category
from app.modules.context import context_tool_manager
from app.modules.context.calendar_scope import calendar_scope
from app.modules.context.context_tool_manager import get_calendar_events
from app.modules.database.model import CalendarEvent
from app.modules.context.types import ToolContext


NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


@pytest.fixture
def utc_calendar(monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(context_tool_manager, "settings", replace(context_tool_manager.settings, timezone="UTC"))


@pytest.mark.parametrize(("query", "start", "end"), [
    ("오늘 일정", "2026-10-18", "2026-10-19"),
    ("내일 일정", "2026-10-19", "2026-10-20"),
    ("모레 일정", "2026-10-20", "2026-10-21"),
    ("어제 일정", "2026-10-17", "2026-10-18"),
    ("이번 주 일정", "2026-10-12", "2026-10-19"),
    ("다음주 일정", "2026-10-19", "2026-10-26"),
    ("지난 주 일정", "2026-10-05", "2026-10-12"),
    ("이번달 일정", "2026-10-01", "2026-11-01"),
    ("다음 달 일정", "2026-11-01", "2026-12-01"),
    ("지난달 일정", "2026-09-01", "2026-10-01"),
    ("2026-11-15 일정", "2026-11-15", "2026-11-16"),
    ("day after tomorrow", "2026-10-20", "2026-10-21"),
    ("next month appointments", "2026-11-01", "2026-12-01"),
    ("What may I have scheduled tomorrow?", "2026-10-19", "2026-10-20"),  # "may" is not the month
])
def test_explicit_calendar_windows(query, start, end):
    scope = calendar_scope(query, NOW)
    assert scope.status == "explicit"
    assert scope.start == datetime.fromisoformat(start).replace(tzinfo=UTC)
    assert scope.end == datetime.fromisoformat(end).replace(tzinfo=UTC)


@pytest.mark.parametrize(("now", "query", "start", "end"), [
    (datetime(2026, 12, 31, tzinfo=UTC), "다음달", "2027-01-01", "2027-02-01"),
    (datetime(2027, 1, 1, tzinfo=UTC), "지난달", "2026-12-01", "2027-01-01"),
    (datetime(2028, 2, 1, tzinfo=UTC), "이번달", "2028-02-01", "2028-03-01"),
])
def test_month_boundaries(now, query, start, end):
    scope = calendar_scope(query, now)
    assert scope.start.date().isoformat() == start
    assert scope.end.date().isoformat() == end


@pytest.mark.parametrize("query", ["2026-02-30 일정", "9999-12-31 일정", "2026-1-5 일정", "11월 15일 일정", "다다음주 일정",
                                    "내년 일정", "이번 주말 일정", "오늘과 내일 일정", "다음달 15일 일정",
                                    "May 3 appointments", "plans in March", "June schedule"])
def test_unresolved_calendar_dates_are_not_claimed(query):
    scope = calendar_scope(query, NOW)
    assert scope.status == "unresolved"
    assert scope.start == NOW - timedelta(hours=12)
    assert scope.end == NOW + timedelta(days=14)


def test_calendar_timezone_is_context_timezone():
    local = timezone(timedelta(hours=9))
    scope = calendar_scope("내일", datetime(2026, 10, 18, 1, tzinfo=local))
    assert scope.start == datetime(2026, 10, 19, tzinfo=local)
    assert scope.as_dict()["timezone"] == "UTC+09:00"
    assert scope.as_dict()["start"].endswith("+09:00")


def test_calendar_default_window_is_labeled():
    scope = calendar_scope("등록한 일정 알려줘", NOW)
    assert scope.status == "default"
    assert scope.start == NOW - timedelta(hours=12)
    assert scope.end == NOW + timedelta(days=14)


def test_next_month_context_uses_requested_events_and_exact_refs(session, utc_calendar):
    session.add_all([
        CalendarEvent(title="이번달", starts_at=datetime(2026, 10, 20, tzinfo=UTC)),
        CalendarEvent(title="다음달 면접", starts_at=datetime(2026, 11, 15, 9, tzinfo=UTC)),
        CalendarEvent(title="다다음달", starts_at=datetime(2026, 12, 1, tzinfo=UTC)),
    ])
    session.flush()
    result = get_calendar_events(ToolContext(session, NOW, frozenset({Category.CALENDAR}), query="다음달 일정"))
    assert [e["title"] for e in result.data["events"]] == ["다음달 면접"]
    assert result.data["window"]["status"] == "explicit"
    assert result.data["window"]["timezone"] == "UTC"
    assert [f"{r['table']}:{r['id']}" for r in result.refs] == [e["ref"] for e in result.data["events"]]
    assert all(r["table"] == "calendar_events" for r in result.refs)


def test_yesterday_window_includes_overlap_and_excludes_end_boundary(session, utc_calendar):
    start = datetime(2026, 10, 17, tzinfo=UTC)
    session.add_all([
        CalendarEvent(title="ongoing", starts_at=start - timedelta(hours=2), ends_at=start + timedelta(hours=1)),
        CalendarEvent(title="ends at start", starts_at=start - timedelta(hours=2), ends_at=start),
        CalendarEvent(title="starts at start", starts_at=start),
        CalendarEvent(title="starts at end", starts_at=start + timedelta(days=1)),
        CalendarEvent(title="point before", starts_at=start - timedelta(seconds=1)),
    ])
    session.flush()
    result = get_calendar_events(ToolContext(session, NOW, frozenset({Category.CALENDAR}), query="어제 일정"))
    assert [e["title"] for e in result.data["events"]] == ["ongoing", "starts at start"]


def test_unresolved_calendar_result_warns_about_partial_scope(session, utc_calendar):
    result = get_calendar_events(ToolContext(session, NOW, frozenset({Category.CALENDAR}), query="내년 일정"))
    assert result.data["window"]["status"] == "unresolved"
    assert "calendar_time_scope_unresolved" in {f["code"] for f in result.flags}


def test_calendar_words_use_the_configured_local_day(session, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(context_tool_manager, "settings", replace(context_tool_manager.settings, timezone="Asia/Seoul"))
    morning_kst = datetime(2026, 10, 17, 23, tzinfo=UTC)  # 2026-10-18 08:00 in Seoul
    session.add_all([
        CalendarEvent(title="오늘 오후", starts_at=datetime(2026, 10, 18, 5, tzinfo=UTC)),  # 14:00 KST
        CalendarEvent(title="어제 저녁", starts_at=datetime(2026, 10, 17, 10, tzinfo=UTC)),  # 10-17 19:00 KST
    ])
    session.flush()
    result = get_calendar_events(ToolContext(session, morning_kst, frozenset({Category.CALENDAR}), query="오늘 일정"))
    assert [e["title"] for e in result.data["events"]] == ["오늘 오후"]
    assert result.data["window"]["start"] == "2026-10-18T00:00:00+09:00"
    assert result.data["window"]["timezone"] == "Asia/Seoul"
