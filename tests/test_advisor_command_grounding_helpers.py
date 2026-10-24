import pytest

from app.modules.advisor.commands.grounding import legacy_command_grounded


def holding(symbol='QAFIRST', quantity=3, avg_cost='12.34', **extra):
    return {'operation': 'create', 'resource': 'holdings', 'selector': {},
        'values': {'symbol': symbol, 'quantity': quantity, 'avg_cost': avg_cost, 'currency': 'USD', **extra}}


BATCH = '내 주식\nQAFIRST $12.34 3주\nQASECOND $56.78 5주\n가격은 평균 매입가야. 전부 저장해줘'


def test_legacy_holding_requires_its_exact_original_symbol_and_row_values():
    assert legacy_command_grounded(BATCH, holding())
    assert legacy_command_grounded(BATCH, holding('NASDAQ:QAFIRST'))
    assert legacy_command_grounded(BATCH.replace('\n', ', '), holding('QASECOND', 5, '56.78'))
    assert not legacy_command_grounded(BATCH, holding('QAINVENTED'))
    assert not legacy_command_grounded(BATCH, holding('QAFIRST', 5, '12.34'))
    assert not legacy_command_grounded(BATCH, holding('QAFIRST', 3, '56.78'))
    assert not legacy_command_grounded(BATCH, holding('QAFIRST', '12.34', 3))


def test_legacy_holdings_do_not_borrow_quoted_or_hypothetical_data():
    assert not legacy_command_grounded('친구가 "QAFIRST $12.34 3주"라고 했어. 평균 매입가야. 저장해줘', holding())
    assert not legacy_command_grounded('만약 QAFIRST $12.34 3주 있다면 저장해줘', holding())
    assert not legacy_command_grounded(BATCH.replace('QAFIRST', 'OTHERQAFIRST'), holding())
    assert not legacy_command_grounded(BATCH.replace('QAFIRST', 'QAFIRSTOTHER'), holding())
    assert not legacy_command_grounded(BATCH.replace('QAFIRST', 'NASDAQ:QAFIRST'), holding('NYSE:QAFIRST'))


def test_legacy_holding_cost_needs_average_price_meaning_and_cannot_be_current_quote():
    assert not legacy_command_grounded(BATCH.replace('평균 매입가', '현재 시세'), holding())
    assert legacy_command_grounded('내 QAFIRST 3주 있고 평균 매입가는 12.34달러야. 저장해줘', holding())
    assert legacy_command_grounded('내 QAFIRST 3주 있고 평균 매입가는 12.34야. 저장해줘', holding())
    assert not legacy_command_grounded('내 QAFIRST 3주 있고 평균 매입가는 12.34야. 저장해줘', holding(avg_cost=3))


def test_legacy_addition_retains_original_quantity_after_server_total_conversion():
    command = {'operation': 'update', 'resource': 'holdings', 'selector': {'symbol': 'QAFIRST'},
        'values': {'delta': 5, 'avg_cost': '132.21', 'currency': 'USD'}}
    query = '내 QAFIRST 5주 더 있어. 평균 매입가는 132.21달러야. 추가로 저장해줘'
    assert legacy_command_grounded(query, command)
    assert not legacy_command_grounded(query, {**command, 'values': {**command['values'], 'delta': 12}})
    assert not legacy_command_grounded(query, {**command, 'values': {**command['values'], 'delta': -5}})


def test_legacy_currency_and_ids_cannot_be_invented():
    assert not legacy_command_grounded(BATCH, holding(currency='KRW'))
    assert not legacy_command_grounded(BATCH, holding(account_id=1))
    changed = holding()
    changed['selector'] = {'id': 123}
    assert not legacy_command_grounded(BATCH, changed)
    assert not legacy_command_grounded(BATCH + '\nQAFIRST $12.34 3주', holding())


def account(name='합성 보류 통장', balance='3000000', **extra):
    return {'operation': 'create', 'resource': 'accounts', 'selector': {},
        'values': {'name': name, 'kind': 'checking', 'currency': 'KRW', 'balance': balance, **extra}}


