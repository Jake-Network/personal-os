from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.dashboard.dashboard_manager import dashboard_manager
from app.modules.database.model import CashflowEntry, WorkoutLog

NOW = datetime(2026, 10, 20, 3, tzinfo=UTC)


def test_empty_dashboard_has_incomplete_checklist(session):
    result = dashboard_manager.summary(session, NOW)
    assert result['signals'] == []
    assert result['checklist']['has_cash_account'] is False
    assert result['checklist']['has_recent_expense'] is False
    assert result['checklist']['has_active_application_or_goal'] is False


def test_old_workout_counts_but_future_workout_does_not(session):
    session.add_all([
        WorkoutLog(performed_on=date(2026, 1, 1), activity='walk', duration_seconds=1200),
        WorkoutLog(performed_on=date(2026, 10, 21), activity='walk', duration_seconds=1200),
    ])
    session.commit()
    result = dashboard_manager.summary(session, NOW)
    assert [s['kind'] for s in result['signals']] == ['exercise']
    assert result['data']['get_health_summary']['last_session_on'] == '2026-01-01'


def test_expense_signal_requires_complete_currency_coverage(session):
    session.add_all([CashflowEntry(occurred_on=date(2026, month, 1), kind='expense', amount=Decimal(amount), currency='KRW')
                     for month, amount in [(7, '100'), (8, '100'), (9, '100'), (10, '101')]])
    session.commit()
    assert 'expenses' in [s['kind'] for s in dashboard_manager.summary(session, NOW)['signals']]
    session.add(CashflowEntry(occurred_on=date(2026, 8, 2), kind='expense', amount=Decimal('1'), currency='USD'))
    session.commit()
    assert 'expenses' not in [s['kind'] for s in dashboard_manager.summary(session, NOW)['signals']]


def test_goal_interview_half_open_windows_and_completed_goals(session):
    from datetime import timedelta
    from app.modules.database.model import Goal, Interview, JobApplication
    app = JobApplication(company='Synthetic', role='Engineer', status='applied')
    session.add(app)
    session.flush()
    session.add_all([
        Goal(title='today', category='personal', target_date=date(2026, 10, 20)),
        Goal(title='boundary', category='personal', target_date=date(2026, 11, 3)),
        Goal(title='done', category='personal', target_date=date(2026, 10, 21), status='done'),
        Interview(application_id=app.id, stage='first', starts_at=NOW),
        Interview(application_id=app.id, stage='boundary', starts_at=NOW + timedelta(days=7)),
    ])
    session.commit()
    assert dashboard_manager.summary(session, NOW)['signals'] == [
        {'kind': 'goals', 'count': 1}, {'kind': 'interviews', 'count': 1}]


def test_workout_recent_window_uses_app_today(session, monkeypatch):
    from app.config import settings
    from dataclasses import replace
    monkeypatch.setattr('app.modules.context.context_tool_manager.settings', replace(settings, timezone='Asia/Tokyo'))
    monkeypatch.setattr('app.modules.dashboard.dashboard_manager.settings', replace(settings, timezone='Asia/Tokyo'))
    session.add(WorkoutLog(performed_on=date(2026, 10, 14), activity='walk', duration_seconds=1200))
    session.commit()
    # Tokyo is already Oct 21: Oct 14 is outside today plus preceding six days.
    result = dashboard_manager.summary(session, datetime(2026, 10, 20, 15, tzinfo=UTC))
    assert {'kind': 'exercise', 'count': 1} in result['signals']
    session.add(WorkoutLog(performed_on=date(2026, 10, 21), activity='walk', duration_seconds=1200))
    session.commit()
    assert not dashboard_manager.summary(session, datetime(2026, 10, 20, 15, tzinfo=UTC))['signals']


def test_expense_checklist_excludes_foreign_future_and_old_records(session):
    session.add_all([
        CashflowEntry(occurred_on=date(2026, 9, 20), kind='expense', amount=Decimal('1'), currency='KRW'),
        CashflowEntry(occurred_on=date(2026, 10, 20), kind='expense', amount=Decimal('1'), currency='USD'),
        CashflowEntry(occurred_on=date(2026, 10, 21), kind='expense', amount=Decimal('1'), currency='KRW'),
    ])
    session.commit()
    assert not dashboard_manager.summary(session, NOW)['checklist']['has_recent_expense']
    session.add(CashflowEntry(occurred_on=date(2026, 9, 21), kind='expense', amount=Decimal('1'), currency='KRW'))
    session.commit()
    assert dashboard_manager.summary(session, NOW)['checklist']['has_recent_expense']


def test_configuration_checks_selected_provider_only(session, monkeypatch):
    from app.modules.crud import app_setting_handler
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager, PROVIDER_KEY
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic')
    assert not llm_gateway_manager.configuration_complete(session)
    app_setting_handler.set_value(session, PROVIDER_KEY, {'name': 'openai_api_key'})
    assert llm_gateway_manager.configuration_complete(session)
    app_setting_handler.set_value(session, PROVIDER_KEY, {'name': 'codex_app_server'})
    assert not llm_gateway_manager.configuration_complete(session)


def test_dashboard_http_contract(client):
    response = client.get('/api/dashboard/summary')
    assert response.status_code == 200
    assert set(response.json()['checklist']) == {'ai_configuration_complete', 'has_cash_account', 'has_recent_expense', 'has_active_application_or_goal'}


def test_expense_signal_requires_strict_increase_and_all_three_months(session):
    session.add_all([CashflowEntry(occurred_on=date(2026, month, 1), kind='expense', amount=Decimal('100'), currency='KRW')
                     for month in (7, 9, 10)])
    session.commit()
    assert not dashboard_manager.summary(session, NOW)['signals']
    session.add(CashflowEntry(occurred_on=date(2026, 8, 1), kind='expense', amount=Decimal('100'), currency='KRW'))
    session.commit()
    assert not dashboard_manager.summary(session, NOW)['signals']
