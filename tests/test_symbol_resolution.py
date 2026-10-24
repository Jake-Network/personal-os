from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.database.model import AuditLog, Holding, LocalPosition
from app.modules.portfolio.holdings_manager import version
from app.modules.portfolio.symbol_resolution import qualify_positions


class Directory:
    def __init__(self, hook=None):
        self.calls = []
        self.hook = hook

    def resolve(self, symbol, currency='USD'):
        self.calls.append((symbol, currency))
        if self.hook:
            self.hook()
        return {'status': 'resolved', 'symbol': 'NASDAQ:' + symbol, 'candidates': ['NASDAQ:' + symbol],
                'source': 'nasdaq_trader', 'as_of': '2026-10-24T01:31:00+00:00'}


def position(session, *, symbol='SYNA', currency='USD', quote_mode='auto', account_id=None, suffix='1'):
    row = Holding(symbol=symbol, name='Synthetic holding', currency=currency, account_id=account_id,
                  quantity=Decimal('3'), avg_cost=Decimal('11.25'), last_price=Decimal('13.5'),
                  price_as_of=datetime(2026, 10, 23, tzinfo=UTC))
    session.add(row)
    session.flush()
    mapping = LocalPosition(position_id='synthetic-' + suffix, holding_id=row.id,
                            quote_mode=quote_mode, version=version(row))
    session.add(mapping)
    session.commit()
    return row, mapping


def test_existing_bare_position_is_qualified_without_repricing_or_merging(session):
    row, mapping = position(session)
    original = (row.quantity, row.avg_cost, row.last_price, row.price_as_of, row.account_id)
    def no_open_transaction():
        assert not session.in_transaction(), 'Directory network must run after the caller transaction is released'
    fake = Directory(hook=no_open_transaction)
    result = qualify_positions(session, directory=fake)
    session.refresh(row)
    session.refresh(mapping)
    assert row.symbol == 'NASDAQ:SYNA'
    assert (row.quantity, row.avg_cost, row.last_price, row.price_as_of, row.account_id) == original
    assert mapping.version == version(row)
    assert [item['status'] for item in result] == ['resolved']
    assert fake.calls == [('SYNA', 'USD')]
    audit = session.scalar(select(AuditLog).where(AuditLog.action == 'holding.symbol.resolve'))
    assert audit.detail['previous_symbol'] == 'SYNA'
    assert audit.detail['symbol'] == 'NASDAQ:SYNA'
    assert audit.detail['source'] == 'nasdaq_trader'
    assert 'quantity' not in audit.detail and 'avg_cost' not in audit.detail


def test_two_accounts_keep_separate_positions_but_reuse_one_public_lookup(session):
    from app.modules.database.model import Account
    from app.modules.finance.clock import local_today
    accounts = [Account(name=f'Synthetic account {n}', kind='brokerage_cash', currency='USD',
                        balance=Decimal('0'), balance_as_of=local_today()) for n in (1, 2)]
    session.add_all(accounts)
    session.commit()
    a, map_a = position(session, account_id=accounts[0].id, suffix='a')
    b, map_b = position(session, account_id=accounts[1].id, suffix='b')
    b.quantity, b.avg_cost = Decimal('7'), Decimal('17.5')
    map_b.version = version(b)
    session.commit()
    original = [(row.id, row.account_id, row.quantity, row.avg_cost) for row in (a, b)]
    fake = Directory()
    result = qualify_positions(session, directory=fake)
    assert [item['status'] for item in result] == ['resolved', 'resolved']
    assert fake.calls == [('SYNA', 'USD')]
    for row in (a, b):
        session.refresh(row)
    assert [(row.id, row.account_id, row.quantity, row.avg_cost) for row in (a, b)] == original
    assert a.symbol == b.symbol == 'NASDAQ:SYNA'
    assert map_a.position_id != map_b.position_id


def test_only_local_auto_usd_bare_positions_are_considered(session):
    position(session, symbol='NASDAQ:SYNA', suffix='qualified')
    position(session, currency='KRW', suffix='foreign')
    position(session, quote_mode='manual', suffix='manual')
    untracked = Holding(symbol='SYNB', currency='USD', quantity=2, avg_cost=3)
    session.add(untracked)
    session.commit()
    fake = Directory()
    assert qualify_positions(session, directory=fake) == []
    assert fake.calls == []
    assert session.scalar(select(AuditLog.id).where(AuditLog.action == 'holding.symbol.resolve')) is None


@pytest.mark.parametrize('status', ['ambiguous', 'not_found', 'unavailable', 'unsupported'])
def test_unresolved_lookup_never_changes_existing_identity(session, status):
    row, _ = position(session)
    class Unresolved:
        def resolve(self, *args):
            return {'status': status, 'symbol': None, 'candidates': [], 'source': 'nasdaq_trader'}
    result = qualify_positions(session, directory=Unresolved())
    assert result[0]['status'] == status
    session.refresh(row)
    assert row.symbol == 'SYNA'
    assert session.scalar(select(AuditLog.id).where(AuditLog.action == 'holding.symbol.resolve')) is None


