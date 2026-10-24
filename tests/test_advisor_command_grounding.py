"""Real extraction shapes: per-row citations and a shared save instruction."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.database.model import Holding
from app.modules.finance.clock import local_today
from test_advisor_crud_runtime import command, consult
from test_advisor_runtime_execution import runtime_env  # noqa: F401


def test_bulk_save_accepts_individual_stock_lines_under_shared_user_instruction(runtime_env):
    _, database, _ = runtime_env
    lines = ['MSFT $123.45 6주', 'AMD $67.89 11주']
    query = '내 보유 주식 전부 저장해줘\n' + '\n'.join(lines) + '\n가격은 평균 매입가야'
    commands = [command('create', 'holdings', line, values={
        'symbol': symbol, 'currency': 'USD', 'quantity': quantity, 'avg_cost': cost,
    }) for line, symbol, quantity, cost in zip(lines, ['MSFT', 'AMD'], ['6', '11'], ['123.45', '67.89'])]
    run, _ = consult(runtime_env, 'line-citations-save', query, commands)
    assert [item['status'] for item in run['result']['data_operations']] == ['saved', 'saved']
    with database.session() as session:
        rows = list(session.scalars(select(Holding).order_by(Holding.symbol)))
        assert [(row.symbol, row.quantity, row.avg_cost, row.last_price) for row in rows] == [
            ('AMD', Decimal('11'), Decimal('67.89'), None), ('MSFT', Decimal('6'), Decimal('123.45'), None)]


def test_bulk_save_cannot_borrow_another_rows_numbers(runtime_env):
    _, database, _ = runtime_env
    line = 'MSFT $123.45 6주'
    query = f'내 보유 주식 저장해줘\n{line}\nAMD $67.89 11주\n가격은 평균 매입가야'
    wrong = command('create', 'holdings', line, values={
        'symbol': 'MSFT', 'currency': 'USD', 'quantity': '11', 'avg_cost': '67.89',
    })
    run, _ = consult(runtime_env, 'cross-row-number-guard', query, [wrong])
    assert not any(item['status'] == 'saved' for item in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.id)) is None


def test_legacy_rejected_batch_confirmation_saves_before_quote_refresh(runtime_env, monkeypatch):
    from app.modules.database.model.advisor_runtime import AdvisorRun
    from app.modules.advisor.data_command_intent import command_requested
    from test_advisor_runtime_execution import FINAL

    client, database, provider = runtime_env
    line = 'MSFT $123.45 6주'
    query = f'내 보유 주식 전부 저장해줘\n{line}\n가격은 평균 매입가야'
    initial = command('create', 'holdings', line, values={
        'symbol': 'MSFT', 'quantity': '6', 'avg_cost': '123.45'})
    run, _ = consult(runtime_env, 'legacy-row-initial', query, [initial])
    with database.session() as session:
        row = session.get(AdvisorRun, run['id'])
        old_rejection = {'operation': 'create', 'resource': 'holdings', 'status': 'needs_input',
                         'message': '요청한 변경 내용과 원문의 수치를 확인해 주세요.'}
        metadata = {**row.runtime_metadata, 'data_command_plan': [], 'data_operations': [old_rejection]}
        metadata.pop('data_command_validation_version', None)
        row.runtime_metadata = metadata
        row.result = {**row.result, 'data_operations': [old_rejection]}
        session.commit()

    calls = []
    def refresh(session, *, excluded, authorization_check, write_authorization_check=None):
        authorization_check()
        assert session.scalar(select(Holding.quantity)) == Decimal('6')
        calls.append(True)
        return {'operation': 'update', 'resource': 'holdings', 'quote_refresh': True,
                'target_label': '시세 갱신', 'status': 'saved', 'refresh_state': 'updated', 'message': '합성 시세 갱신'}
    monkeypatch.setattr('app.modules.advisor.quote_refresh.refresh_quotes', refresh)
    reply = '응 해줘 그리고 최신 현재가 시세 갱신해줘'
    assert command_requested(reply)
    resolved = command('create', 'holdings', '응 해줘', values={
        'symbol': 'MSFT', 'quantity': '6', 'avg_cost': '123.45', 'currency': 'USD'})
    done, requests = consult(runtime_env, 'legacy-row-confirm-refresh', reply, [resolved])
    operations = done['result']['data_operations']
    assert len(calls) == 1
    assert [item['status'] for item in operations] == ['saved', 'saved']
    assert operations[0]['target_label'] == 'MSFT'
    assert operations[1]['quote_refresh'] is True
    with database.session() as session:
        assert len(list(session.scalars(select(Holding)))) == 1
        stored = session.get(AdvisorRun, done['id'])
        assert stored.runtime_metadata['data_command_validation_version'] == 2


def test_quote_only_request_uses_existing_refresh_without_model_command_extraction(runtime_env, monkeypatch):
    from test_advisor_runtime_execution import FINAL, finish
    client, database, provider = runtime_env
    calls = []
    def refresh(session, **kwargs):
        calls.append(True)
        return {'operation': 'update', 'resource': 'holdings', 'quote_refresh': True,
                'status': 'needs_input', 'refresh_state': 'not_connected', 'message': '합성 연결 필요'}
    monkeypatch.setattr('app.modules.advisor.quote_refresh.refresh_quotes', refresh)
    provider.replies.append(FINAL)
    response = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'only-quotes', 'message': '최신 현재가 시세 갱신해줘', 'depth': 'auto'})
    finish(database)
    run = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert run['status'] == 'completed', run
    assert calls == [True]
    assert run['result']['data_operations'][0]['refresh_state'] == 'not_connected'
    assert len(provider.requests) == 1


@pytest.mark.parametrize('cite_whole_message', [False, True])
def test_factual_account_observation_cannot_borrow_an_unrelated_workout_save_instruction(runtime_env, cite_whole_message):
    from app.modules.database.model import Account
    _, database, _ = runtime_env
    query = '합성 통장 잔액 300만원 있어. 오늘 합성 운동 45분 기록해줘'
    invented = command('create', 'accounts', query if cite_whole_message else '합성 통장 잔액 300만원 있어', values={
        'name': '합성 통장', 'kind': 'checking', 'balance': '3000000', 'currency': 'KRW',
        'balance_as_of': local_today().isoformat()})
    run, _ = consult(runtime_env, 'separate-account-fact', query, [invented])
    assert not any(item['status'] == 'saved' for item in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Account.id)) is None


def test_quote_refresh_receipts_stream_and_answer_retry_never_repeats_external_effect(runtime_env, monkeypatch):
    from app.modules.database.model.advisor_runtime import AdvisorRunEvent
    from test_advisor_runtime_execution import FINAL, finish
    client, database, provider = runtime_env
    calls = []
    def refresh(session, **kwargs):
        calls.append(True)
        return {'operation': 'update', 'resource': 'holdings', 'quote_refresh': True,
                'status': 'saved', 'refresh_state': 'updated', 'message': '합성 갱신 완료'}
    monkeypatch.setattr('app.modules.advisor.quote_refresh.refresh_quotes', refresh)
    provider.replies.append(RuntimeError('synthetic answer failure after completed quote refresh'))
    response = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'quotes-answer-fails', 'message': '시세 갱신해줘', 'depth': 'auto'})
    run_id = response.json()['id']
    finish(database)
    failed = client.get(f'/api/advisor/runs/{run_id}').json()
    assert failed['status'] in {'failed', 'blocked'}, failed
    assert failed['result']['data_operations'][0]['refresh_state'] == 'updated'
    with database.session() as session:
        events = list(session.scalars(select(AdvisorRunEvent).where(
            AdvisorRunEvent.run_id == run_id, AdvisorRunEvent.type == 'data_operations'
        ).order_by(AdvisorRunEvent.seq)))
        assert [item.payload['data_operations'][-1]['refresh_state'] for item in events] == ['unknown', 'updated']
    assert client.post(f'/api/advisor/runs/{run_id}/retry').status_code == 200
    provider.replies.append(FINAL)
    finish(database)
    completed = client.get(f'/api/advisor/runs/{run_id}').json()
    assert completed['status'] == 'completed', completed
    assert calls == [True]
    assert completed['result']['data_operations'][0]['refresh_state'] == 'updated'


@pytest.mark.parametrize('symbol,quantity,cost', [('AMD', '6', '120'), ('MSFT', '120', '6')])
def test_legacy_reextraction_cannot_change_original_ticker_or_swap_price_and_quantity(runtime_env, symbol, quantity, cost):
    from app.modules.database.model.advisor_runtime import AdvisorRun
    _, database, _ = runtime_env
    line = 'MSFT $120 6주'
    query = f'내 주식 저장해줘\n{line}\n평균 매입가야'
    first, _ = consult(runtime_env, 'legacy-unsafe-original', query, [command('create', 'holdings', line,
        values={'symbol': 'MSFT', 'quantity': '6', 'avg_cost': '120'})])
    with database.session() as session:
        row = session.get(AdvisorRun, first['id'])
        rejection = {'operation': 'create', 'resource': 'holdings', 'status': 'needs_input',
                     'message': '요청한 변경 내용과 원문의 수치를 확인해 주세요.'}
        metadata = {**row.runtime_metadata, 'data_command_plan': [], 'data_operations': [rejection]}
        metadata.pop('data_command_validation_version', None)
        row.runtime_metadata = metadata
        row.result = {**row.result, 'data_operations': [rejection]}
        session.commit()
    bad = command('create', 'holdings', '응', values={
        'symbol': symbol, 'currency': 'USD', 'quantity': quantity, 'avg_cost': cost})
    run, _ = consult(runtime_env, 'legacy-unsafe-confirmation', '응', [bad])
    assert not any(item['status'] == 'saved' for item in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.id)) is None
