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


def _populate_every_home_section(session):
    from datetime import timedelta
    from app.modules.database.model import Account, CalendarEvent, Goal, Interview, JobApplication, Task
    app = JobApplication(company='Synthetic', role='Engineer', status='applied', next_step='call')
    session.add(app)
    session.flush()
    session.add_all([
        Account(name='Synthetic cash', kind='checking', currency='KRW', balance=Decimal('1000.50'),
                balance_as_of=date(2026, 10, 19), is_liquid=True),
        *[CashflowEntry(occurred_on=date(2026, month, 1), kind='expense', amount=Decimal('100'), currency='KRW')
          for month in (7, 8, 9, 10)],
        Goal(title='Synthetic goal', category='personal', target_value='10', current_value='3', unit='km',
             target_date=date(2026, 10, 25)),
        Task(title='Synthetic task', due_on=date(2026, 10, 19)),
        CalendarEvent(title='Synthetic event', starts_at=NOW + timedelta(hours=1), ends_at=NOW + timedelta(hours=2)),
        CalendarEvent(title='Overlap', starts_at=NOW + timedelta(hours=1), ends_at=NOW + timedelta(hours=3)),
        Interview(application_id=app.id, stage='first', starts_at=NOW + timedelta(days=1)),
        WorkoutLog(performed_on=date(2026, 10, 18), activity='run', duration_seconds=2737),
    ])
    session.commit()


def test_typed_summary_is_the_payload_the_manager_built(session):
    """The response model types the home fields but must not add, drop or coerce any key."""
    import json
    from app.schema.dashboard_schema import DashboardSummary

    for populate in (lambda s: None, _populate_every_home_section):
        populate(session)
        built = json.loads(json.dumps(dashboard_manager.summary(session, NOW), default=str))
        typed = DashboardSummary.model_validate(built).model_dump(mode='json', exclude_unset=True)
        assert typed == built


def test_typed_summary_reads_home_fields(session):
    from app.schema.dashboard_schema import DashboardSummary

    _populate_every_home_section(session)
    data = DashboardSummary.model_validate(dashboard_manager.summary(session, NOW)).data
    assert data.get_accounts_summary.computed.net_worth.spendable_liquidity == '1000.50'
    assert data.get_cashflow_summary.monthly_expense.available is True
    assert data.get_tasks.open_tasks[0].overdue is True
    assert data.get_calendar_events.conflicts
    assert data.get_job_applications.applications[0].next_step == 'call'
    assert data.get_health_summary.total_seconds == 2737
    assert data.cash_runway.available is True


def test_onboarding_state_round_trip(client):
    assert client.get('/api/dashboard/onboarding').json() == {'dismissed': False}
    assert client.put('/api/dashboard/onboarding', json={'dismissed': True}).json() == {'dismissed': True}
    assert client.get('/api/dashboard/onboarding').json() == {'dismissed': True}
