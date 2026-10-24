"""User-message authority for the bounded personal data command path."""

import re


def _instruction(query: str) -> str:
    # Only the user's own instruction can authorize a write, never quoted material.
    text = re.sub(r'```[\s\S]*?```|"[^"\n]*"|“[^”\n]*”|「[^」]*」|\'[^\'\n]*\'', '', query)
    if re.search(r'하지\s*마|하지\s*말|하지\s*않|저장\s*금지|기록\s*금지|(?:기록|저장|추가|수정|삭제|변경)\s*하지', text):
        return ''
    # Meta questions and hypothetical changes are discussion, not execution consent.
    text = re.sub(r'[^.!?。\n]*(?:라고\s*(?:말|하|적|써)|라는\s*(?:말|문구)|한다면|할까|하면|한다면|바꾸면|수정하면)[^.!?。\n]*', '', text)
    return text


def instruction_text(query: str) -> str:
    """The user's own instruction, excluding quotation and hypothetical scope."""
    return _instruction(query)


CREATE = re.compile(r'(?:기록|저장|등록|추가|입력|생성)(?:해|하자|해줘|해주세요|해\s*줘|해\s*주세요|하겠)|(?:만들어|넣어|적어)\s*(?:줘|주세요)')
UPDATE = re.compile(r'(?:수정|변경|갱신|업데이트|정정|반영)(?:해|하자|해\s*줘|해\s*주세요)|(?:바꿔|고쳐)\s*(?:줘|주세요)')
DELETE = re.compile(r'(?:삭제|제거)(?:해|하자|해\s*줘|해\s*주세요)|(?:지워|없애)\s*(?:줘|주세요)')
READ = re.compile(r'(?:조회|확인)(?:해|하자)|(?:보여|찾아|불러)\s*(?:줘|주세요)|목록')

def command_requested(query: str) -> bool:
    text = _instruction(query)
    return any(pattern.search(text) for pattern in (CREATE, UPDATE, DELETE, READ))


def observation_authorized(query: str) -> bool:
    """Conservative eligibility after the user opts in to recording observations."""
    text = _instruction(query)
    if not text or re.search(r'[?？]|만약|가정|예시|샘플|내일|예정|계획|하려고|뛰려고|뛸|있다면|있으면|(?:친구|동료|엄마|아빠|형|누나)(?:가|는|의)', text):
        return False
    topic = re.search(r'뛰|달렸|걸었|운동|완주|\d+\s*(?:km|킬로|미터)|잔액|잔고|계좌|통장|보유|주식|[A-Z0-9.:_-]+\s*\d+\s*주', text, re.I)
    fact = re.search(r'있어|있다|있네|있음|보유|가지고|나왔|뛰었|달렸|걸었|완주했|운동.*했|완료했', text)
    return bool(topic and fact and re.search(r'\d', text))


def factual_write_authorized(query: str, resource: str) -> bool:
    if resource not in {'workout-logs', 'accounts', 'holdings', 'liabilities', 'other-assets', 'cashflow-entries'}:
        return True
    text = _instruction(query)
    return bool(text) and not re.search(
        r'만약|가정|예시|샘플|예정|계획|하려고|뛰려고|뛸|있다면|있으면|'
        r'(?:친구|동료|엄마|아빠|형|누나)(?:가|는|의)|'
        r'(?:내일|다음\s*주).*(?:뛰|살|매수|매도|입금|지출)|'
        r'(?:매수|매도|입금|지출)할\s*거', text)


def operation_authorized(query: str, operation: str) -> bool:
    text = _instruction(query)
    if operation == 'read':
        return bool(READ.search(text) or CREATE.search(text) or UPDATE.search(text) or DELETE.search(text))
    if operation == 'create':
        return bool(CREATE.search(text))
    if operation == 'update':
        return bool(UPDATE.search(text) or CREATE.search(text))
    return operation == 'delete' and bool(DELETE.search(text))


_WRITE_SCOPES = {
    'accounts': r'계좌|통장|잔액|잔고',
    'holdings': r'주식|보유\s*종목|종목|포트폴리오',
    'liabilities': r'부채|대출|빚',
    'other-assets': r'기타\s*자산|부동산|자동차',
    'cashflow-entries': r'가계부|현금흐름|지출|수입',
    'planned-expenses': r'예정\s*(?:지출|결제)|지출\s*예정',
    'job-applications': r'채용\s*지원|입사\s*지원|지원\s*(?:현황|내역|목록)',
    'interviews': r'면접',
    'career-criteria': r'(?:커리어|이직|지원)\s*기준',
    'calendar-events': r'일정|약속|이벤트',
    'tasks': r'할\s*일|태스크|투두|작업\s*목록',
    'goals': r'목표',
    'workout-logs': r'운동|러닝|달리기|수영|라이딩|훈련|산책',
}
_BULK_WRITE = re.compile(
    r'이것들|이(?:거|것|걸)(?:도)?|이\s*(?:내용|항목)|아래|다음(?!\s*(?:달|주|날|해|월|분기))|'
    r'위(?:의)?(?![가-힣])|목록|내역|전부|모두|일괄|'
    r'(?:^|\s)다\s*(?:저장|기록|등록|추가|입력|수정|변경)'
)


