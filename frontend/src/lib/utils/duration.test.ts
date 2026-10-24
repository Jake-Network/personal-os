import { describe, expect, it } from 'vitest';

import { durationInput, durationSeconds, formatDuration } from './duration';

describe('workout durations', () => {
  it('keeps seconds through editing and formats hours beyond a clock day', () => {
    for (const seconds of [1, 45, 60, 2701, 5432, 90061, 2147483647, Number.MAX_SAFE_INTEGER]) {
      expect(durationSeconds(durationInput(seconds))).toBe(seconds);
    }
    expect(formatDuration(5432)).toBe('1시간 30분 32초');
    expect(formatDuration(2700)).toBe('45분');
    expect(formatDuration(45)).toBe('45초');
    expect(formatDuration(90061)).toBe('25시간 1분 1초');
    expect(formatDuration(0)).toBe('0초');
    expect(formatDuration(null)).toBe('—');
  });
});
