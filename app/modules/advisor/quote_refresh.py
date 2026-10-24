"""Explicit advisor access to the same public quote refresh used by finance."""

import re

from app.modules.advisor.data_command_intent import instruction_text


_REFRESH = re.compile(
    r'(?:최신\s*)?(?:(?:현재가|시세|주가)(?:를|도|만)?\s*)+'
    r'(?:새로\s*)?(?:갱신|업데이트|새로고침)(?:해\s*(?:줘|주세요)|해주세요|해라|해)[.!。]*'
)


def split_quote_refresh(query: str) -> tuple[str, bool]:
    """Remove only explicit quote-refresh clauses, preserving any CRUD consent."""
    own = instruction_text(query)
    if not own or re.search(r'[?？]|내일|나중|매일|매주|자동으로|정기적으로', own):
        return query, False
    matches = list(_REFRESH.finditer(own))
    if not matches:
        return query, False
    # Use the user's unquoted instruction, so removed quotes cannot become consent.
    remainder = _REFRESH.sub('', own).strip()
    remainder = re.sub(r'(?:[,，.;]\s*|\s+(?:그리고|하고|또|또한)\s*)+$', '', remainder).strip()
    remainder = re.sub(r'^(?:그리고|하고|또|또한)\s+', '', remainder).strip()
    return remainder, True


def quote_refresh_requested(query: str) -> bool:
    return split_quote_refresh(query)[1]


def _sharing_allowed(session, excluded):
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.context.record_privacy import record_allowed
    categories = {str(value) for value in excluded} | {str(value) for value in privacy_manager.get_excluded(session)}
    return 'investment' not in categories and record_allowed(session, 'holdings')


class _GuardedQuotes:
    """Recheck execution authority around the existing public-only gateway."""

    def __init__(self, session, client, check, excluded):
        self.session, self.client, self.check = session, client, check
        self.excluded = excluded
        self.authorization_error = None
        self.sharing_changed = False

    def authorized(self):
        try:
            if self.check:
                self.check()
        except Exception as exc:
            # The market manager catches retrieval errors. Retain a failed run
            # fence so the caller still receives the original authorization error.
            self.authorization_error = exc
            raise
        if not _sharing_allowed(self.session, self.excluded):
            self.sharing_changed = True
            raise ValueError('quote sharing changed')

    @property
    def gateway(self):
        if self.client is None:
            from app.modules.portfolio.quotes_sheet import QuotesSheet
            self.authorized()
            self.client = QuotesSheet(self.session)
        return self.client

    @property
    def source_identity(self):
        return self.gateway.source_identity

    def read(self, sheet):
        self.authorized()
        result = self.gateway.read(sheet)
        self.authorized()
        return result

    def provision(self, sheet, symbols, currencies):
        self.authorized()
        result = self.gateway.provision(sheet, symbols, currencies)
        self.authorized()
        return result


def refresh_quotes(session, *, excluded=(), authorization_check=None, write_authorization_check=None, client=None) -> dict:
    """Refresh public observations via the finance endpoint's exact policy.

    Call after committing CRUD receipts. The existing market manager commits its
    claim before network I/O and commits quote observations independently; this is
    deliberately not atomic with local CRUD. ``authorization_check`` must release
    any execution-fence lock before returning. The caller persists an attempted
    receipt before entering and must not repeat ambiguous external completion.
    """
    from app.modules.auth.google_oauth_manager import GoogleOAuthError
    from app.modules.portfolio.market_data_manager import refresh

    receipt = {'operation': 'update', 'resource': 'holdings', 'quote_refresh': True,
               'target_label': '시세 갱신'}
    if authorization_check:
        authorization_check()
    if not _sharing_allowed(session, excluded):
        return {**receipt, 'status': 'failed', 'refresh_state': 'sharing_excluded',
                'message': '보유 종목의 공유가 제한되어 상담에서 시세를 갱신하지 않았습니다.'}
    guarded = _GuardedQuotes(session, client, authorization_check, excluded)
    try:
        result = refresh(session, guarded, symbol_authorization_check=authorization_check,
                         symbol_write_authorization_check=write_authorization_check, symbol_excluded=excluded)
    except (ValueError, GoogleOAuthError):
        session.rollback()
        result = {'refresh_state': 'failed',
                  'warning': '시세를 갱신하지 못했습니다. 자산 화면에서 Google 연결과 시세 파일 상태를 확인해 주세요.'}
    finally:
        if guarded.authorization_error is not None:
            raise guarded.authorization_error
    if authorization_check:
        authorization_check()
    if guarded.sharing_changed or not _sharing_allowed(session, excluded):
        return {**receipt, 'status': 'failed', 'refresh_state': 'sharing_excluded',
                'message': '보유 종목의 공유 설정이 바뀌어 상담 시세 갱신 결과를 사용하지 않았습니다.'}
    state = result.get('refresh_state', 'failed')
    statuses = {'updated': 'saved', 'partial': 'saved', 'waiting': 'needs_input',
                'cooldown': 'needs_input', 'not_connected': 'needs_input'}
    messages = {
        'updated': '시세 조회를 완료했습니다. 제공 시각과 지연 정보는 자산 화면에서 확인할 수 있습니다.',
        'partial': '일부 종목의 시세만 갱신했습니다. 나머지 종목은 기존 값을 보존했습니다.',
        'waiting': '시세 수식을 등록했습니다. 계산 대기 중이며 아직 새 시세로 갱신되지 않았습니다.',
        'cooldown': '조회 간격 제한으로 시세를 새로 갱신하지 않았습니다.',
        'not_connected': '시세 전용 Google 파일을 연결해야 갱신할 수 있습니다. 보유 기록 저장은 별개입니다.',
    }
    return {**receipt, 'status': statuses.get(state, 'failed'), 'refresh_state': state,
            'refresh_after_seconds': result.get('refresh_after_seconds', 300),
            'message': result.get('warning') or messages.get(state, '시세 갱신에 실패했습니다. 기존 관측값은 보존했습니다.')}
