"""Resolve US listing identity from Nasdaq's public, fixed directory files.

The requests download whole directories: no ticker, portfolio value or local ID is
sent. Listing fields follow https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs.
This synchronous provider belongs outside database fences, in a worker thread.
"""
from __future__ import annotations

import csv
import io
import re
import threading
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

DIRECTORY_URLS = (
    'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',
    'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt',
)
MAX_RESPONSE_BYTES = 2_000_000
CACHE_SECONDS = 6 * 60 * 60
FAILURE_SECONDS = 60
MAX_FILE_AGE = timedelta(days=7)
_SYMBOL = re.compile(r'[A-Z][A-Z0-9.-]{0,30}')
_SUPPORTED = frozenset({'NASDAQ', 'NYSE', 'NYSEARCA', 'NYSEAMERICAN'})
_OTHER_EXCHANGES = {'A': 'NYSEAMERICAN', 'N': 'NYSE', 'P': 'NYSEARCA'}


class _DirectoryUnavailable(Exception):
    pass


class SymbolDirectory:
    def __init__(self, *, client=None, clock=None, now=None):
        self.client = client
        self.clock = clock or time.monotonic
        self.now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._index: dict[str, set[str | None]] | None = None
        self._as_of: datetime | None = None
        self._expires = 0.0
        self._retry_after = 0.0

    def _fresh(self, as_of):
        return as_of is not None and -timedelta(minutes=5) <= self.now() - as_of <= MAX_FILE_AGE

    def _fetch(self, client, url, deadline):
        with client.stream('GET', url, follow_redirects=False,
                           timeout=httpx.Timeout(6, connect=3, pool=3),
                           headers={'Accept': 'text/plain'}) as response:
            if response.status_code != 200:
                raise _DirectoryUnavailable()
            length = response.headers.get('Content-Length', '')
            if length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                raise _DirectoryUnavailable()
            body = bytearray()
            for chunk in response.iter_bytes():
                if self.clock() > deadline or len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise _DirectoryUnavailable()
                body.extend(chunk)
            return body.decode('utf-8-sig')

    def _parse(self, content, *, nasdaq):
        lines = [line for line in content.splitlines() if line.strip()]
        if len(lines) < 2:
            raise _DirectoryUnavailable()
        trailer = re.fullmatch(r'File Creation Time:\s*(\d{10}:\d{2})\|*', lines[-1])
        if trailer is None:
            raise _DirectoryUnavailable()
        as_of = datetime.strptime(trailer[1], '%m%d%Y%H:%M').replace(
            tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
        if not self._fresh(as_of):
            raise _DirectoryUnavailable()
        rows = csv.DictReader(io.StringIO('\n'.join(lines[:-1])), delimiter='|')
        required = {'Symbol', 'Market Category', 'Test Issue'} if nasdaq else {'ACT Symbol', 'Exchange', 'Test Issue'}
        if (not rows.fieldnames or len(rows.fieldnames) != len(set(rows.fieldnames))
                or not required.issubset(rows.fieldnames)):
            raise _DirectoryUnavailable()
        result: dict[str, set[str | None]] = {}
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise _DirectoryUnavailable()
            if row['Test Issue'] != 'N':
                continue
            symbol = row['Symbol' if nasdaq else 'ACT Symbol'].strip().upper()
            if not _SYMBOL.fullmatch(symbol):
                continue
            exchange = ('NASDAQ' if row['Market Category'] in {'Q', 'G', 'S'} else None) if nasdaq else _OTHER_EXCHANGES.get(row['Exchange'])
            # Unsupported listing venues still prevent a contradictory supported
            # match from being selected. They never become invented Google codes.
            result.setdefault(symbol, set()).add(f'{exchange}:{symbol}' if exchange else None)
        return result, as_of

    def _load(self):
        now = self.clock()
        if self._index is not None and now < self._expires and self._fresh(self._as_of):
            return True
        if now < self._retry_after:
            return False
        self._index, self._as_of = None, None
        try:
            context = nullcontext(self.client) if self.client is not None else httpx.Client(follow_redirects=False)
            with context as client:
                deadline = self.clock() + 12
                combined: dict[str, set[str | None]] = {}
                dates = []
                for index, url in enumerate(DIRECTORY_URLS):
                    records, as_of = self._parse(self._fetch(client, url, deadline), nasdaq=index == 0)
                    for symbol, candidates in records.items():
                        combined.setdefault(symbol, set()).update(candidates)
                    dates.append(as_of)
            self._index, self._as_of = combined, min(dates)
            self._expires = self.clock() + CACHE_SECONDS
            self._retry_after = 0
            return True
        except (httpx.HTTPError, UnicodeError, ValueError, csv.Error, _DirectoryUnavailable):
            self._retry_after = self.clock() + FAILURE_SECONDS
            return False

    def resolve(self, symbol: str, currency: str = 'USD') -> dict:
        result = {'status': 'unsupported', 'symbol': None, 'candidates': [], 'source': 'nasdaq_trader', 'as_of': None}
        if not isinstance(symbol, str) or not isinstance(currency, str):
            return result
        symbol = symbol.strip().upper()
        if ':' in symbol:
            exchange, bare = symbol.split(':', 1)
            if exchange in _SUPPORTED and _SYMBOL.fullmatch(bare):
                return {**result, 'status': 'resolved', 'symbol': symbol, 'candidates': [symbol], 'source': 'user_provided'}
            return result
        if currency.upper() != 'USD' or not _SYMBOL.fullmatch(symbol):
            return result
        with self._lock:
            if not self._load():
                return {**result, 'status': 'unavailable'}
            matches = self._index.get(symbol, set())
            candidates = sorted(candidate for candidate in matches if candidate is not None)
            result = {**result, 'as_of': self._as_of.isoformat(), 'candidates': candidates}
            if not matches:
                return {**result, 'status': 'not_found'}
            if len(matches) > 1:
                return {**result, 'status': 'ambiguous'}
            if candidates:
                return {**result, 'status': 'resolved', 'symbol': candidates[0]}
            return result


symbol_directory = SymbolDirectory()
