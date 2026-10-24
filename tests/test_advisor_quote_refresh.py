"""Explicit quote requests keep their existing connection and cooldown contract."""

import pytest
from datetime import UTC, datetime
from decimal import Decimal
from app.modules.advisor.quote_refresh import quote_refresh_requested, split_quote_refresh, refresh_quotes
from app.modules.database.model import Holding, LocalPosition, MarketSettings


def test_quote_request_is_separated_from_pending_confirmation():
    query = "응 해줘 그리고 최신 현재가 시세 갱신해줘"
    assert split_quote_refresh(query) == ("응 해줘", True)
    assert split_quote_refresh("시세 갱신해줘") == ("", True)


@pytest.mark.parametrize("query", [
    "시세를 업데이트해줘", "현재가 새로고침해줘", "주가를 갱신해 주세요",
])
def test_explicit_quote_refresh_is_recognized(query):
    assert quote_refresh_requested(query)


@pytest.mark.parametrize("query", [
    '"시세 갱신해줘"라고 적힌 문서를 설명해줘', "시세 갱신하는 방법 알려줘",
    "시세 갱신하지 마", "내일 시세 갱신해줘", "매일 시세 갱신해줘", "시세 갱신할까?",
])
def test_quote_refresh_does_not_execute_quotes_hypotheticals_or_schedules(query):
    assert not quote_refresh_requested(query)


class PublicQuotes:
    source_identity = 'synthetic-quotes-identity'

    def __init__(self):
        self.reads = []
        self.provisions = []
        self.rows = None
        self.failure = False

    def read(self, sheet):
        self.reads.append(sheet)
        if self.failure:
            raise ValueError('synthetic provider unavailable')
        serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
        return self.rows if self.rows is not None else [['KRX:000001', 27, 'KRW', serial, 20]], []

    def provision(self, sheet, symbols, currencies):
        self.provisions.append((sheet, symbols, currencies))


@pytest.fixture
def quote_data(session, monkeypatch):
    from app.modules.portfolio import portfolio_manager
    monkeypatch.setattr(portfolio_manager, '_source', lambda session: ('synthetic-quotes-identity', False))
    row = Holding(symbol='KRX:000001', name='합성 종목', currency='KRW', quantity=3, avg_cost=Decimal('11'))
    session.add(row)
    session.flush()
    session.add(LocalPosition(position_id='synthetic-position', holding_id=row.id, quote_mode='auto', version='synthetic'))
    session.add(MarketSettings(id=1, spreadsheet_id='synthetic-public-file', source_identity='synthetic-quotes-identity'))
    session.commit()
    return row, PublicQuotes()


def test_unconnected_refresh_stays_separate_from_local_recording(session):
    fake = PublicQuotes()
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'needs_input'
    assert result['refresh_state'] == 'not_connected'
    assert fake.reads == fake.provisions == []


def test_explicit_refresh_reuses_quote_observations_and_cooldown(session, quote_data):
    row, fake = quote_data
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'saved'
    assert result['refresh_state'] == 'updated'
    session.refresh(row)
    assert row.last_price == Decimal('27')
    assert row.quantity == 3 and row.avg_cost == Decimal('11')
    second = refresh_quotes(session, client=fake)
    assert second['status'] == 'needs_input' and second['refresh_state'] == 'cooldown'
    assert second['refresh_after_seconds'] > 0
    assert fake.reads == ['synthetic-public-file']
    assert fake.provisions == []


def test_formula_provision_sends_only_public_symbols_and_currencies(session, quote_data):
    row, fake = quote_data
    fake.rows = []
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'needs_input' and result['refresh_state'] == 'waiting'
    assert fake.provisions == [('synthetic-public-file', {'KRX:000001'}, {'KRW'})]
    session.refresh(row)
    assert row.last_price is None and row.avg_cost == Decimal('11')


def test_failed_refresh_preserves_price_and_has_no_success_receipt(session, quote_data):
    row, fake = quote_data
    row.last_price = Decimal('19')
    session.commit()
    fake.failure = True
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'failed' and result['refresh_state'] == 'failed'
    session.refresh(row)
    assert row.last_price == Decimal('19')


def test_sharing_exclusion_blocks_refresh_before_gateway(session, quote_data):
    _, fake = quote_data
    result = refresh_quotes(session, excluded={'investment'}, client=fake)
    assert result['status'] == 'failed' and result['refresh_state'] == 'sharing_excluded'
    assert fake.reads == fake.provisions == []


def test_private_position_blocks_aggregate_refresh(session, quote_data):
    from app.modules.context.record_privacy import set_record_policy
    row, fake = quote_data
    set_record_policy(session, 'holdings', row.id, False)
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'failed' and result['refresh_state'] == 'sharing_excluded'
    assert fake.reads == fake.provisions == []


def test_authorization_revoked_during_read_propagates_without_updating_price(session, quote_data):
    row, fake = quote_data
    checks = []

    def check():
        checks.append(True)
        if len(checks) >= 3:
            raise RuntimeError('synthetic lease lost')

    with pytest.raises(RuntimeError, match='synthetic lease lost'):
        refresh_quotes(session, client=fake, authorization_check=check)
    session.refresh(row)
    assert row.last_price is None


def test_sharing_revoked_during_read_cannot_update_prices_or_disclose_ticker_warning(session, quote_data):
    from sqlalchemy.orm import Session
    from app.modules.context.record_privacy import set_record_policy
    row, fake = quote_data
    original = fake.read

    def read(sheet):
        with Session(session.bind) as policy_session:
            set_record_policy(policy_session, 'holdings', row.id, False)
        return original(sheet)

    fake.read = read
    result = refresh_quotes(session, client=fake)
    assert result['status'] == 'failed' and result['refresh_state'] == 'sharing_excluded'
    assert row.symbol not in result['message']
    session.refresh(row)
    assert row.last_price is None
