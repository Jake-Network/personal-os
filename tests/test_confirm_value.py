from datetime import timedelta
from decimal import Decimal

from app.modules.finance.clock import local_today


def test_confirm_preserves_money_and_rejects_stale_version(client):
    body = {"name": "합성", "kind": "checking", "balance": "123.4567",
            "balance_as_of": (local_today() - timedelta(days=50)).isoformat()}
    created = client.post('/api/data/accounts', json=body).json()
    assert created['balance_stale'] is True
    confirmed = client.post(f"/api/data/accounts/{created['id']}/confirm-value",
                            json={"expected_version": created['version']})
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()
    assert Decimal(data['balance']) == Decimal('123.4567')
    assert data['balance_as_of'] == local_today().isoformat()
    assert data['balance_stale'] is False
    assert client.post(f"/api/data/accounts/{created['id']}/confirm-value", json={"expected_version": created['version']}).status_code == 409
    history_url = f"/api/data/accounts/{created['id']}/history"
    count = len(client.get(history_url).json())
    assert client.post(f"/api/data/accounts/{created['id']}/confirm-value", json={"expected_version": data['version']}).status_code == 200
    assert len(client.get(history_url).json()) == count


def test_other_financial_values_keep_history(client):
    for resource, amount_field, date_field, kind in (
        ('liabilities', 'balance', 'balance_as_of', 'credit'),
        ('other-assets', 'value', 'value_as_of', 'other'),
    ):
        body = {'name': '합성', 'kind': kind, amount_field: '123.4567',
                date_field: (local_today() - timedelta(days=50)).isoformat()}
        created = client.post(f'/api/data/{resource}', json=body).json()
        response = client.post(f"/api/data/{resource}/{created['id']}/confirm-value",
                               json={'expected_version': created['version']})
        assert response.status_code == 200, response.text
        assert Decimal(response.json()[amount_field]) == Decimal('123.4567')
        history = client.get(f"/api/data/{resource}/{created['id']}/history").json()
        assert len(history) == 2
        assert Decimal(history[0]['new_value']) == Decimal('123.4567')


def test_confirmation_rolls_back_when_history_fails(client, session, monkeypatch):
    from app.modules.database.model import Account
    from app.modules.finance.value_history_manager import value_history_manager
    from app.modules.personal_data.personal_data_manager import personal_data_manager, RESOURCES
    old_date = local_today() - timedelta(days=50)
    obj = Account(name='합성', kind='cash', balance=Decimal('123.4567'), balance_as_of=old_date)
    session.add(obj)
    session.commit()
    item_id, version = obj.id, obj.updated_at
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic history failure')
    monkeypatch.setattr(value_history_manager, 'record', fail)
    import pytest
    with pytest.raises(RuntimeError):
        personal_data_manager.confirm_value(session, 'accounts', RESOURCES['accounts'], item_id, version)
    session.rollback()
    session.expire_all()
    assert session.get(Account, item_id).balance_as_of == old_date
    assert session.get(Account, item_id).updated_at == version


def test_debt_absence_requires_explicit_coverage_confirmation(session):
    from datetime import UTC, datetime
    from app.enums.context_category import Category
    from app.modules.context.context_tool_manager import get_accounts_summary
    from app.modules.context.types import ToolContext
    from app.modules.database.model import Liability, LocalFinanceCoverage
    ctx = ToolContext(session=session, now=datetime.now(UTC), allowed=frozenset({Category.FINANCIAL}))
    def flags():
        return {flag['code'] for flag in get_accounts_summary(ctx).flags}
    assert 'no_liabilities_recorded' in flags()
    session.add(LocalFinanceCoverage(id=1, kinds=['liability']))
    session.flush()
    assert 'no_liabilities_recorded' not in flags()
    session.get(LocalFinanceCoverage, 1).kinds = []
    session.add(Liability(name='합성 부채', kind='credit', balance=Decimal('10'), balance_as_of=local_today()))
    session.flush()
    assert 'no_liabilities_recorded' not in flags()


def test_confirmation_after_other_tab_edit_never_reverts_balance(client):
    body = {'name': '합성', 'kind': 'cash', 'balance': '12.3456',
            'balance_as_of': (local_today() - timedelta(days=50)).isoformat()}
    original = client.post('/api/data/accounts', json=body).json()
    body['balance'] = '98.7654'
    edited = client.put(f"/api/data/accounts/{original['id']}", json=body).json()
    response = client.post(f"/api/data/accounts/{original['id']}/confirm-value",
                           json={'expected_version': original['version']})
    assert response.status_code == 409
    latest = client.get('/api/data/accounts').json()[0]
    assert Decimal(latest['balance']) == Decimal('98.7654')
    assert latest['version'] == edited['version']


def test_confirmation_uses_app_calendar_date(client, monkeypatch):
    from datetime import UTC, datetime
    from app.modules.finance import clock
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 20, 16, 30, tzinfo=UTC).astimezone(tz)
    from types import SimpleNamespace
    monkeypatch.setattr(clock, 'settings', SimpleNamespace(timezone='Asia/Seoul'))
    monkeypatch.setattr(clock, 'datetime', FrozenClock)
    row = client.post('/api/data/accounts', json={'name': '합성', 'kind': 'cash', 'balance': '1',
                                                'balance_as_of': '2026-09-01'}).json()
    response = client.post(f"/api/data/accounts/{row['id']}/confirm-value", json={'expected_version': row['version']})
    assert response.status_code == 200
    assert response.json()['balance_as_of'] == '2026-10-21'


def test_two_sessions_confirm_once_without_losing_amount_or_history(client, session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    from app.modules.database import db
    from app.modules.database.model import Account, ManualValueChange
    from app.modules.personal_data.personal_data_manager import personal_data_manager, RESOURCES
    created = client.post('/api/data/accounts', json={
        'name': '합성 경합', 'kind': 'cash', 'balance': '123.4567',
        'balance_as_of': (local_today() - timedelta(days=50)).isoformat(),
    }).json()
    barrier = Barrier(2)
    def confirm():
        with db.session() as concurrent:
            account = concurrent.get(Account, created['id'])
            version = account.updated_at
            barrier.wait(timeout=10)
            try:
                personal_data_manager.confirm_value(concurrent, 'accounts', RESOURCES['accounts'], account.id, version)
                return 'confirmed'
            except ValueError:
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: confirm(), range(2)))
    assert sorted(outcomes) == ['confirmed', 'conflict']
    session.expire_all()
    account = session.get(Account, created['id'])
    assert account.balance == Decimal('123.4567')
    assert account.balance_as_of == local_today()
    history = list(session.scalars(select(ManualValueChange).where(
        ManualValueChange.table_name == 'accounts', ManualValueChange.record_id == account.id)))
    assert len(history) == 2
    assert {row.change_kind for row in history} == {'create', 'update'}
