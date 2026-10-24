from datetime import UTC, datetime

import httpx
import pytest

from app.modules.portfolio.symbol_directory import SymbolDirectory

NASDAQ_HEADER = 'Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares'
OTHER_HEADER = 'ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol'
FOOTER = 'File Creation Time: 1023202621:31|||||||'
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def directory(nasdaq=(), other=(), *, handler=None, clock=None):
    seen = []
    bodies = {'nasdaqlisted.txt': '\n'.join([NASDAQ_HEADER, *nasdaq, FOOTER]),
              'otherlisted.txt': '\n'.join([OTHER_HEADER, *other, FOOTER])}
    def fetch(request):
        seen.append(request)
        if handler:
            return handler(request)
        return httpx.Response(200, text=bodies[request.url.path.rsplit('/', 1)[-1]])
    client = httpx.Client(transport=httpx.MockTransport(fetch))
    return SymbolDirectory(client=client, now=lambda: NOW, clock=clock), seen


def test_unique_official_listing_resolves_bare_ticker_without_sending_personal_arguments():
    lookup, seen = directory(nasdaq=['SYNTH|Synthetic common shares|Q|N|N|100|N|N'])
    result = lookup.resolve('synth', 'USD')
    assert result['status'] == 'resolved'
    assert result['symbol'] == 'NASDAQ:SYNTH'
    assert result['candidates'] == ['NASDAQ:SYNTH']
    assert result['source'] == 'nasdaq_trader'
    assert result['as_of'] == '2026-10-24T01:31:00+00:00'
    assert len(seen) == 2
    assert all(request.method == 'GET' and not request.url.query and not request.content for request in seen)
    assert all(request.url.host == 'www.nasdaqtrader.com' for request in seen)
    assert not any('synth' in str(request.url).lower() for request in seen)


@pytest.mark.parametrize('code,exchange', [('A', 'NYSEAMERICAN'), ('N', 'NYSE'), ('P', 'NYSEARCA')])
def test_other_exchange_primary_codes_are_mapped_from_the_public_directory(code, exchange):
    lookup, _ = directory(other=[f'SYNTH|Synthetic fund|{code}|SYNTH|Y|100|N|SYNTH'])
    assert lookup.resolve('SYNTH')['symbol'] == f'{exchange}:SYNTH'


def test_test_issues_unknown_tickers_and_unsupported_venues_never_get_guessed():
    lookup, _ = directory(nasdaq=['TESTONLY|Synthetic test issue|Q|Y|N|100|N|N'],
                          other=['UNSUP|Unsupported market|Z|UNSUP|N|100|N|UNSUP'])
    assert lookup.resolve('TESTONLY')['status'] == 'not_found'
    assert lookup.resolve('MISSING')['status'] == 'not_found'
    assert lookup.resolve('UNSUP')['status'] == 'unsupported'
    assert lookup.resolve('UNSUP')['symbol'] is None


def test_contradictory_exchange_listings_require_a_choice_instead_of_first_match():
    lookup, _ = directory(nasdaq=['DUAL|Synthetic Nasdaq issue|Q|N|N|100|N|N'],
                          other=['DUAL|Synthetic NYSE issue|N|DUAL|N|100|N|DUAL'])
    result = lookup.resolve('DUAL')
    assert result['status'] == 'ambiguous'
    assert result['symbol'] is None
    assert result['candidates'] == ['NASDAQ:DUAL', 'NYSE:DUAL']


def test_unsupported_listing_still_prevents_supported_match_from_appearing_unique():
    lookup, _ = directory(nasdaq=['DUAL|Synthetic issue|Q|N|N|100|N|N'],
                          other=['DUAL|Synthetic other listing|Z|DUAL|N|100|N|DUAL'])
    assert lookup.resolve('DUAL')['status'] == 'ambiguous'


def test_cache_reuses_only_fresh_complete_directories_and_never_old_success_after_failure():
    from app.modules.portfolio.symbol_directory import CACHE_SECONDS
    ticks = [0]
    fail = [False]
    bodies = {'nasdaqlisted.txt': '\n'.join([NASDAQ_HEADER, 'SYNTH|Synthetic issue|Q|N|N|100|N|N', FOOTER]),
              'otherlisted.txt': '\n'.join([OTHER_HEADER, FOOTER])}
    def fetch(request):
        return httpx.Response(503 if fail[0] else 200,
                              text=bodies[request.url.path.rsplit('/', 1)[-1]])
    lookup, seen = directory(handler=fetch, clock=lambda: ticks[0])
    assert lookup.resolve('SYNTH')['status'] == 'resolved'
    assert lookup.resolve('SYNTH')['status'] == 'resolved'
    assert len(seen) == 2
    ticks[0] += CACHE_SECONDS + 1
    fail[0] = True
    assert lookup.resolve('SYNTH')['status'] == 'unavailable'
    assert lookup.resolve('SYNTH')['status'] == 'unavailable'
    assert len(seen) == 3  # Short failure cooldown also protects bulk requests.


@pytest.mark.parametrize('bad', [
    '<html>upstream error</html>',
    NASDAQ_HEADER + '\nSYNTH|Synthetic issue|Q|N|N|100|N|N',  # No complete-file trailer.
    NASDAQ_HEADER + '\nSYNTH|Synthetic issue|Q|N|N|100|N|N\nFile Creation Time: 1001202621:31|||||||',
    NASDAQ_HEADER + '\nSYNTH|Synthetic issue|Q|N|N|100|N|N\nFile Creation Time: 1030202621:31|||||||',
    NASDAQ_HEADER + '\nSYNTH|truncated\n' + FOOTER,
])
def test_malformed_stale_future_or_truncated_directory_fails_closed(bad):
    lookup, _ = directory(handler=lambda request: httpx.Response(200, text=bad))
    assert lookup.resolve('SYNTH')['status'] == 'unavailable'


def test_redirects_timeout_and_oversize_are_not_treated_as_listing_evidence():
    from app.modules.portfolio.symbol_directory import MAX_RESPONSE_BYTES
    for handler in [
        lambda request: httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}),
        lambda request: httpx.Response(200, content=b'x' * (MAX_RESPONSE_BYTES + 1)),
        lambda request: httpx.Response(200, headers={'Content-Length': str(MAX_RESPONSE_BYTES + 1)}),
    ]:
        lookup, seen = directory(handler=handler)
        assert lookup.resolve('SYNTH')['status'] == 'unavailable'
        assert len(seen) == 1
    def timeout(request):
        raise httpx.ReadTimeout('synthetic timeout', request=request)
    lookup, seen = directory(handler=timeout)
    assert lookup.resolve('SYNTH')['status'] == 'unavailable'
    assert len(seen) == 1


def test_invalid_foreign_or_qualified_input_never_causes_a_search_request():
    lookup, seen = directory()
    for ticker, currency in [('000001', 'KRW'), ('SYNTH', 'EUR'), ('../private', 'USD'),
                             ('http://localhost', 'USD'), ('SYNTH?balance=10', 'USD')]:
        assert lookup.resolve(ticker, currency)['status'] == 'unsupported'
    provided = lookup.resolve('nyse:synth')
    assert provided['status'] == 'resolved'
    assert provided['symbol'] == 'NYSE:SYNTH'
    assert provided['source'] == 'user_provided'
    assert not seen