@pytest.mark.parametrize('race', ['quantity', 'mapping', 'mode', 'account'])
def test_position_changed_during_public_lookup_is_skipped(session, race):
    from app.modules.database.model import Account
    from app.modules.finance.clock import local_today
    row, mapping = position(session)
    account = Account(name='Synthetic changed account', kind='brokerage_cash', currency='USD', balance=0,
                      balance_as_of=local_today())
    session.add(account)
    session.commit()
    key, target_account, position_id = row.id, account.id, mapping.position_id
    def change():
        with Session(session.get_bind()) as changing:
            if race == 'quantity':
                changing.execute(update(Holding).where(Holding.id == key).values(quantity=8))
            elif race == 'mapping':
                changing.execute(delete(LocalPosition).where(LocalPosition.position_id == position_id))
            elif race == 'mode':
                changing.execute(update(LocalPosition).where(LocalPosition.position_id == position_id).values(quote_mode='manual'))
            else:
                changing.execute(update(Holding).where(Holding.id == key).values(account_id=target_account))
            changing.commit()
    result = qualify_positions(session, directory=Directory(hook=change))
    assert result[0]['status'] == 'stale'
    session.refresh(row)
    assert row.symbol == 'SYNA'
    assert row.avg_cost == Decimal('11.25')
    assert session.scalar(select(AuditLog.id).where(AuditLog.action == 'holding.symbol.resolve')) is None


def test_lost_execution_authority_before_write_prevents_symbol_mutation(session):
    row, _ = position(session)
    calls = []
    def authority():
        calls.append(True)
        if len(calls) == 3:
            raise RuntimeError('synthetic lease revoked')
    with pytest.raises(RuntimeError, match='lease revoked'):
        qualify_positions(session, directory=Directory(), authorization_check=authority)
    session.refresh(row)
    assert row.symbol == 'SYNA'
    assert session.scalar(select(AuditLog.id).where(AuditLog.action == 'holding.symbol.resolve')) is None


def test_record_sharing_is_checked_for_advisor_but_not_local_finance(session):
    from app.modules.context.record_privacy import set_record_policy
    row, _ = position(session)
    set_record_policy(session, 'holdings', row.id, False)
    fake = Directory()
    blocked = qualify_positions(session, directory=fake, authorization_check=lambda: None)
    assert blocked[0]['status'] == 'sharing_excluded'
    assert fake.calls == []
    assert 'previous_symbol' not in blocked[0]
    local = qualify_positions(session, directory=fake)
    assert local[0]['status'] == 'resolved'
    session.refresh(row)
    assert row.symbol == 'NASDAQ:SYNA'


def test_category_sharing_revoked_during_lookup_prevents_advisor_update(session):
    from app.enums.context_category import Category
    from app.modules.context.privacy_manager import privacy_manager
    row, _ = position(session)
    def revoke():
        with Session(session.get_bind()) as changing:
            privacy_manager.set_excluded(changing, [Category.INVESTMENT])
    result = qualify_positions(session, directory=Directory(hook=revoke), authorization_check=lambda: None)
    assert result[0]['status'] == 'sharing_excluded'
    assert 'previous_symbol' not in result[0]
    session.refresh(row)
    assert row.symbol == 'SYNA'


def test_resolver_cannot_rename_ticker_or_invent_a_provider_source(session):
    row, _ = position(session)
    class WrongIdentity:
        def resolve(self, *args):
            return {'status': 'resolved', 'symbol': 'NASDAQ:SYNB', 'source': 'nasdaq_trader'}
    result = qualify_positions(session, directory=WrongIdentity())
    assert result[0]['status'] == 'unavailable'
    session.refresh(row)
    assert row.symbol == 'SYNA'


def test_final_write_authorization_failure_rolls_back_symbol_change(session):
    row, _ = position(session)
    fake = Directory()
    def write_guard():
        raise RuntimeError('synthetic final write lease revoked')
    with pytest.raises(RuntimeError, match='final write lease revoked'):
        qualify_positions(session, directory=fake, authorization_check=lambda: None,
                          write_authorization_check=write_guard)
    assert fake.calls == [('SYNA', 'USD')]
    assert not session.in_transaction()
    session.refresh(row)
    assert row.symbol == 'SYNA'
    assert session.scalar(select(AuditLog.id).where(AuditLog.action == 'holding.symbol.resolve')) is None


def test_final_run_fence_blocks_concurrent_cancellation_until_symbol_commit(session):
    from datetime import timedelta
    from uuid import uuid4
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from app.modules.advisor.runtime.persistence import RunRepository
    from app.modules.database.model import AdvisorConversation
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.database.model.base import utcnow

    row, _ = position(session)
    conversation = AdvisorConversation(title='Synthetic fenced lookup')
    session.add(conversation)
    session.flush()
    run_id = str(uuid4())
    session.add(AdvisorRun(id=run_id, conversation_id=conversation.id, request_id='synthetic-symbol-fence',
        status='running', input_payload={}, lease_owner='synthetic-owner', lease_generation=1,
        lease_until=utcnow() + timedelta(minutes=30)))
    session.commit()
    probes = []

    def lookup_guard():
        RunRepository(session).fence(run_id, 'synthetic-owner', 1)
        session.commit()

    def write_guard():
        RunRepository(session).fence(run_id, 'synthetic-owner', 1)

    def check_fence(_session, _context, _instances):
        if row not in session.dirty:
            return
        with Session(session.get_bind()) as cancelling:
            with pytest.raises(OperationalError, match='could not obtain lock'):
                cancelling.scalar(select(AdvisorRun).where(AdvisorRun.id == run_id).with_for_update(nowait=True))
        probes.append(True)

    event.listen(session, 'before_flush', check_fence)
    try:
        result = qualify_positions(session, directory=Directory(), authorization_check=lookup_guard,
                                   write_authorization_check=write_guard)
    finally:
        event.remove(session, 'before_flush', check_fence)
    assert result[0]['status'] == 'resolved'
    assert probes == [True]
    # Once the symbol and audit transaction commits, cancellation may claim the row.
    with Session(session.get_bind()) as cancelling:
        run = cancelling.scalar(select(AdvisorRun).where(AdvisorRun.id == run_id).with_for_update(nowait=True))
        run.status = 'cancel_requested'
        cancelling.commit()
    session.refresh(row)
    assert row.symbol == 'NASDAQ:SYNA'
