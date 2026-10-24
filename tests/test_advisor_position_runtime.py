"""Separate-account clarification and public symbol lookup cross the real worker."""
from decimal import Decimal

from sqlalchemy import select

from app.modules.database.model import Holding, LocalPosition
from test_advisor_runtime_execution import runtime_env  # noqa: F401
from test_advisor_command_continuations import consult, data_command, plain_consult


def existing_position(database):
    with database.session() as session:
        row = Holding(symbol='NYSEARCA:QGLD', name='합성 기존 보유분', quantity=Decimal('21'),
                      avg_cost=Decimal('45.15'), currency='USD', last_price=Decimal('39.86'))
        session.add(row)
        session.commit()
        return row.id


def test_rejected_total_recovers_through_separate_account_discussion_and_confirmation(runtime_env):
    _, database, _ = runtime_env
    old_id = existing_position(database)
    query = '내 보유 주식 목록 모두 저장해줘\nQGLD $48.25 84주\n가격은 평균 매입가야'
    rejected, _ = consult(runtime_env, 'original-new-lot', query, [data_command('update', 'holdings', query,
        selector={'symbol': 'NYSEARCA:QGLD'}, values={'quantity': '105', 'avg_cost': '48.25', 'currency': 'USD'})])
    assert rejected['result']['data_operations'][0]['status'] == 'needs_input'
    plain_consult(runtime_env, 'separate-account-discussion',
        '그러면 같은 ticker로 하나 더 저장하면 안되나? 계좌가 서로 다른거에 사놓은 거라서')
    reply = '그러면 그렇게 해줘'
    candidate = data_command('create', 'holdings', reply, command_index=0,
        values={'symbol': 'QGLD', 'quantity': '84', 'avg_cost': '48.25', 'currency': 'USD'})
    candidate['separate_position'] = True
    completed, _ = consult(runtime_env, 'approve-separate-lot', reply, [candidate])
    assert [op['status'] for op in completed['result']['data_operations']] == ['saved']
    with database.session() as session:
        rows = list(session.scalars(select(Holding).order_by(Holding.id)))
        assert len(rows) == 2
        old, new = rows
        assert (old.id, old.quantity, old.avg_cost, old.last_price) == (old_id, Decimal('21'), Decimal('45.15'), Decimal('39.86'))
        assert (new.symbol, new.quantity, new.avg_cost, new.last_price, new.account_id) == (
            'NYSEARCA:QGLD', Decimal('84'), Decimal('48.25'), None, None)
        assert session.scalar(select(LocalPosition).where(LocalPosition.holding_id == new.id)) is not None


def test_bare_ticker_gets_exchange_from_public_directory_not_model_guess(runtime_env, monkeypatch):
    _, database, _ = runtime_env
    seen = []
    def lookup(symbol, currency='USD'):
        seen.append((symbol, currency))
        return {'status': 'resolved', 'symbol': 'NASDAQ:QSTOCK', 'candidates': ['NASDAQ:QSTOCK'],
                'source': 'nasdaq_trader', 'as_of': '2026-10-24T00:00:00+00:00'}
    monkeypatch.setattr('app.modules.portfolio.symbol_directory.symbol_directory.resolve', lookup)
    query = '내 주식 QSTOCK 6주 평균 매입가 123달러로 저장해줘'
    run, _ = consult(runtime_env, 'directory-backed-position', query, [data_command('create', 'holdings', query,
        values={'symbol': 'NYSE:QSTOCK', 'quantity': '6', 'avg_cost': '123', 'currency': 'USD'})])
    assert run['result']['data_operations'][0]['status'] == 'saved'
    assert run['result']['data_operations'][0]['symbol_resolution']['source'] == 'nasdaq_trader'
    assert seen == [('QSTOCK', 'USD')]
    with database.session() as session:
        row = session.scalar(select(Holding))
        assert (row.symbol, row.quantity, row.avg_cost, row.last_price) == ('NASDAQ:QSTOCK', Decimal('6'), Decimal('123'), None)


def test_separate_account_intent_cannot_overwrite_existing_lot_when_model_omits_flag(runtime_env):
    _, database, _ = runtime_env
    old_id = existing_position(database)
    query = '다른 계좌의 QGLD 주식 6주를 평균 매입가 120달러로 별도 보유분으로 저장해줘'
    mistaken = data_command('update', 'holdings', query, selector={'symbol': 'QGLD'},
        values={'quantity': '6', 'avg_cost': '120', 'currency': 'USD'})
    completed, _ = consult(runtime_env, 'separate-intent-no-model-flag', query, [mistaken])
    assert completed['result']['data_operations'][0]['status'] == 'saved'
    with database.session() as session:
        old = session.get(Holding, old_id)
        assert (old.quantity, old.avg_cost) == (Decimal('21'), Decimal('45.15'))
        rows = list(session.scalars(select(Holding).where(Holding.id != old_id)))
        assert len(rows) == 1
        assert (rows[0].quantity, rows[0].avg_cost) == (Decimal('6'), Decimal('120'))


def test_confirmation_maps_the_pending_ticker_without_replaying_a_saved_sibling(runtime_env):
    _, database, _ = runtime_env
    existing_position(database)
    query = '내 보유 종목 모두 저장해줘\nQNEW $9 8주\nQGLD $48.25 84주\n가격은 평균 매입가야'
    consult(runtime_env, 'partial-list-separate-lot', query, [
        data_command('create', 'holdings', query, values={'symbol': 'QNEW', 'currency': 'USD', 'quantity': '8', 'avg_cost': '9'}),
        data_command('update', 'holdings', query, selector={'symbol': 'QGLD'}, values={'quantity': '105', 'avg_cost': '48.25', 'currency': 'USD'}),
    ])
    reply = '다른 계좌의 별도 보유분으로 그대로 저장해줘'
    candidate = data_command('create', 'holdings', reply, command_index=0,
        values={'symbol': 'QGLD', 'currency': 'USD', 'quantity': '84', 'avg_cost': '48.25'})
    result, _ = consult(runtime_env, 'pending-ticker-index-correction', reply, [candidate])
    assert [op['status'] for op in result['result']['data_operations']] == ['saved']
    with database.session() as session:
        assert len(list(session.scalars(select(Holding).where(Holding.symbol == 'QNEW')))) == 1
        assert len(list(session.scalars(select(Holding).where(Holding.symbol == 'NYSEARCA:QGLD')))) == 2
