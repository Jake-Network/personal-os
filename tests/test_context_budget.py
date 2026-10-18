"""The Context Package never exceeds its serialized size budget and never silently loses numbers."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import AdvisorManager
from app.modules.context.context_builder_manager import BudgetExceeded, ContextBuilderManager
from app.modules.context.context_routing_manager import context_routing_manager
from app.modules.database.model import CalendarEvent, JobApplication
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.schema.context_schema import RouteDecision

ALL = frozenset(Category)


def route(categories=ALL) -> RouteDecision:
    return RouteDecision(requested=categories, selected=categories, excluded=frozenset(), matched_terms=(),
                         reason="override")


@pytest.fixture
def bulky(seeded):
    now = datetime.now(UTC)
    seeded.add_all([JobApplication(company=f"회사{i:02d}", role="SW", status="applied", jd_text="자격요건 " * 400,
                                   notes="메모 " * 200) for i in range(30)])
    seeded.add(JobApplication(company="딥마인드코리아", role="Research", status="applied", jd_text="x" * 2000))
    seeded.add_all([CalendarEvent(title=f"일정 {i}", starts_at=now + timedelta(hours=i), notes="n" * 300)
                    for i in range(40)])
    seeded.commit()
    return seeded


def size(package) -> int:
    return len(package.text)


def codes(package) -> set[str]:
    return {f["code"] for f in package.data_quality_flags}


@pytest.mark.parametrize("limit", [24_000, 12_000, 6_000])
def test_package_respects_the_strict_budget(bulky, limit):
    package = ContextBuilderManager(limit).build(bulky, route(), query="딥마인드코리아 지원 어때?")
    assert size(package) <= limit
    worth = package.payload["data"]["get_accounts_summary"]["computed"]["net_worth"]
    assert worth["net_worth"] == "9100000.00"  # essential numbers survive every step
    assert package.payload["data"]["cash_runway"]["available"] is True
    assert codes(package) & {"context_text_trimmed", "context_text_omitted", "context_rows_omitted",
                             "context_section_omitted", "context_records_summarized"}


def test_question_relevant_rows_are_kept_when_rows_are_dropped(bulky):
    package = ContextBuilderManager(9_000).build(bulky, route(), query="딥마인드코리아 지원 어때?")
    apps = package.payload["data"].get("get_job_applications")
    assert apps is not None, "relevant section must outlive unrelated ones"
    assert "딥마인드코리아" in [a["company"] for a in apps["applications"]]
    assert apps["applications_omitted_rows"] > 0
    omitted = {f["detail"] for f in package.data_quality_flags if f["code"] == "context_section_omitted"}
    assert "get_job_applications" not in omitted


def test_omitted_sections_are_reported(bulky):
    package = ContextBuilderManager(4_000).build(bulky, route(), query="")
    omitted = {f["detail"] for f in package.data_quality_flags if f["code"] == "context_section_omitted"}
    assert omitted and omitted.isdisjoint({"get_accounts_summary", "get_cashflow_summary", "cash_runway"})
    assert omitted <= {"get_job_applications", "get_calendar_events", "get_tasks", "get_goals", "get_health_summary",
                       "get_interview_schedule", "get_relevant_news", "get_market_data", "get_profile",
                       "get_monthly_asset_history"}
    assert size(package) <= 4_000


def test_fitting_is_deterministic(bulky):
    builder = ContextBuilderManager(6_000)
    now = datetime(2026, 10, 18, tzinfo=UTC)
    a = builder.build(bulky, route(), now=now, query="딥마인드코리아")
    bulky.rollback()
    b = builder.build(bulky, route(), now=now, query="딥마인드코리아")
    assert a.payload["data"] == b.payload["data"]
    assert a.data_quality_flags == b.data_quality_flags


def test_small_package_is_untouched(seeded):
    package = ContextBuilderManager(24_000).build(seeded, route(frozenset({Category.FINANCIAL})))
    assert not codes(package) & {"context_text_trimmed", "context_section_omitted", "context_rows_omitted"}


def test_budget_too_small_for_essentials_fails_closed(seeded, fake_provider):
    with pytest.raises(BudgetExceeded):
        ContextBuilderManager(300).build(seeded, route())

    manager = AdvisorManager(gateway=llm_gateway_manager, router=context_routing_manager,
                             builder=ContextBuilderManager(300), history_limit=20)
    conv = manager.create_conversation(seeded, "x")

    async def collect():
        return [e async for e in manager.ask(seeded, conv, "현재 내 순자산은?")]

    events = asyncio.run(collect())
    assert events == [{"type": "error", **BudgetExceeded().as_dict()}]
    assert fake_provider.requests == []  # nothing was sent


def test_payload_size_includes_snapshot_header(bulky):
    package = ContextBuilderManager(5_000).build(bulky, route(), query="")
    assert len(json.dumps(package.payload, ensure_ascii=False, separators=(",", ":"))) <= 5_000
