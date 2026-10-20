import type { Category } from '@/api-client/model';
import { issueText } from '@/features/finance/presentation';

export const CATEGORY_LABEL: Record<Category, string> = {
  financial: '재무',
  investment: '투자',
  career: '커리어',
  calendar: '일정',
  health: '건강',
  goals: '목표',
  profile: '개인 프로필',
};

export const CATEGORY_HINT: Record<Category, string> = {
  financial: '계좌 잔고, 부채, 자산, 지출',
  investment: '보유 종목, 수량, 비중, 가격',
  career: '채용 상태, JD, 면접, 평가 기준',
  calendar: '일정, 약속, 마감일, 할 일',
  health: '운동 이력',
  goals: '단기·장기 목표와 진행률',
  profile: '확인된 선호·제약·우선순위',
};

export const ALL_CATEGORIES: Category[] = ['financial', 'investment', 'career', 'calendar', 'health', 'goals', 'profile'];

export const ROUTE_REASON: Record<string, string> = {
  keyword: '질문 키워드로 자동 선택',
  override: '직접 선택',
  previous_turn: '직전 질문의 영역을 이어서 사용',
  domain: '상담 분야 기본값',
  fallback: '해당 키워드 없음, 목표만 사용',
};

const FLAG_TEXT: Record<string, string> = {
  monthly_history_withheld: '월별 자산 이력은 이번 상담에 공유하지 않았습니다',
  history_embedding_index_required: '지난 상담의 의미 검색 준비가 필요합니다',
  history_embedding_unavailable: '지난 상담의 의미 검색을 사용할 수 없습니다',
  history_keyword_retrieval_only: '지난 상담은 단어가 일치하는 내용만 찾았습니다',
  history_search_results_omitted: '지난 상담 검색 결과 일부를 전송 길이에 맞춰 생략했습니다',
  valuation_base_unavailable: '선택한 통화로 전체 자산 평가를 제공할 수 없습니다',
  web_page_blocked: '공개 웹 주소가 아닌 페이지 수집 차단',
  web_page_encoding: '압축 응답으로 본문 수집 불가',
  web_page_too_large: '본문 수집 크기 한도 초과',
  web_page_redirect_limit: '웹페이지 이동 한도 초과',
  web_page_fetch_failed: '일부 웹 본문 수집 실패',
  web_page_unsupported_type: '지원하지 않는 웹 문서 형식',
  web_page_empty: '웹 본문 추출 불가',
  web_search_no_body_evidence: '확보한 웹 본문 근거 없음',
  web_excerpts_trimmed: '전송 예산에 맞춰 웹 발췌 일부 생략',
  history_document_evidence_omitted: '대화 맥락은 유지했으며 일부 과거 문서 인용은 길이 제한으로 생략했습니다',
  no_matching_documents: '검색 범위에 공유 가능한 문서가 없습니다',
  document_embedding_reindex_required: '문서 검색 설정이 바뀌어 다시 처리가 필요합니다',
  document_embedding_unavailable: '문서 검색 모델에 연결할 수 없습니다',
  no_relevant_document_chunks: '질문을 뒷받침할 문서 구간을 찾지 못했습니다',
  requested_document_unavailable: '지정한 문서 일부를 사용할 수 없습니다',
  no_accounts: '등록된 계좌가 없습니다',
  no_liabilities_recorded: '부채가 기록되지 않았습니다 (0인지 미입력인지 알 수 없음)',
  stale_balance: '잔고 기준일이 오래되었습니다',
  stale_price: '시세 기준일이 오래되었습니다',
  investment_excluded_from_net_worth: '투자 영역이 공유 제외되어 순자산에서 증권이 빠졌습니다',
  net_worth_incomplete: '순자산 계산에서 빠진 항목이 있습니다',
  cashflow_foreign_currency_ignored: '외화 현금흐름은 월평균 계산에서 제외했습니다',
  recorded_flows_only: '기록한 수입·지출만 합산했습니다',
  foreign_currency_excluded: '외화 기록은 원화 합계에서 제외했습니다',
  missing_transaction_currency: '통화가 없는 기록이 있어 합계 불완전',
  missing_transaction_amount: '금액이 없는 기록이 있어 합계 불완전',
  cashflow_mixed_sources: '수입·지출과 거래 기록 함께 사용',
  spendable_liquidity_unknown: '생활비 현금 미기록',
  monthly_expense_unknown: '월평균 지출 데이터가 없습니다',
  monthly_expense_insufficient_coverage: '최근 3개월 중 일부 달만 지출 기록이 있어 월평균을 확정하지 않았습니다',
  no_holdings: '보유 종목이 없습니다',
  missing_fx: '환율이 없어 원화 환산을 못한 항목이 있습니다',
  news_source_not_configured: '뉴스 소스가 연결되지 않았습니다',
  no_active_applications: '진행 중인 채용이 없습니다',
  no_career_criteria: '커리어 평가 기준이 설정되지 않았습니다',
  no_upcoming_interviews: '예정된 면접이 없습니다',
  no_upcoming_events: '예정된 일정이 없습니다',
  no_events_in_window: '조회 기간에 등록된 일정이 없습니다',
  calendar_time_scope_unresolved: '날짜를 해석하지 못해 기본 기간의 일정만 조회했습니다',
  no_goals: '진행 중인 목표가 없습니다',
  no_workout_logs: '최근 운동 기록이 없습니다',
  category_excluded_by_user: '사용자가 공유를 제외한 영역입니다',
  context_text_trimmed: '길이 제한으로 긴 텍스트 일부를 줄였습니다',
  context_text_omitted: '길이 제한으로 메모 등 자유 텍스트를 뺐습니다',
  context_rows_omitted: '길이 제한으로 일부 레코드를 뺐습니다 (질문 관련 레코드 우선 유지)',
  context_section_omitted: '길이 제한으로 우선순위가 낮은 영역을 뺐습니다',
  context_records_summarized: '길이 제한으로 계산된 수치만 남기고 세부 레코드를 뺐습니다',
  data_quality_flags_omitted: '반복되는 데이터 경고 일부를 생략했습니다',
};

