import asyncio

from app.modules.advisor.symbol_resolution import resolve_command_symbol


def test_lookup_failure_cannot_preserve_a_model_guessed_exchange(monkeypatch):
    monkeypatch.setattr('app.modules.portfolio.symbol_directory.symbol_directory.resolve',
        lambda *_: {'status': 'unavailable', 'symbol': None, 'source': 'nasdaq_trader'})
    command = {'resource': 'holdings', 'operation': 'create', 'values': {'symbol': 'NYSE:QATEST', 'currency': 'USD'}}
    result = asyncio.run(resolve_command_symbol(command, 'QATEST 8주 저장해줘'))
    assert result['values']['symbol'] == 'QATEST'
    assert result['symbol_resolution']['status'] == 'unavailable'


def test_user_explicit_exchange_is_preserved_without_directory_request(monkeypatch):
    def forbidden(*_):
        raise AssertionError('No lookup for an exchange explicitly chosen by the user')
    monkeypatch.setattr('app.modules.portfolio.symbol_directory.symbol_directory.resolve', forbidden)
    command = {'resource': 'holdings', 'operation': 'create', 'values': {'symbol': 'NASDAQ:QATEST', 'currency': 'USD'}}
    assert asyncio.run(resolve_command_symbol(command, 'NASDAQ:QATEST 8주 저장해줘')) == command
