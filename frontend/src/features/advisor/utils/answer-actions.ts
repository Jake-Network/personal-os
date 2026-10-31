export function answerQuestion(messages: { id?: number; role: string; content: string }[], answerId: number): string {
  return messages.filter(message => message.role === 'user' && (message.id ?? Infinity) < answerId).at(-1)?.content ?? '';
}
export function nextRating(current: number | null | undefined, clicked: -1 | 1): -1 | 1 | null {
  return current === clicked ? null : clicked;
}
const BRIEFING: Record<string, string> = {
  expenses: '이번 달 지출을 살펴보고 조정할 부분을 함께 검토해 주세요.',
  goals: '마감이 다가오는 목표와 다음 행동을 함께 정리해 주세요.',
  interviews: '다가오는 면접을 준비할 계획을 함께 세워 주세요.',
  exercise: '최근 운동 기록을 살펴보고 다시 시작할 계획을 함께 세워 주세요.',
  // First-question templates from onboarding.
  runway: '지금 일을 쉬면 생활비로 몇 개월 버틸 수 있는지 알려 주세요. 계산에 부족한 기록이 있으면 무엇인지도 알려 주세요.',
  week: '이번 주 일정과 할 일을 보고 무엇부터 하면 좋을지 정리해 주세요.',
  recurring: '반복 거래를 포함해 이번 달 남은 지출 계획을 함께 점검해 주세요.',
};
export function briefingDraft(code: string | null, current: string): string {
  return current.trim() ? current : (code && BRIEFING[code]) || current;
}
