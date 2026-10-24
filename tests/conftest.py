import os
from collections.abc import AsyncIterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.database import db
from app.modules.database.model import Base
from app.modules.llm.llm_gateway_manager import llm_gateway_manager
from app.modules.llm.types import LLMRequest, StreamEvent


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


@contextmanager
def migrated_database_url(tmp_path, name):
    """A disposable database upgraded to Alembic head: an isolated schema on PostgreSQL when configured."""
    from alembic import command
    from sqlalchemy import create_engine, make_url, text
    from app.modules.database.migration_manager import alembic_config
    if not TEST_DATABASE_URL.startswith("postgresql"):
        url = "sqlite:///" + str(tmp_path / (name + ".db"))
        command.upgrade(alembic_config(url), "head")
        yield url
        return
    schema = name + "_" + uuid4().hex
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    url = make_url(TEST_DATABASE_URL).update_query_dict(
        {"options": "-csearch_path=" + schema + ",public"}).render_as_string(hide_password=False)
    migration = alembic_config(url)
    migration.attributes["version_table_schema"] = schema
    try:
        command.upgrade(migration, "head")
        yield url
    finally:
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        admin.dispose()


@pytest.fixture
def session(request, tmp_path):
    url = TEST_DATABASE_URL
    if url in {'sqlite://', 'sqlite:///:memory:'} and {'client', 'locked_client'} & set(request.fixturenames):
        # HTTP subscribers, authentication checks and the server worker own separate
        # transactions. Sharing one StaticPool connection can roll back another
        # coroutine's uncommitted evidence; use independent disposable connections.
        url = f"sqlite:///{tmp_path / 'api.db'}"
    db.init(url)
    Base.metadata.drop_all(db.engine)
    db.create_schema()
    with db.session() as s:
        yield s


@pytest.fixture
def fake_provider(monkeypatch, session):
    provider = FakeProvider()
    monkeypatch.setitem(llm_gateway_manager.providers, "chatgpt_plan", provider)
    monkeypatch.setitem(llm_gateway_manager.providers, "openai_api_key", ExplodingProvider())
    # Synthetic account attestation: production gateway policy is still exercised;
    # no real OAuth credentials or personal data enter these fixtures.
    from app.modules.llm import transfer_policy
    monkeypatch.setattr(transfer_policy, "account_binding", lambda session, provider: "synthetic-account")
    transfer_policy.confirm(session, "chatgpt_plan", True, True)
    return provider


@pytest.fixture
def checkpoint_schema(session):
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    # Official saver tables belong to explicit migrations, outside ORM create_all.
    # Only this disposable test fixture installs them; application startup never does.
    with db.engine.begin() as connection:
        if "checkpoints" not in inspect(connection).get_table_names():
            with Operations.context(MigrationContext.configure(connection)):
                importlib.import_module("migrations.versions.0011_advisor_checkpoints").upgrade()


@pytest.fixture
def client(session, monkeypatch, checkpoint_schema):
    from app.main import app
    from app.modules.documents import document_manager
    from app.modules.jobs import job_manager
    from app.modules.agent import reflection

    async def idle_worker(_database, stop):
        await stop.wait()

    # Tests drive document indexing and scheduled jobs explicitly. The consultation
    # worker remains active so legacy SSE tests exercise durable server execution.
    monkeypatch.setattr(document_manager, "process_pending", idle_worker)
    monkeypatch.setattr(job_manager, "process_pending", idle_worker)
    monkeypatch.setattr(reflection, "process_pending", idle_worker)
    # The API only answers to loopback hosts (LocalTrustMiddleware); TestClient defaults to "testserver".
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        from app.config import settings
        c.headers["Origin"] = settings.frontend_url
        response = c.post("/api/security/setup", json={"password": "synthetic-test-password-123"})
        assert response.status_code == 200, response.text
        c.headers["X-CSRF-Token"] = response.json()["csrf_token"]
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
        LocalFinanceCoverage,
    )

    today = date.today()
    session.add_all([
        LocalFinanceCoverage(id=1, kinds=["cash", "holding", "liability", "other"]),
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
