"""Ledger changes reach the real advisor worker and share the dashboard's calculations."""

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.modules.context.record_privacy import set_record_policy
from app.modules.dashboard.dashboard_manager import dashboard_manager
from app.modules.database.model import Account, CashflowEntry, ContextSnapshot, FinancialTransaction
from app.router import personal_data_router
from test_advisor_runtime_execution import FINAL, finish, runtime_env  # noqa: F401


def previous_months():
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    end = today.replace(day=1)
    months = []
    for _ in range(3):
        end = (end - timedelta(days=1)).replace(day=1)
        months.append(end.replace(day=5))
    return months


def consult(env, request_id, *, reply=FINAL, **options):
    client, database, provider = env
    provider.replies.append(reply)
    offset = len(provider.requests)
    response = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': request_id, 'message': '기록된 수입과 지출을 요약해줘',
        'depth': 'auto', **options,
    })
    assert response.status_code == 201, response.text
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run['status'] == 'completed', run
    assert len(provider.requests) == offset + 1
    request = provider.requests[-1]
    package = next(item['content'] for item in request.input
                   if item['role'] == 'developer' and item['content'].startswith('Context Package'))
    return json.loads(package.split('\n', 1)[1]), request


def test_unified_cashflow_categories_and_reversal_provenance_reach_model(runtime_env):
    _, database, _ = runtime_env
    zone = ZoneInfo(settings.timezone)
    days = previous_months()
    with database.session() as session:
        for index, day in enumerate(days):
            session.add(CashflowEntry(occurred_on=day, kind='expense', amount=Decimal('1000.11'),
                                     category='식비'))
            session.add(FinancialTransaction(request_id=f'fee-{index}', kind='fee',
                occurred_at=datetime.combine(day, time(12), zone),
                payload={'amount': '200.22', 'currency': 'KRW', 'category': '식비'}))
        cancelled = FinancialTransaction(request_id='cancelled-expense', kind='expense',
            occurred_at=datetime.combine(days[0], time(12), zone),
            payload={'amount': '99000', 'currency': 'KRW', 'category': '취소분류'})
        session.add(cancelled)
        session.flush()
        reversal = FinancialTransaction(request_id='outside-month-reversal', kind='reversal',
            occurred_at=datetime.now(UTC), reverses_id=cancelled.id,
            payload={'amount': '99000', 'currency': 'KRW'})
        session.add(reversal)
        session.add(CashflowEntry(occurred_on=days[0], kind='expense', amount=Decimal('88.88'),
                                 currency='USD', category='외화분류'))
        session.commit()
        cancelled_id, reversal_id = cancelled.id, reversal.id

    package, _ = consult(runtime_env, 'unified-cashflow')
    summary = package['data']['get_cashflow_summary']
    assert summary['monthly_expense']['monthly_average'] == '1200.33'
    assert summary['expense_by_category_12m'] == {'식비': '3600.99'}
    assert any(flag['code'] == 'cashflow_foreign_currency_ignored'
               for flag in package['data_quality_flags'])
    with database.session() as session:
        dashboard = dashboard_manager.summary(session)
        assert dashboard['data']['get_cashflow_summary'] == summary
        snapshot = session.get(ContextSnapshot, package['context_snapshot_id'])
        refs = {(ref['table'], ref['id']) for ref in snapshot.record_references if ref.get('id') is not None}
        assert ('cashflow_entries', 1) in refs
        assert ('financial_transactions', 1) in refs
        assert ('financial_transactions', cancelled_id) in refs
        assert ('financial_transactions', reversal_id) in refs


def test_cashflow_crud_refreshes_model_and_dashboard_without_changing_account(runtime_env):
    client, database, _ = runtime_env
    client.app.include_router(personal_data_router.router)
    days = previous_months()
    with database.session() as session:
        session.add(Account(name='가계부와 별도인 합성 계좌', kind='checking', currency='KRW',
                            balance=Decimal('1000000'), balance_as_of=date.today(), is_liquid=True))
        for day in days[1:]:
            session.add(CashflowEntry(occurred_on=day, kind='expense', amount=Decimal('100'), category='식비'))
        session.commit()
    body = {'occurred_on': days[0].isoformat(), 'kind': 'expense', 'amount': '100.01',
            'currency': 'KRW', 'category': '식비', 'description': '합성 기록'}
    created = client.post('/api/data/cashflow-entries', json=body)
    assert created.status_code == 201, created.text
    item_id = created.json()['id']
    first, _ = consult(runtime_env, 'before-edit')
    assert first['data']['get_cashflow_summary']['monthly_expense']['monthly_average'] == '100.00'

    edited = client.put(f'/api/data/cashflow-entries/{item_id}', json={**body, 'amount': '400.04'})
    assert edited.status_code == 200, edited.text
    latest, _ = consult(runtime_env, 'after-edit')
    assert latest['data']['get_cashflow_summary']['monthly_expense']['monthly_average'] == '200.01'
    assert latest['data']['get_cashflow_summary']['expense_by_category_12m'] == {'식비': '600.04'}
    assert latest['context_snapshot_id'] != first['context_snapshot_id']

    assert client.delete(f'/api/data/cashflow-entries/{item_id}').status_code == 204
    deleted, request = consult(runtime_env, 'after-delete')
    summary = deleted['data']['get_cashflow_summary']
    assert summary['expense_by_category_12m'] == {'식비': '200.00'}
    assert summary['monthly_expense']['available'] is False
    assert summary['monthly_expense']['months_with_data'] == 2
    assert all(item['content'] != '합성 상담 결과입니다.' for item in request.input)
    with database.session() as session:
        assert dashboard_manager.summary(session)['data']['get_cashflow_summary'] == summary
        assert session.get(Account, 1).balance == Decimal('1000000')


@pytest.mark.parametrize('policy', ['record', 'category'])
def test_cashflow_exclusion_withholds_aggregate_and_prior_answer(runtime_env, policy):
    _, database, _ = runtime_env
    with database.session() as session:
        record = CashflowEntry(occurred_on=previous_months()[0], kind='expense',
                              amount=Decimal('918273.45'), category='합성비공개분류')
        session.add(record)
        session.commit()
        record_id = record.id
    package, _ = consult(runtime_env, f'allowed-{policy}',
                         reply={**FINAL, 'answer': '합성비공개분류 지출 근거를 확인했습니다.'})
    assert package['data']['get_cashflow_summary']['expense_by_category_12m'] == {'합성비공개분류': '918273.45'}
    options = {}
    if policy == 'record':
        with database.session() as session:
            set_record_policy(session, 'cashflow_entries', record_id, False)
    else:
        options['exclude'] = ['financial']
    restricted, request = consult(runtime_env, f'restricted-{policy}', **options)
    assert 'get_cashflow_summary' not in restricted['data']
    outbound = json.dumps([request.instructions, request.input], ensure_ascii=False)
    assert '918273.45' not in outbound
    assert '합성비공개분류' not in outbound
    with database.session() as session:
        # A local dashboard remains useful even when external sharing is disabled.
        assert dashboard_manager.summary(session)['data']['get_cashflow_summary']['expense_by_category_12m'] == {
            '합성비공개분류': '918273.45'}
