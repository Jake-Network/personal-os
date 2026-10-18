import { describe, expect, it } from 'vitest';
import { advisorValue } from './presentation';

describe('consultation result presentation', () => {
  it('keeps unavailable values distinct from numeric zero', () => {
    expect(advisorValue(null)).toBe('확인 필요');
    expect(advisorValue('0', 'months')).toBe('0개월');
  });
  it('recursively removes internal provenance hashes while retaining user meaning', () => {
    const text = advisorValue({
      server_calculations: {
        time: {
          available_hours_per_week: '12',
          dependency_hash: 'private-hash',
          calculation_version: 'v1',
          dependencies: { secret: true },
          reused: true,
        },
      },
    });
    expect(text).toContain('주당 가용 시간: 12시간');
    expect(text).toContain('조건과 근거가 같아 이전 계산 유지');
    expect(text).not.toMatch(/private-hash|calculation_version|dependencies|secret/);
  });
});
