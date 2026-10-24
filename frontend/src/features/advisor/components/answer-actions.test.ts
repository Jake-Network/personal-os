import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  mutation: { isPending: false, isSuccess: false, variables: undefined as { kind?: string } | undefined,
    error: null as Error | null, mutate: vi.fn(), reset: vi.fn() },
}));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => state.mutation,
}));
vi.mock('@/api-client/generated/advisor/advisor', () => ({
  rateRecommendation: vi.fn(),
  getListRecommendationsQueryKey: () => ['synthetic-ratings'],
  useListRecommendations: () => ({ isSuccess: true, data: [
    { message_id: 9, user_rating: -1, user_feedback: '합성 저장된 사유' },
  ] }),
}));
vi.mock('@/features/memory/components/decision-form', () => ({ DecisionFormSheet: () => null }));

import { AnswerActions } from './answer-actions';

const render = () => renderToStaticMarkup(createElement(AnswerActions, {
  messageId: 9, conversationId: 1, question: '합성 질문',
}));

describe('answer feedback controls', () => {
  beforeEach(() => {
    state.mutation.isPending = false;
    state.mutation.isSuccess = false;
    state.mutation.variables = undefined;
    state.mutation.error = null;
  });

  it('makes a persisted thumbs-down visually selected and prevents resaving an unchanged reason', () => {
    const html = render();
    expect(html).toMatch(/aria-label="아쉬워요"[^>]*aria-pressed="true"/);
    expect(html).toContain('aria-pressed:bg-primary');
    expect(html).toContain('합성 저장된 사유');
    expect(html).toMatch(/type="submit"[^>]*disabled/);
    expect(html).toContain('저장됨');
  });

  it('shows pending feedback saves and prevents edits while they are in flight', () => {
    state.mutation.isPending = true;
    state.mutation.variables = { kind: 'reason' };
    const html = render();
    expect(html).toContain('저장 중…');
    expect(html).toMatch(/aria-label="답변이 아쉬운 이유"[^>]*disabled/);
  });

  it('acknowledges a saved reason separately from a rating', () => {
    state.mutation.isSuccess = true;
    state.mutation.variables = { kind: 'reason' };
    expect(render()).toContain('사유를 저장했습니다.');
    state.mutation.variables = { kind: 'rating' };
    expect(render()).toContain('평가를 저장했습니다.');
  });

  it('reports failure without replacing the reason with a success message', () => {
    state.mutation.error = new Error('합성 저장 실패');
    expect(render()).toContain('합성 저장 실패');
    expect(render()).not.toContain('사유를 저장했습니다.');
    expect(render()).toContain('합성 저장된 사유');
  });
});
