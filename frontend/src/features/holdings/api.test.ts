import { beforeEach, describe, expect, it, vi } from 'vitest';
import { customInstance } from '@/api-client/custom-client';
import { financeApi } from '@/features/finance/api';
import { holdingDraft, holdingsApi, type HoldingInput, type SheetHolding } from './api';

vi.mock('@/api-client/custom-client', () => ({ customInstance: vi.fn().mockResolvedValue({}) }));

beforeEach(() => vi.clearAllMocks());

describe('Sheets holdings API', () => {
  it('requests explicit write consent and returns to holdings without changing default read consent', async () => {
    await financeApi.googleLogin(true, 'holdings');
    expect(customInstance).toHaveBeenLastCalledWith({
      url: '/api/finance/google/login',
      method: 'POST',
      params: { write_access: true, return_to: 'holdings' },
    });
    await financeApi.googleLogin();
    expect(customInstance).toHaveBeenLastCalledWith({ url: '/api/finance/google/login', method: 'POST', params: undefined });
  });

  it('preserves decimal precision, missing prices and stable intent IDs across retries', async () => {
    const payload: HoldingInput = {
      position_id: 'position',
      request_id: 'request',
      ticker: 'NASDAQ:AAPL',
      quantity: '9007199254740993.000000001',
      avg_cost: '123.123456789',
      currency: 'USD',
      label: 'Apple',
      asset_class: 'equity',
      quote_mode: 'auto',
      manual_price: null,
      price_as_of: null,
    };
    await holdingsApi.save(payload);
    await holdingsApi.save(payload);
    expect(customInstance).toHaveBeenNthCalledWith(1, { url: '/api/finance/holdings', method: 'POST', data: payload });
    expect(customInstance).toHaveBeenNthCalledWith(2, { url: '/api/finance/holdings', method: 'POST', data: payload });
  });

  it('maps editable inputs without leaking Sheet metadata and preserves the optimistic version', () => {
    const row = {
      position_id: 'position',
      id: 'position',
      ticker: 'NASDAQ:AAPL',
      label: 'Apple',
      currency: 'USD',
      quantity: '1.00001',
      avg_cost: null,
      asset_class: 'equity',
      quote_mode: 'manual',
      manual_price: '12.35',
      price_as_of: '2026-10-17T00:00:00Z',
      price: '12.35',
      expected_version: 'abc123',
      source: 'manual',
    } as SheetHolding;
    const body = holdingDraft(row, 'request');
    expect(body).not.toHaveProperty('id');
    expect(body).not.toHaveProperty('price');
    expect(body).not.toHaveProperty('source');
    expect(body.expected_version).toBe('abc123');
    expect(body.price_as_of).toBe('2026-10-17');
    expect(body.quantity).toBe('1.00001');
  });

  it('reads Sheet rows and keeps worksheet initialization separate from refresh', async () => {
    await holdingsApi.list();
    expect(customInstance).toHaveBeenLastCalledWith({ url: '/api/finance/holdings' });
    await holdingsApi.refresh();
    expect(customInstance).toHaveBeenLastCalledWith({ url: '/api/finance/holdings/refresh', method: 'POST' });
    await holdingsApi.initialize();
    expect(customInstance).toHaveBeenLastCalledWith({ url: '/api/finance/holdings/initialize', method: 'POST' });
  });
});
