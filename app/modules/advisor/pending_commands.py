"""Resolve follow-ups against a bounded, live, unfinished local data request.

This module reads provenance only. The graph still validates the resulting command and
owns its lease/transaction; neither old assistant text nor a bare assent adds a new action.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re

from sqlalchemy import select

from app.modules.advisor.data_command_intent import instruction_text, operation_authorized
from app.modules.context.record_privacy import RECORD_CATEGORY
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import AdvisorMessage
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow
from app.modules.personal_data.personal_data_manager import RESOURCES


def _assent(text):
    text = re.sub(r'^(?:그러면|그럼)\s+', '', text)
    return bool(re.fullmatch(r'(?:응|네|예|그래|좋아|맞아|확인|오케이|알겠어|ok|yes)(?:[,，.]?\s*(?:그대로|이렇게|그렇게|그걸로|맞게|다|모두|저장|기록|반영|추가|처리|진행|해|하자|줘|주세요|해줘|해주세요|해\s*줘|해\s*주세요|부탁해|부탁해요))*[.!。]*', text, re.I)
        or re.fullmatch(r'(?:그대로|이렇게|그렇게|그걸로)\s*(?:(?:저장|기록|반영|추가|처리|진행)\s*)?(?:해\s*줘|해\s*주세요|해|하자|해주세요)[.!。]*', text))


def is_data_followup(query: str) -> bool:
    text = instruction_text(query).strip()
    from app.modules.advisor.quote_refresh import split_quote_refresh
    remainder, refresh = split_quote_refresh(text)
    if refresh:
        text = remainder.strip()
    if not text or len(text) > 2000 or re.search(r'[?？]|다른\s*질문|새로운?\s*주제|취소|하지\s*마|안\s*할래|그만', text):
        return False
    compact = re.sub(r'\s+', '', text).rstrip('.!。')
    if compact in {'아니', '아니요', '싫어', '됐어', '괜찮아'}:
        return False
    if _assent(text):
        return True
    from app.modules.advisor.data_commands import separate_position_authorized
    if separate_position_authorized(text):
        return True
    completion = re.sub(r'^(?:응|네|예|그래|좋아|맞아|확인|오케이|ok|yes)(?:[,，]\s*|\s+)(?=\S)', '', text, count=1, flags=re.I)
    # A short answer may supply a currency, named account or numeric field the
    # immediately preceding request was missing. Questions/new tasks do not count.
    if re.search(r'(?:만들어|생성|삭제|지워|조회|보여|추천|설명|조언)', completion):
        return False
    if re.fullmatch(r'(?:원화|달러|미국\s*달러|엔화|유로|KRW|USD|JPY|EUR)(?:로|이야|야|입니다|예요|이에요|해줘|해\s*줘|로\s*해\s*(?:줘|주세요))?[.!。]*', completion, re.I):
        return True
    return bool(len(completion) <= 300 and (
        re.search(r'(?:은행|계좌|통장)(?:이야|야|입니다|예요|이에요|으로|로|에서|에\s*넣어)[.!。]*$', completion)
        or re.search(r'(?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN|KRX|KOSDAQ)\s*:', completion, re.I)
        or re.search(r'\d+(?:\.\d+)?\s*(?:주|원|달러|분|초)(?:야|이야|입니다|예요|이에요|로\s*해줘|가\s*맞아)[.!。]*$', completion)))


def _sources_allowed(session, run, metadata, excluded):
    inherited = metadata.get('data_command_source_ids', [])
    if not isinstance(inherited, list) or any(not isinstance(key, int) or isinstance(key, bool) for key in inherited):
        return None
    ids = list(dict.fromkeys([*inherited,
                             run.user_message_id, run.assistant_message_id]))
    ids = [key for key in ids if isinstance(key, int) and not isinstance(key, bool)]
    if not run.user_message_id or not run.assistant_message_id:
        return None
    messages = list(session.scalars(select(AdvisorMessage).where(AdvisorMessage.id.in_(ids))))
    if len(messages) != len(ids) or any(message.conversation_id != run.conversation_id for message in messages):
        return None
    if not source_allowed(session, [{'table': 'advisor_messages', 'id': key} for key in ids], excluded):
        return None
    return ids


_REJECTED_INPUT = '요청한 변경 내용과 원문의 수치를 확인해 주세요.'
_UNINDEXED_HOLDING_INPUT = '이 항목의 수량·금액이 사용자 원문과 일치하지 않아 저장하지 않았습니다.'


def _legacy_rejections(operations):
    """Only the old extraction guard's known rejection can be reinterpreted."""
    return bool(operations) and all(
        operation.get('status') == 'needs_input' and operation.get('message') == _REJECTED_INPUT
        and operation.get('resource') in RESOURCES for operation in operations)


