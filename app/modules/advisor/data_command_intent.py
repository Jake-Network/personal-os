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