// Their backend `detail` is guidance for the model (English); the Korean text above says it all.
const MODEL_ONLY_DETAIL = new Set(['monthly_expense_unknown', 'investment_excluded_from_net_worth', 'no_liabilities_recorded', 'no_career_criteria']);

export function flagDetail(code: string, detail?: string): string | undefined {
  if (code === 'monthly_history_withheld') return '월별 전체 자산 이력을 사용하려면 재무와 투자 공유를 모두 허용해야 합니다. 공유 범위를 확인하세요.';
  if (code === 'history_embedding_index_required') return '현재는 단어 검색만 가능해 표현이 다른 관련 경험을 놓칠 수 있습니다.';
  if (code === 'history_embedding_unavailable') return '검색 연결을 확인하세요. 현재는 단어가 일치하는 과거 상담만 참고합니다.';
  if (code === 'valuation_base_unavailable') return '전체 자산 평가는 원화 기준으로 기록되어 있습니다. 기준 통화 설정을 확인하세요.';
  if (code === 'net_worth_incomplete' && detail)
    return detail
      .replaceAll('Stale price; latest valid market close unconfirmed', '시세가 오래됨')
      .split('; ')
      .map(issueText)
      .join('; ')
      .replace(/missing_fx_([A-Z]+)_([A-Z]+)/g, '$1 → $2 환율 없음')
      .replace(/\bno_value\b/g, '금액 미기록');
  return detail && !MODEL_ONLY_DETAIL.has(code) ? detail : undefined;
}

export function flagText(code: string): string {
  return FLAG_TEXT[code] ?? code;
}

export const TABLE_LABEL: Record<string, string> = {
  document_chunks: '문서 근거',
  accounts: '계좌',
  other_assets: '기타 자산',
  liabilities: '부채',
  holdings: '보유 종목',
  fx_rates: '환율',
  cashflow_entries: '수입·지출',
  financial_transactions: '거래 기록',
  planned_expenses: '예정 지출',
  job_applications: '채용 지원',
  interviews: '면접',
  career_criteria: '평가 기준',
  calendar_events: '일정',
  tasks: '할 일',
  goals: '목표',
  workout_logs: '운동 기록',
  personal_memories: '기억',
};

export const TOOL_LABEL: Record<string, string> = {
  search_documents: '문서 검색',
  get_accounts_summary: '계좌·자산·부채',
  get_cashflow_summary: '현금흐름',
  get_portfolio_summary: '포트폴리오',
  get_market_data: '시세·환율',
  get_relevant_news: '뉴스',
  get_job_applications: '채용 지원',
  get_interview_schedule: '면접 일정',
  get_calendar_events: '일정',
  get_tasks: '할 일',
  get_goals: '목표',
  get_health_summary: '운동',
  get_profile: '개인 프로필',
};

export const ACTION_LABEL: Record<string, string> = {
  create_task: '할 일 추가',
  calendar_update: '일정 변경',
  goal_update: '목표 수정',
};

export const MEMORY_KIND_LABEL: Record<string, string> = {
  profile: '프로필',
  preference: '선호',
  constraint: '제약',
  priority: '우선순위',
};

export const ERROR_HINT: Record<string, { action: string; href: string }> = {
  not_connected: { action: 'ChatGPT 연결하기', href: '/settings/ai-provider' },
  reauth_required: { action: '다시 로그인', href: '/settings/ai-provider' },
  plan_usage_not_authorized: { action: '권한 포함해 재연결', href: '/settings/ai-provider' },
  plan_usage_limit_exceeded: { action: '사용량 상태 보기', href: '/settings/ai-provider' },
};
