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

it('shows committed operation results independently of the answer and keeps failures distinct', () => {
  const html = render({
    content: '',
    status: 'incomplete',
    is_final_answer: false,
    data_operations: [
      { operation: 'create', resource: 'workout-logs', status: 'saved', record_id: 17, message: '오늘 달리기를 기록했습니다.', record: { private_internal: 'raw-json-not-for-ui' } },
      { operation: 'update', resource: 'accounts', status: 'needs_input', message: '같은 이름의 계좌가 두 개입니다. 계좌를 선택해 주세요.' },
      { operation: 'delete', resource: 'tasks', status: 'failed', message: '할 일을 삭제하지 못했습니다.' },
    ],
  });
  expect(html).toContain('저장됨');
  expect(html).toContain('/plan/workouts?record=17');
  expect(html).toContain('확인 필요');
  expect(html).toContain('계좌를 선택해 주세요');
  expect(html).toContain('실패');
  expect(html).not.toContain('raw-json-not-for-ui');
  expect(html).not.toContain('#17');
  expect(html).not.toContain('삭제됨');
});

it('does not link a deleted record to its old editor', () => {
  const html = render({ data_operations: [{ operation: 'delete', resource: 'workout-logs', status: 'saved', record_id: 17, message: '운동 기록을 삭제했습니다.' }] });
  expect(html).toContain('삭제됨');
  expect(html).toContain('href="/plan/workouts"');
  expect(html).not.toContain('?record=17');
});
