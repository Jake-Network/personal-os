import { expect, it } from 'vitest';
import { toPayload } from './form-values';

it('keeps whole holding quantities exact while converting ordinary integer IDs', () => {
  expect(toPayload([
    { name: 'quantity', kind: 'integer', required: true, nullable: false },
    { name: 'account_id', kind: 'integer', required: false, nullable: true },
  ], { quantity: '9007199254740993', account_id: '2' })).toEqual({
    quantity: '9007199254740993', account_id: 2,
  });
});
