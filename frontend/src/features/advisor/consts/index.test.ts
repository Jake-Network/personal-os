import { expect, it } from 'vitest';

import { evidenceHref } from './index';

it('links cited records to where they are managed, and nothing else', () => {
  expect(evidenceHref('tasks', 4)).toBe('/plan/tasks?record=4');
  expect(evidenceHref('liabilities', 2)).toBe('/finance/accounts?record=2');
  expect(evidenceHref('interviews', 9)).toBe('/career?record=9');
  expect(evidenceHref('document_chunks', 1)).toBeNull();
  expect(evidenceHref('personal_memories', 1)).toBeNull();
  expect(evidenceHref('tasks', undefined)).toBeNull();
});
