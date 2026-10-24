"""Same ticker positions preserve each account's independently entered cost basis."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.modules.advisor.data_commands import execute_commands
from app.modules.database.model import Account, AdvisorConversation, AdvisorMessage, AuditLog, Holding, LocalPosition


def holding(session, account_id=None):
    row = Holding(symbol='NYSEARCA:QAFUND', name='합성 기존 펀드', currency='USD',
                  quantity=Decimal('7'), avg_cost=Decimal('22.50'), last_price=Decimal('27.25'),
                  account_id=account_id)
    session.add(row)
    session.flush()
    session.add(LocalPosition(position_id=f'synthetic-existing-{row.id}', holding_id=row.id, quote_mode='auto', version='synthetic'))
    session.flush()
    return row


def source(session, query):
    conversation = AdvisorConversation(title='합성 계좌별 보유 기록')
    session.add(conversation)
    session.flush()
    message = AdvisorMessage(conversation_id=conversation.id, role='user', status='complete', content=query)
    session.add(message)
    session.flush()
    return dict(conversation_id=conversation.id, message_id=message.id, excluded=set())


def command(**values):
    return {'operation': 'create', 'resource': 'holdings', 'selector': {}, 'separate_position': True,
            'source_quote': 'QAFUND $31.25 3주를 다른 계좌의 별도 보유분으로 저장해줘',
            'values': {'symbol': 'QAFUND', 'quantity': '3', 'avg_cost': '31.25', 'currency': 'USD', **values}}


def test_explicit_other_account_keeps_same_ticker_positions_separate_without_requiring_account_name(session):
    existing = holding(session)
    pending = command()
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'saved', result
    rows = list(session.scalars(select(Holding).order_by(Holding.id)))
    assert len(rows) == 2
    assert (rows[0].quantity, rows[0].avg_cost, rows[0].last_price) == (Decimal('7'), Decimal('22.50'), Decimal('27.25'))
    assert (rows[1].symbol, rows[1].quantity, rows[1].avg_cost, rows[1].last_price, rows[1].account_id) == (
        'NYSEARCA:QAFUND', Decimal('3'), Decimal('31.25'), None, None)
    assert result['separate_position'] is True
    assert result['account_status'] == 'unspecified'
    mappings = list(session.scalars(select(LocalPosition).order_by(LocalPosition.holding_id)))
    assert len({mapping.position_id for mapping in mappings}) == 2
    assert len(list(session.scalars(select(Account)))) == 0, 'Do not manufacture a zero-balance account to store the position'


def test_model_flag_without_separate_account_user_authority_stays_pending(session):
    holding(session)
    pending = command()
    result = execute_commands(session, commands=[pending], **source(session, 'QAFUND $31.25 3주 기록해줘'))[0]
    assert result['status'] == 'needs_input'
    assert len(list(session.scalars(select(Holding)))) == 1


def test_other_account_authority_does_not_overwrite_explicitly_same_registered_account(session):
    account = Account(name='합성 증권 계좌', kind='brokerage_cash', currency='USD', balance=Decimal('0'), balance_as_of=date(2026, 10, 1))
    session.add(account)
    session.flush()
    holding(session, account.id)
    pending = command(account_id=account.id)
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'needs_input'
    assert len(list(session.scalars(select(Holding)))) == 1


def test_existing_and_new_registered_accounts_keep_their_positions_independent(session):
    accounts = [Account(name=f'합성 증권 계좌 {number}', kind='brokerage_cash', currency='USD',
        balance=Decimal('0'), balance_as_of=date(2026, 10, 1)) for number in (1, 2)]
    session.add_all(accounts)
    session.flush()
    holding(session, accounts[0].id)
    pending = command(account_id=accounts[1].id)
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'saved'
    assert result['record']['account_id'] == accounts[1].id
    assert len(list(session.scalars(select(Holding)))) == 2


def test_separate_position_receipt_replay_and_duplicate_batch_do_not_create_more_lots(session):
    holding(session)
    pending = command()
    args = source(session, pending['source_quote'])
    batch = [{**pending, 'command_index': 0}, {**pending, 'command_index': 1}]
    first = execute_commands(session, commands=batch, **args)
    second = execute_commands(session, commands=batch, **args)
    assert all(item['status'] == 'saved' for item in first + second)
    assert len({item['record_id'] for item in first + second}) == 1
    assert len(list(session.scalars(select(Holding)))) == 2


def test_pending_confirmation_uses_server_validated_original_instruction(session):
    holding(session)
    pending = command()
    original = pending['source_quote']
    pending['source_quote'] = '응 그렇게 해줘'
    result = execute_commands(session, commands=[pending], authorized_query=original + '\n사용자 확인: 응 그렇게 해줘',
                              **source(session, '응 그렇게 해줘'))[0]
    assert result['status'] == 'saved'
    assert len(list(session.scalars(select(Holding)))) == 2


def test_separate_position_update_cannot_overwrite_the_old_cost_basis(session):
    old = holding(session)
    pending = {**command(), 'operation': 'update', 'selector': {'id': old.id}}
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'needs_input'
    assert (old.quantity, old.avg_cost, old.last_price) == (Decimal('7'), Decimal('22.50'), Decimal('27.25'))
    assert len(list(session.scalars(select(Holding)))) == 1


def test_quoted_separate_account_words_and_non_boolean_model_flags_do_not_grant_authority(session):
    holding(session)
    pending = command()
    quoted = '친구가 "다른 계좌의 별도 보유분으로 저장해줘"라고 말했어. QAFUND 3주 기록해줘'
    result = execute_commands(session, commands=[pending], **source(session, quoted))[0]
    assert result['status'] == 'needs_input'
    pending['separate_position'] = 'true'
    result = execute_commands(session, commands=[pending], **source(session, 'QAFUND 3주 기록해줘'))[0]
    assert result['status'] == 'needs_input'
    assert len(list(session.scalars(select(Holding)))) == 1


def test_caller_rollback_removes_the_new_lot_and_its_receipt(session):
    holding(session)
    session.commit()
    pending = command()
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'saved'
    session.rollback()
    assert len(list(session.scalars(select(Holding)))) == 1
    assert not list(session.scalars(select(AuditLog).where(AuditLog.action == 'advisor.data_command')))


def test_changed_batch_index_does_not_borrow_another_positions_cached_receipt(session):
    holding(session)
    first = {**command(name='합성 별도 보유 A'), 'command_index': 0}
    second = {**command(name='합성 별도 보유 B', quantity='5'), 'command_index': 1}
    args = source(session, 'QAFUND를 다른 계좌별로 A는 3주, B는 5주 평균 단가 $31.25로 각각 저장해줘')
    result = execute_commands(session, commands=[first, second], **args)
    assert all(item['status'] == 'saved' for item in result)
    changed = execute_commands(session, commands=[first, {**first, 'command_index': 1}], **args)
    assert changed[1]['status'] == 'failed'
    assert len(list(session.scalars(select(Holding)))) == 3


def test_original_save_and_later_other_account_clarification_authorize_only_a_separate_new_position(session):
    holding(session)
    pending = command()
    clarification = '그러면 같은 ticker로 하나 더 저장하면 안되나? 계좌가 서로 다른거에 사놓은 거라서'
    pending['source_quote'] = clarification
    original = 'QAFUND $31.25 3주 저장해줘'
    result = execute_commands(session, commands=[pending], authorized_query=original + '\n사용자 확인: ' + clarification,
                              **source(session, clarification))[0]
    assert result['status'] == 'saved'
    assert len(list(session.scalars(select(Holding)))) == 2


def test_explicit_separate_account_request_blocks_update_when_model_omits_the_flag(session):
    old = holding(session)
    pending = {**command(), 'operation': 'update', 'selector': {'id': old.id}}
    pending.pop('separate_position')
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'needs_input'
    assert (old.quantity, old.avg_cost, old.last_price) == (Decimal('7'), Decimal('22.50'), Decimal('27.25'))
    assert len(list(session.scalars(select(Holding)))) == 1


def test_explicit_separate_account_create_does_not_depend_on_a_model_flag(session):
    holding(session)
    pending = command()
    pending.pop('separate_position')
    result = execute_commands(session, commands=[pending], **source(session, pending['source_quote']))[0]
    assert result['status'] == 'saved'
    assert result['separate_position'] is True
    assert len(list(session.scalars(select(Holding)))) == 2


def test_cosmetic_names_and_resolution_metadata_cannot_duplicate_the_same_separate_position(session):
    holding(session)
    first = {**command(name='합성 펀드'), 'command_index': 0,
             'symbol_resolution': {'state': 'matched'}}
    second = {**command(name='합성 펀드 별도 계좌', symbol='NYSEARCA:QAFUND', quantity=3, avg_cost='31.2500'),
              'command_index': 1, 'symbol_resolution': {'state': 'known_local'}}
    result = execute_commands(session, commands=[first, second], **source(session, first['source_quote']))
    assert [item['status'] for item in result] == ['saved', 'saved']
    assert len({item['record_id'] for item in result}) == 1
    assert len(list(session.scalars(select(Holding)))) == 2
