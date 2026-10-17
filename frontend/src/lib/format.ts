const krw = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const num = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 4 });

export function money(value: string | number | null | undefined, currency = 'KRW'): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return currency === 'KRW' ? `${krw.format(n)}원` : `${num.format(n)} ${currency}`;
}

/** 1억 2,345만원 style for headline figures. */
export function moneyShort(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  const eok = Math.floor(abs / 1e8);
  const man = Math.round((abs % 1e8) / 1e4);
  if (eok > 0) return `${sign}${eok}억${man ? ` ${krw.format(man)}만` : ''}원`;
  if (abs >= 1e4) return `${sign}${krw.format(Math.round(abs / 1e4))}만원`;
  return `${sign}${krw.format(abs)}원`;
}

export function plain(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return String(value);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' });
}

export function dateOnly(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric' });
}

export function relative(value: string | null | undefined): string {
  if (!value) return '데이터 없음';
  const diff = Date.now() - new Date(value).getTime();
  const day = 86_400_000;
  if (diff < 60_000) return '방금';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}분 전`;
  if (diff < day) return `${Math.floor(diff / 3_600_000)}시간 전`;
  if (diff < 30 * day) return `${Math.floor(diff / day)}일 전`;
  return dateOnly(value);
}
