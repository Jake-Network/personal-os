import { beforeEach, describe, expect, it, vi } from 'vitest';
import { customInstance } from '@/api-client/custom-client';
import { financeApi } from './api';
vi.mock('@/api-client/custom-client', () => ({ customInstance: vi.fn() }));
describe('value confirmation', () => {
  beforeEach(() => vi.clearAllMocks());
  it('sends only the expected version so stale UI balances cannot overwrite stored precision', async () => {
    await financeApi.confirmValue('accounts', 7, '2026-10-20T01:02:03.123456');
    expect(customInstance).toHaveBeenCalledWith({
      url: '/api/data/accounts/7/confirm-value',
      method: 'POST',
      data: { expected_version: '2026-10-20T01:02:03.123456' },
    });
  });
});
