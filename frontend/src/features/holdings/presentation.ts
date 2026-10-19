import { money } from '@/features/finance/presentation';

/** Presentation only: all return and profit amounts are calculated by the backend. */
export function returnTone(value: string | null | undefined): 'positive' | 'negative' | 'neutral' {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value) || /^-?0+(\.0+)?$/.test(value)) return 'neutral';
  return value.startsWith('-') ? 'negative' : 'positive';
}

export function returnPercent(value: string | null | undefined): string {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value) || !Number.isFinite(Number(value))) return '수익률 확인 필요';
  return `${new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format(Number(value))}%`;
}

export function signedMoney(value: string | null | undefined, currency: string): string {
  return `${returnTone(value) === 'positive' ? '+' : ''}${money(value, currency)}`;
}
