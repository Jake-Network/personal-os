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
};
export function briefingDraft(code: string | null, current: string): string {
  return current.trim() ? current : (code && BRIEFING[code]) || current;
}
