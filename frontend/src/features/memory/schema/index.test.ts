import { expect, it } from 'vitest';
import { decisionSchema, EMPTY_DECISION, decisionDefaults } from './index';

it('prefills every decision entrypoint within the server Unicode limit without splitting emoji', () => {
  expect(decisionDefaults({ title: '😀'.repeat(201), choice: '선택' }).title).toBe('😀'.repeat(200));
  expect(decisionDefaults({ title: '가'.repeat(201) }).title).toHaveLength(200);
  expect(decisionDefaults({ title: '짧은 질문' }).title).toBe('짧은 질문');
});
it('allows 200 Unicode characters but rejects 201 in a manually edited title', () => {
  const form = { ...EMPTY_DECISION, choice: '선택', rationale: '이유' };
  expect(decisionSchema.safeParse({ ...form, title: '😀'.repeat(200) }).success).toBe(true);
  expect(decisionSchema.safeParse({ ...form, title: '😀'.repeat(201) }).success).toBe(false);
});