def _write_scopes(text):
    matches = [(match.start(), match.end(), name) for name, pattern in _WRITE_SCOPES.items()
               for match in re.finditer(pattern, text)]
    scopes = {name for _, _, name in matches}
    # Compound domain names are more specific than a noun within that name.
    if 'planned-expenses' in scopes and not re.search(r'가계부|현금흐름', text):
        scopes.discard('cashflow-entries')
    if 'interviews' in scopes and re.search(r'면접\s*일정', text):
        scopes.discard('calendar-events')
    if 'goals' in scopes and re.search(r'(?:운동|러닝|달리기|수영|훈련)\s*목표', text):
        scopes.discard('workout-logs')
    matches = sorted(item for item in matches if item[2] in scopes)
    if len(scopes) > 1:
        # A nearby statement about another domain is not a list of targets.
        # Explicit conjunctions still support "계좌와 주식 목록을 모두 저장".
        last_start, _, last_scope = matches[-1]
        connected = {last_scope}
        for start, end, scope in reversed(matches[:-1]):
            if scope == last_scope:
                last_start = start
                continue
            if not re.search(r'[,·]|와|과|및|하고', text[end:last_start]):
                break
            connected.add(scope)
            last_start, last_scope = start, scope
        return connected
    return scopes


def shared_write_authorized(query: str, source_quote: str, resource: str, operation: str) -> bool:
    """Bind list rows to an explicit shared directive for their own resource.

    This supplements a row's own directive; it never grants delete permission or
    lets an unrelated fact borrow another domain's save verb.
    """
    if operation not in {'create', 'update'} or resource not in _WRITE_SCOPES:
        return False
    own = instruction_text(re.sub(r'"[^"]*"|“[^”]*”|「[^」]*」|\'[^\']*\'', '', query))
    quote = source_quote.strip()
    if (not quote or quote not in own or quote != instruction_text(quote).strip()
            or re.search(r'[?？]|만약|가정|예시|샘플', own)
            or not factual_write_authorized(quote, resource)):
        return False
    boundaries = [0, *(match.end() for match in re.finditer(r'\n+|[!?。]+|(?<!\d)\.(?!\d)', own)), len(own)]
    clauses = [(start, end, own[start:end]) for start, end in zip(boundaries, boundaries[1:])]
    quote_start, quote_end = own.index(quote), own.index(quote) + len(quote)
    quote_scopes = _write_scopes(quote)
    for index, (start, end, clause) in enumerate(clauses):
        if not _BULK_WRITE.search(clause) or not operation_authorized(clause, operation):
            continue
        # Another explicit operation bounds this list in either direction.
        if any(command_requested(other) for other_start, other_end, other in clauses
               if other_start != start and (
                   quote_end <= other_start < start or end <= other_start < quote_start)):
            continue
        scopes = _write_scopes(clause)
        if not scopes and index:
            # "주식이 더 있어. 이것들 다 저장해줘" keeps its immediate subject.
            previous = clauses[index - 1][2]
            if not command_requested(previous):
                scopes = _write_scopes(previous)
        if not scopes:
            scopes = quote_scopes
            if not scopes and re.search(r'[A-Z][A-Z0-9.:-]*.*\d+(?:\.\d+)?\s*주', quote):
                scopes = {'holdings'}
        if resource not in scopes:
            continue
        if quote_scopes and resource not in quote_scopes and resource != 'goals':
            continue
        return True
    return False


def direct_write_authorized(source_quote: str, resource: str, operation: str) -> bool:
    """A whole-message citation still binds writes to the instructed domain."""
    own = instruction_text(source_quote)
    if not operation_authorized(own, operation):
        return False
    if operation not in {'create', 'update', 'delete'}:
        return True
    if operation in {'create', 'update'}:
        # "운동 기록하고 계좌도 저장해줘" contains two explicit actions.
        # Keep their domains separate while recognizing the coordinated first verb.
        own = re.sub(r'((?:기록|저장|등록|추가|입력|생성))하고(?!\s*(?:싶|있|나서|보니))\s+',
                     r'\1해줘. ', own)
    clauses = re.split(r'\n+|[!?。]+|(?<!\d)\.(?!\d)', own)
    all_scopes = _write_scopes(own)
    for index, clause in enumerate(clauses):
        if not operation_authorized(clause, operation):
            continue
        scopes = _write_scopes(clause)
        if not scopes and index:
            scopes = _write_scopes(clauses[index - 1])
        if resource in scopes or not scopes and len(all_scopes) <= 1 and (not all_scopes or resource in all_scopes):
            return True
    return False
