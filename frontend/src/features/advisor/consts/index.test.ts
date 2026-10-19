import { expect, it } from 'vitest';

import { evidenceHref } from './index';

it('links cited records to where they are managed, and nothing else', () => {
  expect(evidenceHref('tasks', 4)).toBe('/plan/tasks?record=4');
  expect(evidenceHref('accounts', 2)).toBe('/finance/accounts?record=2');
  for (const table of ['liabilities', 'other_assets', 'planned_expenses', 'financial_transactions', 'holdings', 'fx_rates']) {
    expect(evidenceHref(table, 2)).toBeNull();
  }
  expect(evidenceHref('job_applications', 9)).toBe('/career?record=9');
  expect(evidenceHref('interviews', 9)).toBeNull();
  expect(evidenceHref('document_chunks', 1)).toBeNull();
  expect(evidenceHref('personal_memories', 1)).toBeNull();
  expect(evidenceHref('tasks', undefined)).toBeNull();
});
