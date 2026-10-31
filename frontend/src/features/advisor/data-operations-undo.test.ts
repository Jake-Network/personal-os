import { expect, it } from 'vitest';

import { canUndo, type DataOperation } from './data-operations';

const saved: DataOperation = { operation: 'create', resource: 'workout-logs', status: 'saved', message: '저장했습니다.', receipt_id: 7 };

it('offers undo only for saved creates and updates with a receipt that is not undone yet', () => {
  expect(canUndo(saved)).toBe(true);
  expect(canUndo({ ...saved, operation: 'update' })).toBe(true);
  expect(canUndo({ ...saved, operation: 'delete' })).toBe(false);
  expect(canUndo({ ...saved, status: 'needs_input' })).toBe(false);
  expect(canUndo({ ...saved, receipt_id: undefined })).toBe(false);
  expect(canUndo({ ...saved, undone: true })).toBe(false);
});
