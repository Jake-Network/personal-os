import { describe, expect, it } from 'vitest';

import { isDecisionReviewDue } from './review-due';

describe('decision review due', () => {
  const now = Date.parse('2026-10-20T00:00:00Z');
  it('includes the scheduled instant and respects timezone offsets', () => {
    expect(isDecisionReviewDue({ review_on: '2026-10-20T09:00:00+09:00' }, now)).toBe(true);
    expect(isDecisionReviewDue({ review_on: '2026-10-20T09:00:01+09:00' }, now)).toBe(false);
  });
  it('excludes completed, unscheduled and malformed dates', () => {
    expect(isDecisionReviewDue({ review_on: '2026-10-19T00:00:00Z', reviewed_at: '2026-10-19T01:00:00Z' }, now)).toBe(false);
    expect(isDecisionReviewDue({}, now)).toBe(false);
    expect(isDecisionReviewDue({ review_on: 'invalid' }, now)).toBe(false);
  });
  it('treats an outcome recorded before the scheduled review as not settling it', () => {
    expect(isDecisionReviewDue({ review_on: '2026-10-19T00:00:00Z', reviewed_at: '2026-10-18T00:00:00Z' }, now)).toBe(true);
    expect(isDecisionReviewDue({ review_on: '2026-10-19T00:00:00Z', reviewed_at: '2026-10-19T00:00:00Z' }, now)).toBe(false);
  });
});
