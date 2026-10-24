"""Conservative reconstruction of legacy commands whose typed plan was not stored.

Current plans retain their original typed fields. Old receipts do not, so a fresh
model extraction must prove its target and values against one original input row.
"""
import re
from decimal import Decimal, InvalidOperation

from app.modules.advisor.data_command_intent import factual_write_authorized, instruction_text, operation_authorized

_NUMBER = r'[-+]?\d[\d,]*(?:\.\d+)?'
_CURRENCIES = {'USD', 'KRW', 'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF', 'CNY'}
_NON_SYMBOLS = _CURRENCIES | {'NASDAQ', 'NYSE', 'NYSEARCA', 'NYSEAMERICAN', 'KRX', 'KOSDAQ', 'ETF', 'USDOLLAR'}
_AVERAGE = r'(?:평균\s*(?:매입가|매수가|매입단가|매수단가)|평단가|평단|매입가|매수가|매입단가|원가)'
_MONEY_FIELDS = {'balance', 'amount', 'value', 'avg_cost', 'monthly_payment', 'interest_rate', 'quantity', 'delta'}
_MARKERS = {
    'balance': r'잔액|잔고|대출금|부채액', 'amount': r'금액|지출액|수입액', 'value': r'평가액|자산\s*가액|가치',
    'monthly_payment': r'월\s*(?:상환|납부|납입|지급)|상환액', 'interest_rate': r'금리|이자율',
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        result = Decimal(str(value).replace(',', ''))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def _amount(raw, unit=''):
    number = _number(raw)
    return None if number is None else number * {'억': Decimal(100000000), '만': Decimal(10000), '천': Decimal(1000)}.get(unit, Decimal(1))


def _money(scope):
    amounts = set()
    for match in re.finditer(r'[$₩€¥]\s*(' + _NUMBER + r')|(' + _NUMBER + r')\s*(억|만|천)?\s*(?:달러|원|유로|엔|USD|KRW|EUR|JPY)(?![A-Za-z])', scope, re.I):
        value = _amount(match[1]) if match[1] is not None else _amount(match[2], match[3] or '')
        if value is not None:
            amounts.add(value)
    return amounts


def _marked(scope, field):
    pattern = _AVERAGE if field == 'avg_cost' else _MARKERS.get(field)
    if pattern is None:
        return set()
    result = set()
    for marker in re.finditer(pattern, scope):
        # A field marker binds only its immediately following number. Do not
        # borrow another field's number from a later clause.
        match = re.match(r'(?:\s|은|는|이|가|를|:|=|[$₩€¥]){0,12}(' + _NUMBER + r')\s*(억|만|천)?', scope[marker.end():])
        if match:
            result.add(_amount(match[1], match[2] or ''))
    return result


def _currency_allowed(scope, value):
    if value is None:
        return True
    if not isinstance(value, str) or value.upper() not in _CURRENCIES:
        return False
    markers = {'USD': r'\$|달러|(?<![A-Za-z])USD(?![A-Za-z])',
        'KRW': r'₩|원화|\d\s*(?:억|만|천)?\s*원|(?<![A-Za-z])KRW(?![A-Za-z])',
        'EUR': r'€|유로|(?<![A-Za-z])EUR(?![A-Za-z])',
        'JPY': r'¥|엔화|\d\s*엔|(?<![A-Za-z])JPY(?![A-Za-z])'}
    supplied = {code for code in _CURRENCIES if re.search(markers.get(code,
        r'(?<![A-Za-z])' + code + r'(?![A-Za-z])'), scope, re.I)}
    # Missing currency may be filled by the confirmed clarification. An explicit
    # original currency can never be replaced by a bare affirmative answer.
    return not supplied or supplied == {value.upper()}


def _explicit_ids(scope, selector, values):
    for field, value in {**selector, **values}.items():
        if (field == 'id' or field.endswith('_id')) and value is not None:
            if _number(value) is None or not re.search(r'\b' + re.escape(field) + r'\s*[:=#]?\s*' + re.escape(str(value)) + r'(?!\d)', scope, re.I):
                return False
    return True


def _holding_scope(text, symbol):
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    symbol = symbol.strip().upper()
    exchange, _, bare = symbol.rpartition(':')
    bare = bare or symbol
    pattern = re.compile(r'(?<![A-Za-z0-9_.:-])(?:(?P<exchange>[A-Za-z][A-Za-z0-9]*):)?' + re.escape(bare) + r'(?![A-Za-z0-9_.:-])', re.I)
    occurrences = list(pattern.finditer(text))
    if len(occurrences) != 1:
        return None
    match = occurrences[0]
    if exchange and match['exchange'] and exchange != match['exchange'].upper():
        return None
    tail = text[match.end():]
    # A following stock symbol starts a different row even when the user uses
    # commas instead of newlines. Currency codes and exchange names are metadata.
    other = next((token for token in re.finditer(r'(?<![A-Za-z0-9_.:-])(?:[A-Z][A-Z0-9]*:)?[A-Z][A-Z0-9._-]*(?![A-Za-z0-9_.:-])', tail)
                  if token.group().rsplit(':', 1)[-1] not in _NON_SYMBOLS), None)
    return tail[:other.start()] if other else tail


def _holdings(text, selector, values):
    selector, values = dict(selector), dict(values)
    for fields in (selector, values):
        if 'ticker' in fields:
            if 'symbol' in fields and fields['symbol'] != fields['ticker']:
                return False
            fields['symbol'] = fields.pop('ticker')
        if 'symbol' in fields:
            if not isinstance(fields['symbol'], str) or not fields['symbol'].strip():
                return False
            fields['symbol'] = fields['symbol'].strip().upper()
    symbol = selector.get('symbol', values.get('symbol'))
    if selector.get('symbol') and values.get('symbol'):
        left, right = selector['symbol'], values['symbol']
        if left.rsplit(':', 1)[-1] != right.rsplit(':', 1)[-1] or ':' in left and ':' in right and left != right:
            return False
        # Retain an explicit exchange from either location when checking the
        # original query; an alias must not hide a change to a qualified identity.
        symbol = left if ':' in left else right
    scope = _holding_scope(text, symbol)
    if scope is None or not _explicit_ids(scope, selector, values) or not _currency_allowed(scope, values.get('currency', selector.get('currency'))):
        return False
    if any(field in _MONEY_FIELDS - {'quantity', 'avg_cost', 'delta'} for field in values):
        return False
    shares = {_amount(match[1]) for match in re.finditer(r'(?<![\d,.+−–-])(' + _NUMBER + r')\s*주', scope)}
    if len(shares) != 1:
        return False
    for field in ('quantity', 'delta'):
        if values.get(field) is None:
            continue
        number = _number(values[field])
        if number is None or abs(number) not in shares:
            return False
        if field == 'quantity' and number < 0:
            return False
        if field == 'delta':
            decrease = bool(re.search(r'팔|매도|차감|감소|줄|빼', scope))
            increase = bool(re.search(r'추가|더\s*(?:있|샀|매수|보유|갖)|매수', scope))
            if number < 0 and not decrease or number >= 0 and decrease or number >= 0 and not (increase or '추가' in text):
                return False
    if values.get('avg_cost') is not None:
        if not re.search(_AVERAGE, text):
            return False
        cost = _number(values['avg_cost'])
        prices = _marked(scope, 'avg_cost') or _money(scope)
        if cost is None or len(prices) != 1 or prices != {cost}:
            return False
    return True


def _named_scope(text, name, account=False):
    if not isinstance(name, str):
        return None
    if account:
        # Account type is a structured field, not part of its user-given name.
        # Preserve distinctive words while accepting "급여 입출금 통장" → "급여 통장".
        kinds = r'입출금|보통\s*예금|정기\s*예금|예금|적금|저축'
        name = re.sub(kinds, '', name)
    compact = re.sub(r'\s+', '', name)
    distinctive = re.sub(r'계좌|통장|은행|내', '', compact)
    if len(distinctive) < 2:
        return None
    pattern = re.compile(r'\s*'.join(re.escape(char) for char in compact))
    scopes = [clause for clause in re.split(r'[;\n!?。]|(?<!\d)[,.]|[,.](?!\d)', text)
              if pattern.search(re.sub(kinds, '', clause) if account else clause)]
    return scopes[0] if len(scopes) == 1 else None


def _named(text, resource, selector, values):
    identities = {'accounts': 'name', 'liabilities': 'name', 'other-assets': 'name', 'planned-expenses': 'name',
        'tasks': 'title', 'goals': 'title', 'calendar-events': 'title', 'career-criteria': 'name',
        'job-applications': 'company', 'workout-logs': 'activity', 'cashflow-entries': 'description'}
    field = identities.get(resource)
    if field is None:
        return False
    identity = selector.get(field, values.get(field))
    scope = _named_scope(text, identity, account=resource == 'accounts')
    if scope is None or not _explicit_ids(scope, selector, values) or not _currency_allowed(scope, values.get('currency', selector.get('currency'))):
        return False
    if resource == 'accounts':
        kinds = {'checking': r'입출금|보통\s*예금', 'savings': r'적금|저축', 'deposit': r'정기\s*예금',
            'brokerage_cash': r'예수금', 'cash': r'현금', 'pension': r'연금', 'other': r'기타'}
        for fields in (selector, values):
            if fields.get('kind') is not None and (not isinstance(fields['kind'], str)
                    or fields['kind'] not in kinds or not re.search(kinds[fields['kind']], scope)):
                return False
    for boolean_field, value in {**selector, **values}.items():
        if isinstance(value, bool):
            markers = {
                ('is_liquid', True): r'유동성\s*(?:있음|있어)|생활비로\s*(?:사용|쓸)\s*(?:가능|수\s*있)|현금화\s*가능',
                ('is_liquid', False): r'유동성\s*(?:없음|없어)|생활비로\s*(?:사용|쓸)\s*(?:불가|수\s*없)|현금화\s*불가',
                ('all_day', True): r'종일(?!\s*(?:아님|아니|말고))', ('all_day', False): r'종일\s*(?:아님|아니|말고)',
            }
            if ((boolean_field, value) not in markers or not re.search(markers[boolean_field, value], scope)
                    or re.search(markers[boolean_field, not value], scope)):
                return False
    if values.get(field) != identity and values.get(field) is not None and str(values[field]) not in scope:
        return False
    primary = {'accounts': 'balance', 'liabilities': 'balance', 'other-assets': 'value',
        'planned-expenses': 'amount', 'cashflow-entries': 'amount'}.get(resource)
    allowed = {primary, 'delta'} if primary else set()
    if resource == 'liabilities':
        allowed |= {'monthly_payment', 'interest_rate'}
    for key in _MONEY_FIELDS & values.keys():
        if key not in allowed or values[key] is None:
            if values[key] is None:
                continue
            return False
        number = _number(values[key])
        field = primary if key == 'delta' else key
        candidates = _marked(scope, field)
        if not candidates and field == primary:
            candidates = _money(scope)
        if number is None or len(candidates) != 1 or abs(number) not in candidates:
            return False
        if key == 'delta' and not re.search(r'추가|입금|출금|차감|감소|증가|더|빼', scope):
            return False
    # Other numeric or progress fields need their own unambiguous textual input;
    # unknown legacy transformations stay pending rather than inventing values.
    for field in ('duration_seconds', 'estimate_minutes', 'weight', 'current_value', 'target_value'):
        if values.get(field) is not None and str(values[field]) not in scope:
            return False
    return True


def legacy_command_grounded(query: str, command: dict) -> bool:
    if not isinstance(query, str) or not isinstance(command, dict):
        return False
    text = instruction_text(query)
    resource, operation = command.get('resource'), command.get('operation')
    selector, values = command.get('selector', {}), command.get('values', {})
    if (not text.strip() or not isinstance(resource, str) or not isinstance(operation, str)
            or not isinstance(selector, dict) or not isinstance(values, dict)
            or not operation_authorized(text, operation) or not factual_write_authorized(text, resource)):
        return False
    if resource == 'holdings':
        return _holdings(text, selector, values)
    return _named(text, resource, selector, values)
