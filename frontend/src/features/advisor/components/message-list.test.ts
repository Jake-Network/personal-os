import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import type { ChatMessage } from '../types';
import { MessageItem } from './message-list';
vi.mock('./answer-actions', () => ({ AnswerActions: () => createElement('span', null, '결정과 평가') }));
const message: ChatMessage = {
  key: 'm-2',
  id: 2,
  role: 'assistant',
  content: '저장된 답변',
  status: 'complete',
  model: null,
  context_snapshot_id: null,
  is_final_answer: true,
};
const render = (changes: Partial<ChatMessage> = {}) =>
  renderToStaticMarkup(
    createElement(MessageItem, {
      message: { ...message, ...changes },
      conversationId: 1,
      question: '원래 질문',
      onEvidence: () => {},
      onDocument: () => {},
    }),
  );
it('allows actions for a server-confirmed final saved answer', () => expect(render()).toContain('결정과 평가'));
it('excludes clarification, unfinished, and streaming answers', () => {
  expect(render({ is_final_answer: false })).not.toContain('결정과 평가');
  expect(render({ status: 'incomplete' })).not.toContain('결정과 평가');
  expect(render({ streaming: true })).not.toContain('결정과 평가');
});