def _failed_legacy_refresh_followup(run, metadata, operations):
    from app.modules.advisor.quote_refresh import split_quote_refresh
    if 'data_command_validation_version' in metadata:
        return False
    query = run.input_payload.get('message', '')
    remainder, refresh = split_quote_refresh(query)
    # A lost parameter correction cannot be skipped as an empty assent.
    if not refresh or not _assent(remainder.strip()):
        return False
    commands = metadata.get('data_command_plan', [])
    if not isinstance(commands, list) or any(not isinstance(command, dict)
            or command.get('resource') != 'market-data' for command in commands):
        return False
    rejected = [operation for operation in operations if operation.get('status') == 'needs_input']
    unsupported = [operation for operation in operations if operation not in rejected]
    return (_legacy_rejections(rejected) and bool(unsupported) and all(
        operation.get('resource') == 'market-data' and operation.get('status') == 'failed'
        and operation.get('message') == '지원하지 않는 데이터 작업입니다.' for operation in unsupported))


def _holding_account_clarification(query):
    """A factual account distinction can survive a discussion before consent."""
    text = instruction_text(query).strip()
    if not text or len(query) > 600 or re.search(
            r'다른\s*질문|새로운?\s*(?:질문|주제)|만약|가정|예시|샘플|친구|동료|엄마|아빠|형|누나|'
            r'운동|러닝|날씨|이직|추천|일정|목표|대출|부채|잔액|잔고', text):
        return False
    distinction = re.search(r'(?:다른|별도(?:의)?)\s*계좌|계좌(?:가|는)?\s*(?:서로\s*)?(?:다른|다르|달라)', text)
    if not distinction:
        return False
    same_position = re.search(r'같은\s*(?:ticker|티커|종목|주식|[A-Z][A-Z0-9.:-]*)', query, re.I)
    if same_position and re.search(r'저장|기록|보유|추가', query):
        return True
    return bool(len(text) <= 100 and not re.search(r'[?？]', text) and re.fullmatch(
        r'(?:응[,，]?\s*)?계좌(?:가|는)?\s*(?:서로\s*)?(?:다른|다르|달라)[가-힣\s.!。]*', text))


