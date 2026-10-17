import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.modules.database import db
from app.modules.database.model import Base
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.schema.llm_schema import LLMRequest, StreamEvent


class FakeProvider:
    """Captures every request so tests can assert exactly what would leave the machine."""

    name = "chatgpt_plan"

    def __init__(self, reply: str = "답변입니다.", error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.requests: list[LLMRequest] = []

    async def list_models(self, session) -> list[str]:
        return ["fake-model"]

    async def stream(self, session, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if self.error:
            raise self.error
        for i in range(0, len(self.reply), 8):
            yield StreamEvent("delta", text=self.reply[i:i + 8])
        yield StreamEvent("completed", usage={"input_tokens": 10, "output_tokens": 5})


class ExplodingProvider(FakeProvider):
    name = "openai_api_key"

    async def stream(self, session, request):  # pragma: no cover - must never run
        raise AssertionError("paid provider must never be called implicitly")
        yield


# Set to run the suite against PostgreSQL, e.g. the compose DB (a dedicated test database: tables are dropped).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


@pytest.fixture
def session():
    db.init(TEST_DATABASE_URL)
    Base.metadata.drop_all(db.engine)
    db.create_schema()
    with db.session() as s:
        yield s


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    monkeypatch.setitem(llm_gateway_manager.providers, "openai_api_key", ExplodingProvider())
    return provider


@pytest.fixture
def client(session):
    from app.main import app

    with TestClient(app) as c:
        yield c


NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@pytest.fixture
def seeded(session):
    from app.modules.database.model import (
        Account,
        CashflowEntry,
        FxRate,
        Holding,
        JobApplication,
        Liability,
    )

    today = date.today()
    session.add_all([
        Account(name="급여통장", kind="checking", currency="KRW", balance=Decimal("12000000"),
                balance_as_of=today, is_liquid=True),
        Account(name="달러예금", kind="deposit", currency="USD", balance=Decimal("1000"),
                balance_as_of=today, is_liquid=True),
        Liability(name="신용대출", kind="credit", currency="KRW", balance=Decimal("5000000"), balance_as_of=today),
        Holding(symbol="005930", name="삼성전자", currency="KRW", quantity=Decimal("10"),
                last_price=Decimal("70000"), price_as_of=datetime.now(UTC)),
        FxRate(base="USD", quote="KRW", rate=Decimal("1400"), as_of=datetime.now(UTC)),
        JobApplication(company="레인보우로보틱스", role="로봇 AI 플랫폼 SW", status="interviewing"),
    ])
    first_of_month = today.replace(day=1)
    for months_back in (1, 2, 3):
        d = first_of_month - timedelta(days=1)
        for _ in range(months_back - 1):
            d = d.replace(day=1) - timedelta(days=1)
        session.add(CashflowEntry(occurred_on=d.replace(day=5), kind="expense", amount=Decimal("2000000")))
    session.commit()
    return session
