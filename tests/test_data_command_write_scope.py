import pytest

from app.modules.advisor.data_command_intent import shared_write_authorized


def test_bulk_holding_header_authorizes_each_unadorned_source_line():
    row = 'NASDAQ:TEST $12.50 8주'
    query = '나 주식 다른 거 더 있거든 이것들 다 저장해줘\n' + row + '\nKRX:000001 3000원 2주'
    assert shared_write_authorized(query, row, 'holdings', 'create')
    assert shared_write_authorized(query, row, 'holdings', 'update')


@pytest.mark.parametrize('resource,header,row', [
    ('accounts', '아래 계좌 목록을 모두 저장해줘', '합성 급여통장 300만원'),
    ('liabilities', '대출 목록을 모두 기록해줘', '합성 은행 500만원'),
    ('other-assets', '아래 기타 자산을 전부 저장해줘', '합성 자동차 100만원'),
    ('cashflow-entries', '아래 가계부 내역을 다 기록해줘', '합성 식비 12000원'),
    ('planned-expenses', '아래 예정 지출을 모두 등록해줘', '합성 보험료 다음 달 5만원'),
    ('job-applications', '채용 지원 목록을 전부 저장해줘', '합성 회사 데이터 엔지니어'),
    ('interviews', '아래 면접 목록을 모두 등록해줘', '합성 회사 내일 10시'),
    ('career-criteria', '다음 커리어 기준을 모두 기록해줘', '연봉 협의 가능'),
    ('calendar-events', '아래 일정 목록을 모두 등록해줘', '합성 약속 내일 3시'),
    ('tasks', '아래 할 일 목록을 모두 등록해줘', '합성 보고서 작성'),
    ('goals', '아래 목표 목록을 모두 등록해줘', '합성 영어 공부'),
    ('workout-logs', '아래 운동 기록들을 모두 저장해줘', '합성 러닝 45분'),
])
def test_shared_headers_are_resource_scoped(resource, header, row):
    assert shared_write_authorized(header + '\n' + row, row, resource, 'create')


@pytest.mark.parametrize('query,quote,resource', [
    ('계좌 잔액300만원 있어. 오늘 운동45분 기록해줘', '계좌 잔액300만원 있어', 'accounts'),
    ('계좌 잔액300만원 있어. 오늘 운동45분 모두 기록해줘', '계좌 잔액300만원 있어', 'accounts'),
    ('아래 운동 기록들을 모두 저장해줘\n합성 러닝45분', '합성 러닝45분', 'accounts'),
    ('나 주식 더 있거든 이것들 다 저장해줘\nNASDAQ:TEST $12.50 8주', 'NASDAQ:TEST $12.50 8주', 'accounts'),
    ('계좌 잔액300만원 있어. 아래 운동 기록들을 모두 저장해줘\n합성 러닝45분', '계좌 잔액300만원 있어', 'accounts'),
    ('계좌 내역 모두 저장해줘\n합성 통장 300만원\n오늘 운동 기록들을 모두 저장해줘\n합성 러닝45분', '합성 러닝45분', 'accounts'),
    ('계좌 내역 모두 저장해줘\n합성 통장 300만원', '합성 통장 300만원', 'fx-rates'),
])
def test_unrelated_domains_do_not_borrow_a_write_directive(query, quote, resource):
    assert not shared_write_authorized(query, quote, resource, 'create')


@pytest.mark.parametrize('query,quote', [
    ('"계좌 내역 모두 저장해줘\n합성 통장300만원"', '합성 통장300만원'),
    ('만약 계좌 내역 모두 저장해줘\n합성 통장300만원', '합성 통장300만원'),
    ('계좌 내역 모두 저장해줘?\n합성 통장300만원', '합성 통장300만원'),
    ('계좌 내역 모두 저장하지 마\n합성 통장300만원', '합성 통장300만원'),
    ('계좌 내역 모두 저장해줘\n합성 통장300만원', '없는 통장900만원'),
])
def test_shared_write_remains_user_authorized_and_grounded(query, quote):
    assert not shared_write_authorized(query, quote, 'accounts', 'create')


def test_shared_create_permission_never_authorizes_delete():
    row = '합성 급여통장 300만원'
    assert not shared_write_authorized('아래 계좌 목록을 모두 저장해줘\n' + row, row, 'accounts', 'delete')


def test_adjacent_fact_without_sentence_punctuation_is_not_a_target_list():
    row = '계좌 잔액300만원 있어'
    assert not shared_write_authorized(row + ' 오늘 운동45분 모두 기록해줘', row, 'accounts', 'create')


def test_explicit_mixed_domain_list_and_trailing_consent_remain_supported():
    account = '합성 계좌 잔액300만원'
    stock = 'NASDAQ:TEST $12.50 8주'
    query = '계좌와 주식 목록을 모두 저장해줘\n' + account + '\n' + stock
    assert shared_write_authorized(query, account, 'accounts', 'create')
    assert shared_write_authorized(query, stock, 'holdings', 'create')
    assert shared_write_authorized(stock + '\n이것들 모두 저장해줘', stock, 'holdings', 'create')


def test_immediate_subject_can_supply_a_deictic_list_header():
    row = 'NASDAQ:TEST $12.50 8주'
    query = '주식이 더 있어. 이것들 다 저장해줘\n' + row
    assert shared_write_authorized(query, row, 'holdings', 'create')
