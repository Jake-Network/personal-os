"""Review regressions for per-command trade direction and quote-session ownership."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.database.model import Holding
from test_advisor_crud_runtime import command, consult
from test_advisor_runtime_execution import runtime_env  # noqa: F401


@pytest.mark.parametrize('whole_message_quote', [False, True])
def test_mixed_buy_sell_message_cannot_turn_its_sale_into_an_addition(runtime_env, whole_message_quote):
    _, database, _ = runtime_env
    with database.session() as session:
        session.add_all([
            Holding(symbol='AAPL', currency='USD', quantity=20, avg_cost=100),
            Holding(symbol='TSLA', currency='USD', quantity=7, avg_cost=200),
        ])
        session.commit()
    query = '아래 주식 보유량 모두 반영해줘\nAAPL 10주 매도하고 TSLA 5주 매수했어'
    run, _ = consult(runtime_env, 'mixed-directions-wrong-sign', query, [
        command('update', 'holdings', query if whole_message_quote else 'AAPL 10주 매도',
                selector={'symbol': 'AAPL'}, values={'delta': '10'}),
        command('update', 'holdings', query if whole_message_quote else 'TSLA 5주 매수했어',
                selector={'symbol': 'TSLA'}, values={'delta': '5'}),
    ])
    assert not any(op['status'] == 'saved' and op.get('target_label') == 'AAPL'
                   for op in run['result']['data_operations'])
    with database.session() as session:
        rows = {row.symbol: row.quantity for row in session.scalars(select(Holding))}
        assert rows == {'AAPL': Decimal('20'), 'TSLA': Decimal('12')}


@pytest.mark.parametrize('whole_message_quote', [False, True])
def test_mixed_trade_directions_apply_each_correct_signed_delta(runtime_env, whole_message_quote):
    _, database, _ = runtime_env
    with database.session() as session:
        session.add_all([Holding(symbol='AAPL', currency='USD', quantity=20),
                         Holding(symbol='TSLA', currency='USD', quantity=7)])
        session.commit()
    query = '아래 주식 보유량 모두 반영해줘\nAAPL 10주 매도하고 TSLA 5주 매수했어'
    run, _ = consult(runtime_env, 'mixed-directions-correct-signs', query, [
        command('update', 'holdings', query if whole_message_quote else 'AAPL 10주 매도',
                selector={'symbol': 'AAPL'}, values={'delta': '-10'}),
        command('update', 'holdings', query if whole_message_quote else 'TSLA 5주 매수했어',
                selector={'symbol': 'TSLA'}, values={'delta': '5'}),
    ])
    assert all(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert {row.symbol: row.quantity for row in session.scalars(select(Holding))} == {
            'AAPL': Decimal('10'), 'TSLA': Decimal('12')}


def test_quote_thread_owns_session_and_read_auth_cannot_commit_staged_data(runtime_env, monkeypatch):
    import threading
    from test_advisor_runtime_execution import finish
    client, database, _ = runtime_env
    original_factory = database.session
    quote_sessions = []

    def factory():
        session = original_factory()
        session.info['created_thread'] = threading.get_ident()
        return session
    monkeypatch.setattr(database, 'session', factory)

    def refresh(session, *, authorization_check, **kwargs):
        quote_sessions.append(session)
        assert session.info['created_thread'] == threading.get_ident()
        session.add(Holding(symbol='QASTAGED', name='synthetic uncommitted refresh', currency='USD', quantity=1))
        session.flush()
        authorization_check()
        with original_factory() as independent:
            assert independent.scalar(select(Holding.id).where(Holding.symbol == 'QASTAGED')) is None
        raise RuntimeError('synthetic later quote stage failure')
    monkeypatch.setattr('app.modules.advisor.commands.quote_refresh.refresh_quotes', refresh)
    created = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'quote-owned-session-rollback', 'message': '시세 갱신해줘', 'depth': 'auto'})
    finish(database)
    run = client.get(f"/api/advisor/runs/{created.json()['id']}").json()
    assert run['status'] in {'failed', 'blocked'}
    assert len(quote_sessions) == 1
    assert quote_sessions[0].info['created_thread'] != threading.get_ident()
    with original_factory() as independent:
        assert independent.scalar(select(Holding.id).where(Holding.symbol == 'QASTAGED')) is None


@pytest.mark.parametrize('repeat_cancel', [False, True])
def test_cancel_waits_for_quote_thread_to_close_its_own_session(runtime_env, monkeypatch, repeat_cancel):
    import asyncio
    import threading
    from app.modules.advisor.runtime.worker import process_one
    client, database, _ = runtime_env
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    original_factory = database.session
    quote_session = []

    def factory():
        session = original_factory()
        original_close = session.close
        def close():
            if quote_session and session is quote_session[0]:
                closed.set()
            original_close()
        session.close = close
        return session
    monkeypatch.setattr(database, 'session', factory)

    def refresh(session, **kwargs):
        quote_session.append(session)
        entered.set()
        assert release.wait(10)
        assert not closed.is_set()
        return {'operation': 'update', 'resource': 'holdings', 'quote_refresh': True,
                'status': 'needs_input', 'refresh_state': 'not_connected', 'message': 'synthetic connection needed'}
    monkeypatch.setattr('app.modules.advisor.commands.quote_refresh.refresh_quotes', refresh)
    assert client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'quote-cancel-owned-session', 'message': '시세 갱신해줘', 'depth': 'auto'}).status_code == 201

    async def cancel():
        task = asyncio.create_task(process_one(database))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not closed.is_set()
            if repeat_cancel:
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done() and not closed.is_set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert closed.is_set()
    asyncio.run(cancel())


def test_explicit_exchange_ticker_can_be_created_from_its_own_source(runtime_env):
    _, database, _ = runtime_env
    query = '내 주식 NASDAQ:QAPRIV 3주 평균 매입가 12달러로 저장해줘'
    run, _ = consult(runtime_env, 'explicit-qualified-source', query, [
        command('create', 'holdings', query, values={'symbol': 'NASDAQ:QAPRIV',
                'quantity': '3', 'avg_cost': '12', 'currency': 'USD'})])
    assert run['result']['data_operations'][0]['status'] == 'saved'
    with database.session() as session:
        assert session.scalar(select(Holding.symbol)) == 'NASDAQ:QAPRIV'


def test_explicit_exchange_cannot_be_changed_by_model(runtime_env):
    _, database, _ = runtime_env
    query = '내 주식 NASDAQ:QAPRIV 3주 평균 매입가 12달러로 저장해줘'
    run, _ = consult(runtime_env, 'wrong-qualified-source', query, [
        command('create', 'holdings', query, values={'symbol': 'NYSE:QAPRIV',
                'quantity': '3', 'avg_cost': '12', 'currency': 'USD'})])
    assert not any(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.id)) is None


def test_direction_cannot_be_borrowed_from_another_targets_only_trade():
    from app.modules.advisor.commands.direction import delta_direction
    query = 'AAPL 10주 매도하고 TSLA 보유량 5주로 수정해줘'
    candidate = {'selector': {'symbol': 'TSLA'}, 'values': {'delta': '-5'}}
    assert delta_direction(candidate, query) is None


def test_quote_batch_rolls_back_all_prices_if_later_stage_fails_after_auth_check(runtime_env, monkeypatch):
    from datetime import UTC, datetime
    from app.modules.database.model import LocalPosition, MarketSettings, MarketObservation
    from app.modules.portfolio import portfolio_manager, market_data_manager
    from app.modules.advisor.commands import quote_refresh as quotes
    from test_advisor_runtime_execution import FINAL, finish
    client, database, provider = runtime_env
    monkeypatch.setattr(portfolio_manager, '_source', lambda _: ('synthetic-owned-quotes', False))
    with database.session() as session:
        for index, symbol in enumerate(('KRX:000001', 'KRX:000002'), 1):
            row = Holding(symbol=symbol, currency='KRW', quantity=3, avg_cost=11, last_price=19)
            session.add(row)
            session.flush()
            session.add(LocalPosition(position_id=f'synthetic-owned-{index}', holding_id=row.id,
                                      quote_mode='auto', version='synthetic'))
        session.add(MarketSettings(id=1, spreadsheet_id='synthetic-owned-file', source_identity='synthetic-owned-quotes'))
        session.commit()

    class PublicQuotes:
        source_identity = 'synthetic-owned-quotes'
        def read(self, _):
            serial = (datetime.now(UTC) - datetime(1899, 12, 30, tzinfo=UTC)).total_seconds() / 86400
            return [[symbol, 27, 'KRW', serial, 20] for symbol in ('KRX:000001', 'KRX:000002')], []
    monkeypatch.setattr('app.modules.portfolio.quotes_sheet.QuotesSheet', lambda _: PublicQuotes())
    actual_refresh, guards = quotes.refresh_quotes, []
    def capture_refresh(session, **kwargs):
        guards.append(kwargs['authorization_check'])
        return actual_refresh(session, **kwargs)
    monkeypatch.setattr(quotes, 'refresh_quotes', capture_refresh)
    actual_observation = market_data_manager._observation
    def fail_later(session, symbol, *args, **kwargs):
        if symbol == 'KRX:000002':
            guards[0]()  # Must not commit the first staged price or block on its run fence.
            with database.session() as independent:
                assert independent.scalar(select(Holding.last_price).where(Holding.symbol == 'KRX:000001')) == 19
            raise ValueError('synthetic later stage failed')
        return actual_observation(session, symbol, *args, **kwargs)
    monkeypatch.setattr(market_data_manager, '_observation', fail_later)
    provider.replies.append(FINAL)
    response = client.post('/api/advisor/conversations/1/runs', json={
        'request_id': 'atomic-public-quote-batch', 'message': '시세 갱신해줘', 'depth': 'auto'})
    finish(database)
    result = client.get(f"/api/advisor/runs/{response.json()['id']}").json()
    assert result['status'] == 'completed', result
    assert result['result']['data_operations'][0]['refresh_state'] == 'failed'
    with database.session() as session:
        assert list(session.scalars(select(Holding.last_price).order_by(Holding.id))) == [19, 19]
        assert session.scalar(select(MarketObservation.id)) is None
        # The pre-I/O cooldown claim intentionally survives; quote results do not.
        assert session.get(MarketSettings, 1).last_attempt_at is not None


def test_quote_error_cleanup_preserves_the_original_write_authority_error(session, monkeypatch):
    from app.modules.database.model import LocalPosition, MarketSettings
    from app.modules.portfolio import portfolio_manager
    from app.modules.advisor.commands.quote_refresh import refresh_quotes
    monkeypatch.setattr(portfolio_manager, '_source', lambda _: ('synthetic-cleanup', False))
    row = Holding(symbol='KRX:000001', currency='KRW', quantity=1, last_price=19)
    session.add(row)
    session.flush()
    session.add_all([LocalPosition(position_id='synthetic-cleanup', holding_id=row.id, quote_mode='auto', version='x'),
                     MarketSettings(id=1, spreadsheet_id='synthetic-file', source_identity='synthetic-cleanup')])
    session.commit()
    revoked = []
    class BrokenQuotes:
        source_identity = 'synthetic-cleanup'
        def read(self, _):
            revoked.append(True)
            raise ValueError('synthetic provider failure')
    def final_guard():
        if revoked:
            raise RuntimeError('synthetic final authority lost')
    with pytest.raises(RuntimeError, match='synthetic final authority lost'):
        refresh_quotes(session, client=BrokenQuotes(), write_authorization_check=final_guard)
    session.refresh(row)
    assert row.last_price == 19


def test_bare_citation_cannot_discard_an_explicit_exchange_elsewhere_in_user_input(runtime_env):
    _, database, _ = runtime_env
    query = '내 주식 NASDAQ:QAPRIV 3주 평균 매입가 12달러로 저장해줘'
    excerpt = 'QAPRIV 3주 평균 매입가 12달러로 저장해줘'
    run, _ = consult(runtime_env, 'wrong-exchange-narrow-citation', query, [
        command('create', 'holdings', excerpt, values={'symbol': 'NYSE:QAPRIV',
                'quantity': '3', 'avg_cost': '12', 'currency': 'USD'})])
    assert not any(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.id)) is None


@pytest.mark.parametrize('selector_kind', ['symbol', 'id'])
def test_trade_cannot_borrow_another_tickers_citation(runtime_env, selector_kind):
    _, database, _ = runtime_env
    with database.session() as session:
        first = Holding(symbol='AAPL', currency='USD', quantity=20)
        second = Holding(symbol='TSLA', currency='USD', quantity=20)
        session.add_all([first, second])
        session.commit()
        selector = {'symbol': 'TSLA'} if selector_kind == 'symbol' else {'id': second.id}
    query = '아래 주식 보유량 모두 반영해줘\nAAPL 10주 매도하고 TSLA 5주 매수했어'
    run, _ = consult(runtime_env, 'mismatched-trade-citation', query, [
        command('update', 'holdings', 'AAPL 10주 매도', selector=selector, values={'delta': '-10'})])
    assert not any(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert {row.symbol: row.quantity for row in session.scalars(select(Holding))} == {
            'AAPL': Decimal('20'), 'TSLA': Decimal('20')}


def test_trade_citation_cannot_swap_its_explicit_exchange(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        session.add(Holding(symbol='NASDAQ:QATICK', currency='USD', quantity=20))
        session.commit()
    query = '아래 주식 보유량 모두 반영해줘\nNYSE:QATICK 10주 매도했어'
    run, _ = consult(runtime_env, 'wrong-exchange-trade-citation', query, [
        command('update', 'holdings', 'NYSE:QATICK 10주 매도했어',
                selector={'symbol': 'NASDAQ:QATICK'}, values={'delta': '-10'})])
    assert not any(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.quantity)) == 20


def test_short_citation_cannot_borrow_direction_from_a_mixed_target_clause():
    from app.modules.advisor.commands.direction import delta_direction
    candidate = {'selector': {'symbol': 'TSLA'}, 'values': {'delta': '-10'}}
    query = 'AAPL 10주 매도 및 TSLA 5주 매수했어'
    assert delta_direction(candidate, '10주 매도', original_query=query) is None


def test_named_unambiguous_citation_stays_valid_inside_a_mixed_target_clause():
    from app.modules.advisor.commands.direction import delta_direction
    candidate = {'selector': {'symbol': 'TSLA'}, 'values': {'delta': '5'}}
    query = 'AAPL 10주 매도 및 TSLA 5주 매수했어'
    assert delta_direction(candidate, 'TSLA 5주 매수했어', original_query=query) == 1


def test_short_wrong_target_citation_cannot_update_in_mixed_unsplit_clause(runtime_env):
    _, database, _ = runtime_env
    with database.session() as session:
        session.add(Holding(symbol='TSLA', currency='USD', quantity=20))
        session.commit()
    query = '아래 주식 보유량 모두 반영해줘\nAAPL 10주 매도 및 TSLA 5주 매수했어'
    run, _ = consult(runtime_env, 'short-mixed-wrong-target', query, [
        command('update', 'holdings', '10주 매도', selector={'symbol': 'TSLA'}, values={'delta': '-10'})])
    assert not any(op['status'] == 'saved' for op in run['result']['data_operations'])
    with database.session() as session:
        assert session.scalar(select(Holding.quantity)) == 20
