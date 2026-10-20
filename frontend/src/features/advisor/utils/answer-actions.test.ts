import { expect, it } from 'vitest';
import { answerQuestion, briefingDraft, nextRating } from './answer-actions';
it('uses the question preceding the selected answer, not a later question', () => {
  expect(
    answerQuestion(
      [
        { id: 1, role: 'user', content: '원래 질문' },
        { id: 2, role: 'assistant', content: '답변' },
        { id: 3, role: 'user', content: '새 질문' },
      ],
      2,
    ),
  ).toBe('원래 질문');
});
it('clears the same rating and preserves separate ratings', () => {
  expect(nextRating(-1, -1)).toBeNull();
  expect(nextRating(-1, 1)).toBe(1);
});
it('only accepts known public briefing codes and never overwrites a draft', () => {
  expect(briefingDraft('goals', '작성 중')).toBe('작성 중');
  expect(briefingDraft('private company', '')).toBe('');
  expect(briefingDraft('goals', '')).toContain('목표');
});
