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

it('reads date-time inputs as the backend timezone, whatever the browser zone is', async () => {
  const { setDisplayTimeZone } = await import('@/lib/utils/format');
  const { initialValues } = await import('./form-values');
  const fields = [{ name: 'starts_at', kind: 'datetime' as const, required: true, nullable: false }];
  setDisplayTimeZone('Asia/Seoul');
  try {
    expect(toPayload(fields, { starts_at: '2026-10-18T09:30' })).toEqual({ starts_at: '2026-10-18T00:30:00.000Z' });
    expect(initialValues(fields, { starts_at: '2026-10-18T00:30:00Z' })).toEqual({ starts_at: '2026-10-18T09:30' });
  } finally {
    setDisplayTimeZone(undefined);
  }
});

it('edits all-day events as first and last day and stores the half-open local span', async () => {
  const { setDisplayTimeZone } = await import('@/lib/utils/format');
  const { initialValues } = await import('./form-values');
  const fields = [
    { name: 'title', kind: 'text' as const, required: true, nullable: false },
    { name: 'starts_at', kind: 'datetime' as const, required: true, nullable: false },
    { name: 'ends_at', kind: 'datetime' as const, required: false, nullable: true },
    { name: 'all_day', kind: 'boolean' as const, required: false, nullable: false },
  ];
  setDisplayTimeZone('Asia/Seoul');
  try {
    const stored = { title: '연휴', all_day: true, starts_at: '2026-10-16T15:00:00Z', ends_at: '2026-10-18T15:00:00Z' };
    const values = initialValues(fields, stored);
    expect([values.starts_at, values.ends_at]).toEqual(['2026-10-17', '2026-10-18']);
    expect(toPayload(fields, values)).toEqual({
      title: '연휴', all_day: true, starts_at: '2026-10-16T15:00:00.000Z', ends_at: '2026-10-18T15:00:00.000Z',
    });
    // One day with no end typed.
    expect(toPayload(fields, { ...values, ends_at: '' })).toMatchObject({ ends_at: '2026-10-17T15:00:00.000Z' });
    // Timed events are untouched.
    expect(toPayload(fields, { title: '회의', all_day: false, starts_at: '2026-10-18T09:00', ends_at: '' })).toEqual({
      title: '회의', all_day: false, starts_at: '2026-10-18T00:00:00.000Z', ends_at: null,
    });
  } finally {
    setDisplayTimeZone(undefined);
  }
});
