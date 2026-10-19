import { recordHref } from '@/features/personal-data/hooks/use-record-param';
import type { ConversationCreateDomain } from '@/api-client/model';

export const DOMAINS: { key: NonNullable<ConversationCreateDomain>; label: string }[] = [
  { key: 'financial', label: '재무' },
  { key: 'investment', label: '투자' },
  { key: 'career', label: '커리어' },
  { key: 'calendar', label: '일정' },
  { key: 'health', label: '건강' },
];

/** `?domain=` from the URL, if it names a known advisor domain. */
export const parseDomain = (value: string | null): ConversationCreateDomain => DOMAINS.find(d => d.key === value)?.key ?? null;

export const SUGGESTIONS: Record<string, string[]> = {
  general: [
    '현재 내 순자산은?',
    '지금 회사를 퇴사하고 3개월 쉬어도 재정적으로 괜찮을까?',
    '앞으로 6개월 동안 돈, 커리어, 운동을 고려해서 우선순위를 정해 줘',
  ],
  financial: ['현재 내 순자산은?', '월 저축액을 50만원 늘리면 목표 자산 달성이 얼마나 빨라질까?'],
  investment: ['현재 포트폴리오가 너무 공격적인지 분석해 줘', '환율이 10% 떨어지면 내 자산은 어떻게 변해?'],
  career: ['현재 진행 중인 채용 중에서 어떤 회사에 가장 집중해야 할까?', '면접 준비 우선순위를 정리해 줘'],
  calendar: ['다음 주 일정을 분석해서 면접 준비와 운동을 어떻게 병행할지 정리해 줘'],
  health: ['이번 달 운동량이 목표에 비해 충분한지 봐 줘'],
};

export const INSPECTOR_TITLE = {
  preview: '이번 질문에 보낼 데이터',
  answer: '최근 답변에 쓴 데이터',
  snapshot: '답변 당시 데이터',
} as const;

/** Only tables whose destination understands this record ID may open an editor. */
const RECORD_PATH: Record<string, string> = {
  tasks: '/plan/tasks',
  goals: '/plan/goals',
  calendar_events: '/plan/events',
  workout_logs: '/plan/workouts',
  job_applications: '/career',
  career_criteria: '/career/criteria',
  accounts: '/finance/accounts',
  cashflow_entries: '/finance/transactions',
};

export function evidenceHref(table: string | undefined, id: number | undefined): string | null {
  const path = table ? RECORD_PATH[table] : undefined;
  return path && id !== undefined && Number.isSafeInteger(id) ? recordHref(path, id) : null;
}
