import { describe, expect, it } from 'vitest';

import { approvalKey, batchSummary, parseApprovalKey } from './batch';

describe('batch approvals', () => {
  it('round-trips item keys', () => {
    expect(parseApprovalKey(approvalKey('playbook', 12))).toEqual({ kind: 'playbook', id: 12 });
  });
  it('reports partial success with the server reasons', () => {
    const result = {
      succeeded: 1,
      failed: 2,
      results: [
        { kind: 'memory' as const, id: 1, decision: 'approve' as const, ok: true },
        { kind: 'memory' as const, id: 2, decision: 'approve' as const, ok: false, error: '이미 처리됨' },
        { kind: 'playbook' as const, id: 3, decision: 'approve' as const, ok: false, error: '이미 처리됨' },
      ],
    };
    expect(batchSummary(result, '승인')).toEqual({ ok: false, message: '1건 승인, 2건은 처리하지 못했습니다: 이미 처리됨' });
    expect(batchSummary({ ...result, failed: 0, succeeded: 3 }, '승인')).toEqual({ ok: true, message: '3건을 승인했습니다' });
  });
});
