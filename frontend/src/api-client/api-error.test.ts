import { describe, expect, it } from 'vitest';

import { errorFromBody } from './api-error';

describe('errorFromBody', () => {
  it('keeps the advisor error code', () => {
    const e = errorFromBody(401, { message: '다시 로그인하세요', code: 'reauth_required' });
    expect([e.status, e.message, e.code]).toEqual([401, '다시 로그인하세요', 'reauth_required']);
  });

  it('flattens FastAPI validation details', () => {
    const e = errorFromBody(422, { detail: [{ loc: ['body', 'balance'], msg: 'Input should be a valid decimal' }] });
    expect(e.message).toBe('balance: Input should be a valid decimal');
  });

  it('falls back to the status code', () => {
    expect(errorFromBody(500, null).message).toBe('요청 실패 (500)');
  });
});