def find_pending_commands(session, *, conversation_id, message_id, query, excluded):
    if not is_data_followup(query):
        return None
    from app.modules.context.privacy_manager import privacy_manager
    excluded = {str(value) for value in excluded} | {str(value) for value in privacy_manager.get_excluded(session)}
    runs = session.scalars(select(AdvisorRun).where(
        AdvisorRun.conversation_id == conversation_id,
        AdvisorRun.user_message_id < message_id,
    ).order_by(AdvisorRun.user_message_id.desc(), AdvisorRun.created_at.desc()).limit(8))
    cutoff = utcnow() - timedelta(hours=24)
    account_clarifications = []
    for run in runs:
        if run.status != 'completed' or run.created_at < cutoff:
            return None
        metadata = run.runtime_metadata or {}
        operations = (run.result or {}).get('data_operations', metadata.get('data_operations', []))
        if not isinstance(operations, list) or any(not isinstance(operation, dict) for operation in operations):
            return None
        # That release could reject an assent's refresh and echo all unresolved
        # rows without inheriting their request. Nothing succeeded, so find the
        # earlier source-checked request instead of treating the echo as authority.
        if _failed_legacy_refresh_followup(run, metadata, operations):
            continue
        pending = [operation for operation in operations
                   if isinstance(operation, dict) and operation.get('status') == 'needs_input']
        if not pending:
            # Recover old releases' lost assent turns, but stop as soon as another
            # real topic or an already successful data request intervenes.
            previous_query = run.input_payload.get('message', '')
            from app.modules.advisor.data_commands import separate_position_authorized
            account_clarification = (_holding_account_clarification(previous_query)
                                     or separate_position_authorized(previous_query))
            if operations or not (is_data_followup(previous_query) or account_clarification):
                return None
            if account_clarification:
                checked_ids = _sources_allowed(session, run, metadata, excluded)
                if checked_ids is None:
                    return None
                account_clarifications.append((previous_query, checked_ids))
            continue
        commands = metadata.get('data_command_plan', [])
        if not isinstance(commands, list) or any(not isinstance(command, dict) for command in commands):
            return None
        reextract_legacy = ('data_command_plan' in metadata and not commands
            and 'data_command_validation_version' not in metadata and _legacy_rejections(operations))
        original_query = metadata.get('data_command_query') or run.input_payload.get('message', '')
        if reextract_legacy and (not isinstance(original_query, str) or any(
                not operation_authorized(original_query, operation.get('operation')) for operation in pending)):
            return None
        legacy = 'data_command_plan' not in metadata or reextract_legacy
        if reextract_legacy:
            operations = [{**operation, 'command_index': index} for index, operation in enumerate(operations)]
        if not legacy:
            command_indices = [command.get('command_index', index) for index, command in enumerate(commands)]
            if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in command_indices):
                return None
            indices = set(command_indices)
            if len(indices) != len(command_indices):
                return None
            # Version 2 stored successful commands but could omit a rejected row's
            # slot. Recover only its original ticker, never its rejected numbers.
            if commands and isinstance(original_query, str):
                from app.modules.advisor.command_grounding import legacy_command_grounded
                used = indices | {operation['command_index'] for operation in operations
                    if isinstance(operation.get('command_index'), int) and not isinstance(operation['command_index'], bool)}
                recovered_symbols = set()
                restored = []
                for operation in operations:
                    label = operation.get('target_label')
                    if (operation.get('status') == 'needs_input' and operation.get('resource') == 'holdings'
                            and operation.get('operation') in {'create', 'update'} and 'command_index' not in operation
                            and operation.get('message') == _UNINDEXED_HOLDING_INPUT
                            and isinstance(label, str) and len(label) <= 32
                            and re.fullmatch(r'(?:[A-Z][A-Z0-9]*:)?[A-Z0-9][A-Z0-9.-]*', label)):
                        symbol = label.rsplit(':', 1)[-1]
                        skeleton = {'operation': operation['operation'], 'resource': 'holdings',
                                    'selector': {}, 'values': {'symbol': symbol}, 'reextract': True}
                        next_index = next((index for index in range(12) if index not in used), None)
                        if (symbol not in recovered_symbols and next_index is not None
                                and legacy_command_grounded(original_query, skeleton)):
                            skeleton['command_index'] = next_index
                            commands = [*commands, skeleton]
                            operation = {**operation, 'command_index': next_index}
                            used.add(next_index)
                            indices.add(next_index)
                            recovered_symbols.add(symbol)
                    restored.append(operation)
                operations = restored
            pending = [operation for operation in operations
                       if operation.get('status') == 'needs_input'
                       and isinstance(operation.get('command_index'), int)
                       and not isinstance(operation['command_index'], bool)
                       and operation['command_index'] in indices]
            if not pending:
                return None
            operations = [operation for operation in operations
                          if operation.get('status') != 'needs_input' or operation in pending]
        if any(not isinstance(item, dict) or not isinstance(item.get('resource'), str)
               for item in [*operations, *commands]):
            return None
        resources = {item.get('resource') for item in [*operations, *commands]}
        if any(name not in RESOURCES for name in resources):
            return None
        if any(RECORD_CATEGORY.get(RESOURCES[name].handler.model.__tablename__, 'investment') in excluded
               for name in resources):
            return None
        source_ids = _sources_allowed(session, run, metadata, excluded)
        if source_ids is None:
            return None
        snapshot_id = (run.result or {}).get('context_snapshot_id')
        if snapshot_id is not None and not isinstance(snapshot_id, str):
            return None
        if snapshot_id and not source_allowed(session, [{'table':'context_snapshots', 'id':snapshot_id}], excluded):
            return None
        answer = session.get(AdvisorMessage, run.assistant_message_id)
        if not isinstance(original_query, str) or not original_query.strip():
            return None
        authorized_query = original_query
        if account_clarifications:
            if {operation['resource'] for operation in pending} != {'holdings'}:
                return None
            pending_indices = {operation.get('command_index') for operation in pending}
            pending_symbols = {str(group.get('symbol') or group.get('ticker')).upper().split(':')[-1]
                for index, command in enumerate(commands) if command.get('command_index', index) in pending_indices
                for group in (command.get('values', {}), command.get('selector', {}))
                if group.get('symbol') or group.get('ticker')}
            for clarification_query, checked_ids in reversed(account_clarifications):
                mentioned = set(re.findall(r'(?<![A-Za-z0-9.:-])(?:[A-Z][A-Z0-9]*:)?([A-Z][A-Z0-9.:-]+)(?![A-Za-z0-9.:-])', clarification_query)) - {'TICKER', 'USD', 'KRW'}
                if mentioned and any(symbol.split(':')[-1] not in pending_symbols for symbol in mentioned):
                    return None
                if not source_allowed(session, [{'table': 'advisor_messages', 'id': key} for key in checked_ids], excluded):
                    return None
                source_ids = list(dict.fromkeys([*source_ids, *checked_ids]))
                authorized_query += '\n사용자 계좌 구분 설명: ' + clarification_query
        return {'commands': commands, 'query': authorized_query, 'original_query': original_query, 'operations': operations,
                'source_message_ids': source_ids, 'source_snapshot_id': snapshot_id,
                'clarification': answer.content if answer else '', 'legacy': legacy,
                'allow_data_recording': bool(metadata.get('data_command_recording_allowed',
                    run.input_payload.get('allow_data_recording', False)))}
    return None


