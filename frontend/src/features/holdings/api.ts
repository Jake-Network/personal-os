import { customInstance } from '@/api-client/custom-client';
import type { FinanceSettings, Portfolio } from '@/features/finance/api';

export type HoldingInput = {
  account_id?: number | null;
  position_id: string;
  request_id: string;
  expected_version?: string | null;
  ticker: string;
  quantity: string;
  currency: string;
  label: string;
  avg_cost: string | null;
  asset_class: 'equity' | 'etf' | 'bond' | 'crypto' | 'other';
  quote_mode: 'auto' | 'manual';
  manual_price: string | null;
  price_as_of: string | null;
};
export type SheetHolding = Omit<HoldingInput, 'request_id'> & { id: string; price: string | null; quote_status?: string; record_id?: number };

// Sheets rows also contain quote metadata. Only user input belongs in a write request.
export function holdingDraft(row: SheetHolding, requestId: string): HoldingInput {
  return {
    position_id: row.position_id || row.id,
    ...(row.account_id !== undefined ? { account_id: row.account_id } : {}),
    request_id: requestId,
    expected_version: row.expected_version,
    ticker: row.ticker,
    label: row.label,
    quantity: row.quantity,
    currency: row.currency,
    avg_cost: row.avg_cost ?? null,
    asset_class: row.asset_class,
    quote_mode: row.quote_mode,
    manual_price: row.manual_price ?? null,
    price_as_of: row.price_as_of?.slice(0, 10) ?? null,
  };
}
export type HoldingsState = {
  rows: SheetHolding[];
  portfolio: Portfolio;
  settings: FinanceSettings;
  can_write: boolean;
  initialized: boolean;
  warning: string | null;
};
export const holdingsApi = {
  list: () => customInstance<HoldingsState>({ url: '/api/finance/holdings' }),
  save: (data: HoldingInput) =>
    customInstance<HoldingsState & { saved: boolean; quote_status: string }>({ url: '/api/finance/holdings', method: 'POST', data }),
  refresh: () => customInstance<HoldingsState>({ url: '/api/finance/holdings/refresh', method: 'POST' }),
  initialize: () => customInstance<HoldingsState>({ url: '/api/finance/holdings/initialize', method: 'POST' }),
};
