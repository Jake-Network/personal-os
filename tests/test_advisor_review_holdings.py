"""Review regressions: hidden positions do not affect creates; legacy fractions survive deltas."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.advisor.commands.execution import execute_commands
from app.modules.context.record_privacy import set_record_policy
from app.modules.database.model import Account, AdvisorConversation, AdvisorMessage, Holding, ManualValueChange
from test_advisor_runtime_execution import runtime_env  # noqa: F401


def source(session):
    conversation = AdvisorConversation(title='합성 검토 상담')
    session.add(conversation)
    session.flush()
    message = AdvisorMessage(conversation_id=conversation.id, role='user', content='합성 보유 종목 기록해줘')
    session.add(message)
    session.flush()
    return {'conversation_id': conversation.id, 'message_id': message.id, 'excluded': set()}


def create_command():
    return {'operation': 'create', 'resource': 'holdings',
            'values': {'symbol': 'NASDAQ:QAPRIV', 'currency': 'USD', 'quantity': 3, 'avg_cost': '12.50'}}


@pytest.mark.parametrize('hide_account', [False, True])
def test_hidden_position_or_its_account_does_not_disclose_or_block_create(session, hide_account):
    account = Account(name='합성 비공유 계좌', kind='brokerage_cash', currency='USD',
                      balance=Decimal('0'), balance_as_of=date(2026, 10, 1))
    session.add(account)
    session.flush()
    private = Holding(symbol='NASDAQ:QAPRIV', name='합성 비공유 보유명', currency='USD',
                      account_id=account.id, quantity=Decimal('17'), avg_cost=Decimal('99'))
    session.add(private)
    session.flush()
    set_record_policy(session, 'accounts' if hide_account else 'holdings', account.id if hide_account else private.id, False)
    result = execute_commands(session, commands=[create_command()], **source(session))[0]
    assert result['status'] == 'saved'
    assert '기존 보유' not in result['message']
    assert 'candidates' not in result
    assert '합성 비공유' not in str(result)
    assert result['record_id'] != private.id
    assert (private.quantity, private.avg_cost) == (Decimal('17'), Decimal('99'))
    assert len(list(session.scalars(select(Holding)))) == 2


def test_visible_duplicate_candidates_exclude_private_holdings_and_accounts(session):
    visible = Holding(symbol='NASDAQ:QAPRIV', name='합성 공유 보유분', currency='USD', quantity=Decimal('2'))
    hidden = Holding(symbol='NASDAQ:QAPRIV', name='합성 숨긴 보유분', currency='USD', quantity=Decimal('47'))
    session.add_all([visible, hidden])
    session.flush()
    set_record_policy(session, 'holdings', hidden.id, False)
    result = execute_commands(session, commands=[create_command()], **source(session))[0]
    assert result['status'] == 'needs_input'
    assert [candidate['id'] for candidate in result['candidates']] == [visible.id]
    assert '합성 숨긴 보유분' not in str(result)


def test_integer_delta_preserves_legacy_fractional_quantity_history_and_replay(session):
    row = Holding(symbol='NYSEARCA:QAFRAC', currency='USD', quantity=Decimal('1.5'), avg_cost=Decimal('18.25'))
    session.add(row)
    session.flush()
    command = {'operation': 'update', 'resource': 'holdings', 'selector': {'id': row.id}, 'values': {'delta': '1'}}
    args = source(session)
    first = execute_commands(session, commands=[command], **args)[0]
    assert first['status'] == 'saved'
    assert row.quantity == Decimal('2.5')
    assert first['record']['quantity'] == '2.5'
    replay = execute_commands(session, commands=[command], **args)[0]
    assert replay['record_id'] == row.id and row.quantity == Decimal('2.5')
    changes = list(session.scalars(select(ManualValueChange).where(ManualValueChange.record_id == row.id,
        ManualValueChange.field == 'quantity').order_by(ManualValueChange.id)))
    assert [(item.old_value, item.new_value) for item in changes] == [(None, Decimal('1.5')), (Decimal('1.5'), Decimal('2.5'))]
    assert row.avg_cost == Decimal('18.25')


@pytest.mark.parametrize('initial,delta,expected', [
    ('1.000000000001', '1', '2.000000000001'),
    ('2.5', '-2', '0.5'),
    ('99999999999999999998.5', '1', '99999999999999999999.5'),
])
def test_legacy_fractional_integer_deltas_remain_exact(session, initial, delta, expected):
    row = Holding(symbol='NYSEARCA:QAFRAC', currency='USD', quantity=Decimal(initial))
    session.add(row)
    session.flush()
    result = execute_commands(session, commands=[{'operation': 'update', 'resource': 'holdings',
        'selector': {'id': row.id}, 'values': {'delta': delta}}], **source(session))[0]
    assert result['status'] == 'saved'
    assert row.quantity == Decimal(expected)


@pytest.mark.parametrize('initial,delta', [('0.5', '-1'), ('99999999999999999999.5', '1'), ('1.5', '0.5'), ('1.5', 'NaN')])
def test_invalid_fractional_delta_does_not_mutate_legacy_quantity(session, initial, delta):
    row = Holding(symbol='NYSEARCA:QAFRAC', currency='USD', quantity=Decimal(initial))
    session.add(row)
    session.flush()
    result = execute_commands(session, commands=[{'operation': 'update', 'resource': 'holdings',
        'selector': {'id': row.id}, 'values': {'delta': delta}}], **source(session))[0]
    assert result['status'] == 'needs_input'
    assert row.quantity == Decimal(initial)


@pytest.mark.parametrize('operation', ['create', 'update'])
def test_new_or_absolute_fractional_input_still_requires_whole_quantity(session, operation):
    row = Holding(symbol='NYSEARCA:QAFRAC', currency='USD', quantity=Decimal('1.5'))
    session.add(row)
    session.flush()
    command = {'operation': operation, 'resource': 'holdings', 'selector': {'id': row.id} if operation == 'update' else {},
        'values': {'quantity': '2.5'} if operation == 'update' else {'symbol': 'NASDAQ:QANEW', 'currency': 'USD', 'quantity': '2.5'}}
    result = execute_commands(session, commands=[command], **source(session))[0]
    assert result['status'] == 'needs_input'
    assert row.quantity == Decimal('1.5')


@pytest.mark.parametrize('qualified_source', [False, True])
def test_hidden_same_ticker_never_reaches_the_final_model_payload(runtime_env, qualified_source):
    import json
    from test_advisor_runtime_execution import FINAL, finish

    client, database, provider = runtime_env
    with database.session() as session:
        private = Holding(symbol='NASDAQ:QAPRIV', name='합성 비공유 존재 표식', currency='USD',
                          quantity=Decimal('17'), avg_cost=Decimal('99'))
        session.add(private)
        session.flush()
        set_record_policy(session, 'holdings', private.id, False)
    ticker = 'NASDAQ:QAPRIV' if qualified_source else 'QAPRIV'
    query = f'내 주식 {ticker} 3주 평균 매입가 12.50달러로 저장해줘'
    provider.replies.extend([{'commands': [{**create_command(), 'selector': {}, 'source_quote': query}]}, FINAL])
    response = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'hidden-existing-position-create', 'message': query, 'depth': 'auto'})
    assert response.status_code == 201
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run['status'] == 'completed', run
    assert run['result']['data_operations'][0]['status'] == 'saved', run['result']['data_operations'][0]['message']
    outbound = json.dumps([{'instructions': item.instructions, 'input': item.input} for item in provider.requests], ensure_ascii=False)
    assert '합성 비공유 존재 표식' not in outbound
    assert '기존 보유 기록이 있습니다.' not in outbound


@pytest.mark.parametrize('requested_symbol', ['NASDAQ:QAPRIV', 'QAPRIV'])
@pytest.mark.parametrize('hidden_count', [0, 101])
def test_private_prefix_cannot_hide_a_later_visible_duplicate(session, requested_symbol, hidden_count):
    from app.modules.context.record_privacy import KEY
    from app.modules.crud import app_setting_handler

    hidden = [Holding(symbol='NASDAQ:QAPRIV', currency='USD', quantity=Decimal('17')) for _ in range(hidden_count)]
    session.add_all(hidden)
    session.flush()
    visible = Holding(symbol='NASDAQ:QAPRIV', name='합성 공유 보유분', currency='USD', quantity=Decimal('2'))
    session.add(visible)
    session.flush()
    app_setting_handler.set_value(session, KEY, {'holdings': [str(row.id) for row in hidden]})
    result = execute_commands(session, commands=[{**create_command(), 'values': {
        **create_command()['values'], 'symbol': requested_symbol}}], **source(session))[0]
    assert result['status'] == 'needs_input'
    assert [item['id'] for item in result['candidates']] == [visible.id]
    assert len(list(session.scalars(select(Holding)))) == hidden_count + 1


def test_visible_identity_after_private_prefix_is_used_for_a_different_account(session):
    from app.modules.context.record_privacy import KEY
    from app.modules.crud import app_setting_handler

    hidden = [Holding(symbol='NASDAQ:QAPRIV', currency='USD', quantity=Decimal('17')) for _ in range(101)]
    session.add_all(hidden)
    session.flush()
    account = Account(name='합성 새 증권 계좌', kind='brokerage_cash', currency='USD',
                      balance=Decimal('0'), balance_as_of=date(2026, 10, 1))
    visible = Holding(symbol='NYSEARCA:QAPRIV', name='합성 공유 종목', currency='USD', quantity=Decimal('2'))
    session.add_all([account, visible])
    session.flush()
    app_setting_handler.set_value(session, KEY, {'holdings': [str(row.id) for row in hidden]})
    result = execute_commands(session, commands=[{'operation': 'create', 'resource': 'holdings',
        'values': {'symbol': 'QAPRIV', 'account_id': account.id, 'quantity': 3}}], **source(session))[0]
    assert result['status'] == 'saved'
    assert (result['record']['symbol'], result['record']['currency']) == ('NYSEARCA:QAPRIV', 'USD')