def _same_identity(field, original, candidate):
    if field == 'symbol' and isinstance(original, str) and isinstance(candidate, str):
        if ':' in original and ':' in candidate:
            return original.upper() == candidate.upper()
        return original.upper().split(':')[-1] == candidate.upper().split(':')[-1]
    return original == candidate


NUMERIC_FIELDS = frozenset({'quantity', 'avg_cost', 'balance', 'amount', 'value', 'monthly_payment',
    'interest_rate', 'delta', 'duration_seconds', 'estimate_minutes', 'weight', 'current_value', 'target_value'})
FIELD_WORDS = {
    'quantity': r'수량|보유량|주식\s*수|총\s*보유',
    'avg_cost': r'평균\s*(?:매입가|매수가|매입단가|매수단가)|평단가|평단|매입가|매수가|매입단가|원가',
    'balance': r'잔액|잔고', 'amount': r'금액|지출액|수입액', 'value': r'평가액|자산\s*가액|가치',
    'monthly_payment': r'월\s*(?:상환|납부|납입|지급)|상환액', 'interest_rate': r'금리|이자율',
    'delta': r'증감|추가|차감|증가|감소', 'duration_seconds': r'운동\s*시간|소요\s*시간',
    'estimate_minutes': r'예상\s*시간', 'weight': r'가중치|비중',
    'current_value': r'현재\s*값|현재\s*진행', 'target_value': r'목표\s*값|목표량',
}
NUMBER = re.compile(r'(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:억|만|천)?')


def _canonical_fields(values):
    if not isinstance(values, dict):
        return None
    result = dict(values)
    for alias, field in (('ticker', 'symbol'), ('label', 'name')):
        if alias in result:
            value = result.pop(alias)
            if field in result and not _same_identity(field, value, result[field]):
                return None
            result.setdefault(field, value)
    return result


def _decimal(value):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(',', ''))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def _same_value(field, original, candidate):
    if field in {'current_value', 'target_value'} and original == candidate:
        return True  # Goal progress also supports user-entered free-form text.
    if field in NUMERIC_FIELDS or field.endswith('_id'):
        left, right = _decimal(original), _decimal(candidate)
        return left is not None and right is not None and left == right
    if isinstance(original, bool) or isinstance(candidate, bool):
        return isinstance(original, bool) and isinstance(candidate, bool) and original is candidate
    if field == 'currency' and isinstance(original, str) and isinstance(candidate, str):
        return original.upper() == candidate.upper()
    return _same_identity(field, original, candidate)