def test_legacy_named_account_keeps_meaningful_identity_when_account_type_is_structured():
    query = '합성 보류 입출금 통장에 300만원 있어. 새 계좌로 저장해줘'
    assert legacy_command_grounded(query, account())
    assert not legacy_command_grounded(query, account(name='다른 사람 통장'))
    assert not legacy_command_grounded(query, account(name='통장'))
    assert not legacy_command_grounded(query, account(balance='4000000'))
    assert not legacy_command_grounded(query, account(currency='USD'))


def test_legacy_account_balance_cannot_come_from_another_named_account():
    query = '합성 보류 입출금 통장에 300만원, 합성 여유 입출금 통장에 500만원 있어. 둘 다 저장해줘'
    assert legacy_command_grounded(query, account())
    assert not legacy_command_grounded(query, account(balance='5000000'))
    assert legacy_command_grounded(query, account(name='합성 여유 통장', balance='5000000'))


def test_legacy_account_kind_and_liquidity_cannot_be_invented_on_bare_assent():
    query = '합성 보류 입출금 통장에 300만원 있어. 저장해줘'
    assert legacy_command_grounded(query, account())
    assert not legacy_command_grounded(query, account(kind='pension'))
    assert not legacy_command_grounded(query, account(is_liquid=False))
    assert not legacy_command_grounded(query, account(is_liquid=True))
    assert legacy_command_grounded(query.replace('300만원 있어', '300만원 있고 생활비로 사용 가능'), account(is_liquid=True))
    assert legacy_command_grounded(query.replace('300만원 있어', '300만원 있고 생활비로 사용 불가'), account(is_liquid=False))


def test_malformed_legacy_symbol_is_rejected_without_an_exception():
    command = holding()
    command['selector']['symbol'] = 123
    assert not legacy_command_grounded(BATCH, command)


@pytest.mark.parametrize('resource,identity,field,value', [
    ('other-assets', 'name', 'value', '1200000'),
    ('planned-expenses', 'name', 'amount', '1200000'),
    ('liabilities', 'name', 'balance', '1200000'),
])
def test_other_named_financial_resources_retain_their_own_local_amount(resource, identity, field, value):
    query = '합성 항목 120만원, 다른 항목 340만원 있어. 기록해줘'
    command = {'operation': 'create', 'resource': resource, 'selector': {},
        'values': {identity: '합성 항목', field: value, 'currency': 'KRW'}}
    assert legacy_command_grounded(query, command)
    assert not legacy_command_grounded(query, {**command, 'values': {**command['values'], field: '3400000'}})


def test_unknown_or_unidentifiable_legacy_resource_fails_closed():
    assert not legacy_command_grounded('저장해줘', {'operation': 'create', 'resource': 'unknown', 'values': {}})
    assert not legacy_command_grounded('내 운동 45분 기록해줘', {'operation': 'create', 'resource': 'workout-logs',
        'values': {'activity': '모델이 지어낸 운동', 'duration_seconds': 2700}})


def test_legacy_symbol_aliases_cannot_change_or_conflict_with_the_original_target():
    query = '내 보유 주식 QAFIRST $12.34 3주 평균 매입가로 저장해줘'
    command = {'operation': 'update', 'resource': 'holdings', 'selector': {'ticker': 'QAFIRST'},
        'values': {'ticker': 'QAINVENTED', 'quantity': '3', 'avg_cost': '12.34', 'currency': 'USD'}}
    assert not legacy_command_grounded(query, command)
    assert not legacy_command_grounded(query, {**command,
        'selector': {'ticker': 'QAFIRST', 'symbol': 'QAINVENTED'}})
    assert not legacy_command_grounded(query, {**command,
        'values': {**command['values'], 'ticker': 'QAFIRST', 'symbol': 'QAINVENTED'}})
    assert not legacy_command_grounded(query, {**command,
        'selector': {'symbol': 'QAFIRST'}})
    assert not legacy_command_grounded(query.replace('QAFIRST', 'NASDAQ:QAFIRST'), {**command,
        'values': {**command['values'], 'ticker': 'NYSE:QAFIRST'}})
    assert legacy_command_grounded(query, {**command,
        'values': {**command['values'], 'ticker': 'QAFIRST'}})
