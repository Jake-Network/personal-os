import { fieldLabel } from '@/features/personal-data/consts/resources';
import { money } from '@/lib/utils/format';

const HIDDEN = new Set([
  'dependency_hash',
  'dependency_inputs',
  'dependencies',
  'calculation_version',
  'computed_by',
  'snapshot_id',
  'baseline_snapshot_id',
]);
const LABELS: Record<string, string> = {
  question: '상담 질문',
  objective: '상담 목적',
  period: '검토 기간',
  constraints: '필수 제약',
  assumptions: '이번 상담의 가정',
  unresolved: '아직 필요한 정보',
  confirmed_facts: '확인된 사실',
  server_calculations: '서버 계산',
  financial: '생활비·유동성',
  time: '시간 제약',
  available: '계산 가능 여부',
  reason: '확인할 정보',
  available_hours_per_week: '주당 가용 시간',
  required_hours_per_week: '주당 필요한 시간',
  margin_hours_per_week: '주당 여유 시간',
  feasible_under_assumptions: '가정 아래 일정 충족',
  work_hours_per_week: '주당 근무 시간',
  rest_hours_per_week: '주당 휴식 시간',
  committed_hours_per_week: '주당 기존 약속 시간',
  months: '생활비를 유지할 수 있는 기간',
  usable_cash: '사용 가능한 현금',
  monthly_net_burn: '월 순지출',
  monthly_expense: '월 지출',
  monthly_income: '월 수입',
  basis: '계산 기준',
  understated: '일부 자산이 제외된 결과',
  reused: '계산 재사용',
  currency: '통화',
  requested_change: '변경한 조건',
  note: '계산 설명',
};
const TEXT: Record<string, string> = {
  spendable_liquidity_or_explicit_assumption_missing: '생활비로 쓸 수 있는 현금 또는 월 지출·수입 가정이 필요합니다.',
  work_rest_commitment_or_required_hours_missing: '근무·휴식·기존 약속·필요 시간 입력이 필요합니다.',
  current_spendable_liquidity_and_scenario_assumptions: '현재 생활비용 현금과 이번 대안의 가정',
  explicit_scenario_assumptions: '이번 대안에 명시한 시간 가정',
  non_positive_burn_cash_does_not_deplete: '수입이 지출 이상이어서 현금이 소진되지 않는 가정입니다.',
};

export const advisorLabel = (key: string) => LABELS[key] ?? fieldLabel(key);
export function advisorValue(value: unknown, key = '', currency?: string): string {
  if (value === null || value === undefined) return '확인 필요';
  if (key === 'reused') return value ? '조건과 근거가 같아 이전 계산 유지' : '현재 근거로 계산';
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  if (Array.isArray(value)) return value.map(item => advisorValue(item)).join(', ') || '기록 없음';
  if (typeof value === 'object') {
    const values = value as Record<string, unknown>;
    const unit = typeof values.currency === 'string' ? values.currency : currency;
    return Object.entries(values)
      .filter(([name]) => !HIDDEN.has(name) && !name.startsWith('_'))
      .map(([name, item]) => `${advisorLabel(name)}: ${advisorValue(item, name, unit)}`)
      .join('\n');
  }
  if (key.endsWith('_hours_per_week')) return `${value}시간`;
  if (key === 'months') return `${value}개월`;
  if (['usable_cash', 'monthly_net_burn', 'monthly_expense', 'monthly_income'].includes(key) && currency) return money(String(value), currency);
  return TEXT[String(value)] ?? String(value);
}
export const visibleAdvisorEntries = (value: Record<string, unknown>) =>
  Object.entries(value).filter(([key]) => !HIDDEN.has(key) && !key.startsWith('_'));
