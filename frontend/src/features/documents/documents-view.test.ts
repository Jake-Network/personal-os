import { expect, it } from 'vitest';

import type { PersonalDocument } from './api';
import { replacing } from './documents-view';

it('stops reporting replacement processing when the latest version failed', () => {
  const doc = { active_version_id: 1, latest_version_id: 2, status: 'failed' } as PersonalDocument;
  expect(replacing(doc)).toBe(false);
  expect(replacing({ ...doc, status: 'processing' })).toBe(true);
  expect(replacing({ ...doc, status: 'pending' })).toBe(true);
  expect(replacing({ ...doc, active_version_id: 2, status: 'ready' })).toBe(false);
});
