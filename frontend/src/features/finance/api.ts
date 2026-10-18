import { customInstance } from '@/api-client/custom-client';

export type FinanceSettings = {
  spreadsheet_id: string | null;
  verified_at: string | null;
  last_sync_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
};

export type GoogleOAuthSetup = {
  missing_fields: string[];
  frontend_url: string;
  redirect_uri: string;
  login_url: string;
  redirect_uri_supported: boolean;
  callback_host_matches_frontend: boolean;
};

export type GoogleConnection = {
  configured: boolean;
  setup?: GoogleOAuthSetup;
  connected: boolean;
  can_write?: boolean;
  requires_scope_reset?: boolean;
  status: 'not_connected' | 'connected' | 'needs_reauth' | 'disconnected';
  email: string | null;
  scopes: string[];
  access_expires_at: string | null;
  last_error_code: string | null;
  credential_source: 'oauth' | 'application_default' | 'none';
};

export type FinanceLine = {
  kind: string;
  id: string;
  label: string;
  currency: string;
  balance: string | null;
  quantity: string | null;
  avg_cost: string | null;
  ticker: string | null;
  price: string | null;
  price_as_of: string | null;
  fx_rate: string | null;
  fx_as_of: string | null;
  value_krw: string | null;
  unrealized_gain_krw: string | null;
  issues: string[];
};

export type Portfolio = {
  lines: FinanceLine[];
  total_assets: string | null;
  total_liabilities: string | null;
  net_worth: string | null;
  cash: string | null;
  investments: string | null;
  complete: boolean;
  issues: string[];
  stale: boolean;
  synced_at: string | null;
  allocation: { cash: string | null; investments: string | null; other: string | null };
};

export type Snapshot = Portfolio & {
  id: number;
  month: string;
  revision: number;
  created_at: string;
  reason: string;
  change_krw: string | null;
  change_pct: string | null;
  rows: Record<string, string | null>[];
  coverage: string[];
};

export const financeApi = {
  googleStatus: () => customInstance<GoogleConnection>({ url: '/api/finance/google/status' }),
  googleLogin: (writeAccess = false, returnTo?: 'holdings') =>
    customInstance<{ authorize_url: string }>({
      url: '/api/finance/google/login',
      method: 'POST',
      params: writeAccess || returnTo ? { write_access: writeAccess, return_to: returnTo } : undefined,
    }),
  googleDisconnect: () => customInstance<void>({ url: '/api/finance/google/disconnect', method: 'POST' }),
  settings: () => customInstance<FinanceSettings>({ url: '/api/finance/settings' }),
  save: (spreadsheet_id: string) => customInstance<FinanceSettings>({ url: '/api/finance/settings', method: 'PUT', data: { spreadsheet_id } }),
  verify: () => customInstance<unknown>({ url: '/api/finance/verify', method: 'POST' }),
  sync: () => customInstance<unknown>({ url: '/api/finance/sync', method: 'POST' }),
  portfolio: () => customInstance<Portfolio>({ url: '/api/finance/portfolio' }),
  history: (period: string) =>
    customInstance<{ snapshots: Snapshot[]; missing_months: string[] }>({ url: '/api/finance/history', params: { period } }),
  create: (month: string) => customInstance<Snapshot>({ url: '/api/finance/history', method: 'POST', data: { month: `${month}-01` } }),
  audit: (id: number) => customInstance<Snapshot[]>({ url: `/api/finance/history/${id}/audit` }),
  closeMonth: (data: unknown) => customInstance<Snapshot>({ url: '/api/finance/month-close', method: 'POST', data }),
  correct: (id: number, data: unknown) => customInstance<Snapshot>({ url: `/api/finance/history/${id}/corrections`, method: 'POST', data }),
};
