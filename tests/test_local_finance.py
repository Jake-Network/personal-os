"""Local authority, public-only quote payloads, immutable evidence and idempotency."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.database.model import (
    Account,
    Holding,
    MarketObservation,
    MarketSettings,
    PortfolioImport,
    PortfolioSettings,
)
from app.modules.finance import ledger_manager
from app.modules.portfolio import (
    holdings_manager as holdings,
)
from app.modules.portfolio import (
    market_data_manager as market,
)
from app.modules.portfolio.quotes_sheet import quote_rows
from app.schema.holdings_schema import HoldingInput
from app.schema.market_data_schema import MonthCloseInput, TransactionInput


def body(**kwargs):
    return HoldingInput(
        position_id="local-a",
        request_id="request-a",
        ticker="KRX:005930",
        label="Private name",
        currency="KRW",
        quantity="2",
        avg_cost="120",
        quote_mode="manual",
        manual_price="150",
        price_as_of=date.today(),
        **kwargs,
    )


def test_local_save_no_google_and_request_replay(session):
    session.add(PortfolioSettings(id=1, spreadsheet_id="old-private-sheet"))
    session.commit()
    first = holdings.save(session, body())
    assert first["saved"] and first["portfolio"]["investments"] == "300.00"
    holdings.save(session, body())
    assert session.scalar(select(func.count()).select_from(Holding)) == 1
    changed = body().model_copy(update={"quantity": 3})
    with pytest.raises(ValueError, match="Request ID"):
        holdings.save(session, changed)
    stale = changed.model_copy(
        update={"request_id": "request-b", "expected_version": "0"}
    )
    with pytest.raises(RuntimeError, match="changed"):
        holdings.save(session, stale)
    row = holdings.listing(session)["rows"][0]
    updated = changed.model_copy(
        update={"request_id": "request-c", "expected_version": row["expected_version"]}
    )
    assert holdings.save(session, updated)["portfolio"]["investments"] == "450.00"
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 1


def test_quote_payload_only_symbols_and_generated_formulas():
    rows = quote_rows(
        ["NASDAQ:AAPL", "NASDAQ:AAPL", "KRX:005930", "EVIL:1", "=IMPORTXML(1)"]
    )
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"NASDAQ:AAPL", "KRX:005930"}
    assert all(len(r) == 5 and all("GOOGLEFINANCE" in v for v in r[1:]) for r in rows)


class FakeQuotes:
    source_identity = "synthetic"

    def __init__(self):
        serial = (
            datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)
        ).total_seconds() / 86400
        self.quotes = [["KRX:005930", 150, "KRW", serial, 20]]
        self.calls = []

    def create(self):
        return "dedicated-public-file"

    def read(self, sheet):
        return self.quotes, []

    def provision(self, sheet, symbols, currencies):
        self.calls.append((symbols, currencies))


def test_quotes_same_observation_does_not_refresh_date_and_bad_quote_preserved(session):
    auto = body().model_copy(
        update={"quote_mode": "auto", "manual_price": None, "price_as_of": None}
    )
    holdings.save(session, auto)
    fake = FakeQuotes()
    market.initialize(session, fake)
    market.refresh(session, fake)
    obj = session.scalar(select(Holding))
    first_time = obj.price_as_of
    observation = session.scalar(
        select(MarketObservation).where(MarketObservation.provider == "googlefinance")
    )
    collected = observation.observed_at
    settings = session.get(MarketSettings, 1)
    settings.last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)
    session.commit()
    market.refresh(session, fake)
    assert (
        session.scalar(
            select(func.count())
            .select_from(MarketObservation)
            .where(MarketObservation.provider == "googlefinance")
        )
        == 1
    )
    assert obj.price_as_of == first_time and observation.observed_at == collected
    fake.quotes = [["KRX:005930", "#N/A", "KRW", 0, 20]]
    settings.last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)
    session.commit()
    market.refresh(session, fake)
    assert obj.last_price == 150 and obj.price_as_of == first_time


def test_import_replay_keeps_distinct_positions_and_original_import(session):
    rows = [
        {
            "id": id,
            "ticker": "KRX:005930",
            "label": id,
            "currency": "KRW",
            "quantity": "2",
            "source": "googlefinance",
        }
        for id in ("account-a", "account-b")
    ]
    imported = PortfolioImport(
        spreadsheet_id="legacy", source_identity="test", payload={"Holdings": rows}
    )
    session.add(imported)
    session.commit()
    assert market.import_holdings(session, imported.id)["imported"] == 2
    assert market.import_holdings(session, imported.id)["imported"] == 0
    assert session.scalar(select(func.count()).select_from(Holding)) == 2
    assert session.get(PortfolioImport, imported.id).payload["Holdings"] == rows


def transaction(kind, request, **kwargs):
    return TransactionInput(
        kind=kind,
        request_id=request,
        occurred_at=datetime.now(UTC) - timedelta(days=1),
        amount="100",
        source="synthetic",
        **kwargs,
    )


def test_transfers_trades_and_reversals_do_not_inflate_income(session):
    a = Account(
        name="a",
        kind="checking",
        currency="KRW",
        balance=100,
        balance_as_of=date.today(),
    )
    b = Account(
        name="b",
        kind="checking",
        currency="KRW",
        balance=100,
        balance_as_of=date.today(),
    )
    session.add_all([a, b])
    session.commit()
    income = ledger_manager.record(session, transaction("income", "income"))
    ledger_manager.record(
        session,
        transaction(
            "transfer", "transfer", account_id=a.id, counterparty_account_id=b.id
        ),
    )
    result = ledger_manager.trend(session, date.today().year)
    assert result["cashflow_by_currency"]["KRW"]["income"] == "100"
    assert result["cashflow_by_currency"]["KRW"]["transfer"] == "100"
    reversal = transaction("reversal", "reverse", reverses_id=income["id"])
    ledger_manager.record(session, reversal)
    assert ledger_manager.record(session, reversal)["id"]
    assert (
        ledger_manager.trend(session, date.today().year)["cashflow_by_currency"]["KRW"][
            "income"
        ]
        == "0"
    )
    assert a.balance == 100 and b.balance == 100
    with pytest.raises(RuntimeError, match="already reversed"):
        ledger_manager.record(
            session, transaction("reversal", "reverse2", reverses_id=income["id"])
        )


def test_local_month_close_requires_explicit_historical_evidence(session):
    month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    end = date.today().replace(day=1) - timedelta(days=1)
    evidence = {
        "kind": "holding",
        "id": "original",
        "label": "synthetic",
        "currency": "KRW",
        "as_of": end,
        "quantity": "2",
        "price": "100",
        "price_as_of": end,
        "source": "manual-close",
        "close_valid_through": end,
    }
    close = MonthCloseInput(
        month=month,
        reason="Confirmed historical evidence",
        coverage=["cash", "holding", "liability", "other"],
        rows=[evidence],
    )
    assert ledger_manager.close_month(session, close)["investments"] == "200.00"
    with pytest.raises(RuntimeError, match="already closed"):
        ledger_manager.close_month(session, close)
    bad = close.model_copy(update={"month": month.replace(year=month.year - 1)})
    with pytest.raises(ValueError, match="evidence incomplete"):
        ledger_manager.close_month(session, bad)


def test_csv_preview_is_read_only_and_account_links_survive_replay(session):
    from app.schema.market_data_schema import CsvImportInput

    csv_text = "kind,id,label,currency,balance,as_of,ticker,quantity,avg_cost,account_id,account_label\ncash,bank,Private brokerage,KRW,500,2026-09-30,,,,,\nholding,a,First lot,KRW,,,KRX:005930,2,100,bank,Private brokerage\nholding,b,Second lot,KRW,,,KRX:005930,3,110,bank,Private brokerage\n"
    body = CsvImportInput(source_id="synthetic-import", csv_text=csv_text)
    preview = market.csv_preview(session, body)
    assert len(preview["rows"]) == 3
    assert not any(r["issues"] for r in preview["rows"])
    assert session.scalar(select(func.count()).select_from(PortfolioImport)) == 0
    assert market.csv_import(session, body)["imported"] == 3
    assert market.csv_import(session, body)["imported"] == 0
    positions = session.scalars(select(Holding).order_by(Holding.id)).all()
    assert len(positions) == 2 and positions[0].account_id == positions[1].account_id
    assert positions[0].account_id is not None
    assert sum(p.quantity for p in positions) == Decimal("5")
    assert session.get(Account, positions[0].account_id).name == "Private brokerage"
    with pytest.raises(RuntimeError, match="source ID"):
        market.csv_import(
            session,
            body.model_copy(
                update={"csv_text": csv_text.replace(",2,100,", ",4,100,")}
            ),
        )


def test_actual_advisor_payload_uses_same_unavailable_local_valuation(
    session, fake_provider
):
    import asyncio
    import json

    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.database.model import LocalFinanceCoverage
    from app.modules.portfolio.local_portfolio import portfolio

    session.add(
        LocalFinanceCoverage(id=1, kinds=["cash", "holding", "liability", "other"])
    )
    session.add_all(
        [
            Holding(
                symbol="KNOWN",
                name="Known",
                quantity=2,
                currency="KRW",
                last_price=100,
                price_as_of=datetime.now(UTC),
            ),
            Holding(symbol="MISSING", name="Missing", quantity=1, currency="KRW"),
        ]
    )
    session.commit()
    assert portfolio(session)["investments"] is None
    from app.modules.dashboard.dashboard_manager import dashboard_manager

    dashboard = dashboard_manager.summary(session)
    assert (
        dashboard["data"]["get_accounts_summary"]["computed"]["net_worth"]["net_worth"]
        is None
    )
    assert (
        dashboard["data"]["get_portfolio_summary"]["computed"]["total_value_base"]
        is None
    )
    conversation = advisor_manager.create_conversation(session, "Local valuation")

    async def ask():
        return [
            event
            async for event in advisor_manager.ask(
                session, conversation, "보유 주식 포트폴리오 비중을 알려줘"
            )
        ]

    asyncio.run(ask())
    developer = next(
        item
        for item in fake_provider.requests[-1].input
        if item["role"] == "developer" and item["content"].startswith("Context Package")
    )
    payload = json.loads(developer["content"].split("\n", 1)[1])
    investment = payload["data"]["get_portfolio_summary"]["computed"]
    assert investment["total_value_base"] is None
    assert investment["recorded_subtotal_base"] == "200.00"
    assert investment["weight_by_currency_pct"] == {}