def _explicit_correction(field, value, clarification):
    text = instruction_text(clarification)
    if field == 'currency':
        words = {'KRW': r'원화|한국\s*원', 'USD': r'달러|미국\s*달러',
                 'JPY': r'엔화|일본\s*엔', 'EUR': r'유로'}
        code = str(value).upper()
        return bool(re.search(r'(?<![A-Za-z])' + re.escape(code) + r'(?![A-Za-z])', text, re.I)
                    or code in words and re.search(words[code], text))
    if field in NUMERIC_FIELDS:
        desired = _decimal(value)
        if desired is None:
            return False
        markers = [(match.start(), key) for key, pattern in FIELD_WORDS.items()
                   for match in re.finditer(pattern, text)]
        for match in NUMBER.finditer(text):
            raw = match.group().strip()
            suffix = raw[-1:]
            number = _decimal(raw[:-1] if suffix in {'억', '만', '천'} else raw)
            if number is None:
                continue
            number *= {'억': Decimal(100000000), '만': Decimal(10000), '천': Decimal(1000)}.get(suffix, Decimal(1))
            if number != desired:
                continue
            # The stock unit itself identifies quantity; money units alone do not
            # distinguish balance, average cost and monthly payment.
            if field == 'quantity' and re.match(r'\s*주', text[match.end():]):
                return True
            previous = [(position, key) for position, key in markers
                        if position <= match.start() and match.start() - position <= 40]
            if previous and max(previous)[1] == field:
                return True
        return False
    if field == 'kind':
        if not isinstance(value, str):
            return False
        names = {'checking': r'입출금|보통\s*예금', 'savings': r'적금|저축', 'deposit': r'정기\s*예금',
                 'cash': r'현금', 'brokerage_cash': r'예수금', 'pension': r'연금', 'other': r'기타'}
        return bool(re.search(r'종류|유형|계좌|통장', text) and
                    (str(value) in text or value in names and re.search(names[value], text)))
    return bool(field in text and str(value) in text)


def resolution_allowed(original: dict, candidate: dict, clarification: str = '', *, authorization_query: str | None = None) -> bool:
    if original.get('resource') != candidate.get('resource'):
        return False
    operation = original.get('operation')
    from app.modules.advisor.data_commands import separate_position_authorized
    separate_create = (original.get('resource') == 'holdings' and operation == 'update'
                       and candidate.get('operation') == 'create' and candidate.get('separate_position') is True
                       and separate_position_authorized(authorization_query if authorization_query is not None else clarification))
    if candidate.get('operation') != operation and not (operation == 'create' and candidate.get('operation') == 'update') and not separate_create:
        return False
    old_selector = _canonical_fields(original.get('selector') or {})
    new_selector = _canonical_fields(candidate.get('selector') or {})
    old_values = _canonical_fields(original.get('values') or {})
    new_values = _canonical_fields(candidate.get('values') or {})
    if not all(isinstance(value, dict) for value in (old_selector, new_selector, old_values, new_values)):
        return False
    if separate_create:
        symbol = old_selector.get('symbol') or old_values.get('symbol')
        if not symbol or not _same_identity('symbol', symbol, new_values.get('symbol')):
            return False
    # Existing target filters may be narrowed, never silently replaced or dropped.
    for field, value in old_selector.items():
        if separate_create and field in {'id', 'account_id'}:
            continue
        supplied = new_values.get(field) if separate_create else new_selector.get(field)
        if supplied is None or not _same_identity(field, value, supplied):
            return False
    if operation == 'create':
        identity_fields = {'holdings': ('symbol', 'account_id'), 'accounts': ('name',),
            'other-assets': ('name',), 'liabilities': ('name',), 'workout-logs': ('activity', 'performed_on'),
            'tasks': ('title',), 'goals': ('title',), 'job-applications': ('company', 'role'),
            'interviews': ('application_id', 'stage'), 'career-criteria': ('name',),
            'calendar-events': ('title',), 'planned-expenses': ('name',),
            'cashflow-entries': ('occurred_on', 'kind')}.get(original.get('resource'), ())
        for field in identity_fields:
            if old_values.get(field) is None:
                continue
            supplied = new_selector.get(field, new_values.get(field))
            if supplied is None or not _same_identity(field, old_values[field], supplied):
                return False
    for field, value in old_values.items():
        if value is None:
            continue  # Missing input may be filled by the clarification.
        supplied = new_values.get(field, new_selector.get(field))
        if separate_create and field == 'delta' and supplied is None:
            supplied = new_values.get('quantity')
        if separate_create and field == 'account_id' and supplied is None:
            continue
        if field == 'quantity' and supplied is None and candidate.get('operation') == 'update':
            supplied = new_values.get('delta')
        if supplied is None:
            return False
        if not _same_value(field, value, supplied) and not _explicit_correction(field, supplied, clarification):
            return False
    return True
