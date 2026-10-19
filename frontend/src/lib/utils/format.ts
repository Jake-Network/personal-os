// Display formatting only. Money stays a Decimal string from the API; nothing here is used for calculation.

let zone: string | undefined;

/** Times are shown in the backend's PERSONAL_OS_TIMEZONE, not the browser's; set once the app knows it. */
export function setDisplayTimeZone(timeZone: string | undefined) {
  zone = timeZone;
}

export function displayTimeZone(): string {
  return zone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
}

const DECIMAL = /^-?\d+(\.\d+)?$/;
const groupDigits = (whole: string) => whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** Digit-grouped exact text of a Decimal string; trailing fraction zeros are dropped. */
function decimalText(value: string): string {
  const [whole, fraction = ''] = value.split('.');
  const kept = fraction.replace(/0+$/, '');
  return `${groupDigits(whole)}${kept ? `.${kept}` : ''}`;
}

function exact(value: string | number): string | null {
  if (typeof value === 'number') return Number.isFinite(value) ? decimalText(String(value)) : null;
  const text = value.trim();
  return DECIMAL.test(text) ? decimalText(text) : null;
}

/** `missing` names why there is no number; a real zero still prints as 0. */
export function money(value: string | number | null | undefined, currency = 'KRW', missing = '미기록'): string {
  if (value === null || value === undefined || value === '') return missing;
  const text = exact(value);
  if (text === null) return '확인 필요';
  return currency === 'KRW' ? `${text}원` : `${text} ${currency}`;
}

/** 1억 2,345만원 style for headline figures. */
export function moneyShort(value: string | number | null | undefined, missing = '미기록'): string {
  if (value === null || value === undefined || value === '') return missing;
  const n = Number(value);
  if (!Number.isFinite(n)) return '확인 필요';
  const krw = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  const eok = Math.floor(abs / 1e8);
  const man = Math.round((abs % 1e8) / 1e4);
  if (eok > 0) return `${sign}${eok}억${man ? ` ${krw.format(man)}만` : ''}원`;
  if (abs >= 1e4) return `${sign}${krw.format(Math.round(abs / 1e4))}만원`;
  return `${sign}${krw.format(abs)}원`;
}

export function quantity(value: string | number | null | undefined, missing = '미기록'): string {
  if (value === null || value === undefined || value === '') return missing;
  return exact(value) ?? String(value);
}

export function plain(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return String(value);
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function instant(value: string): Date | null {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function format(value: string | null | undefined, options: Intl.DateTimeFormatOptions, empty: string): string {
  if (!value) return empty;
  // A calendar date has no time zone: format its own day, never a shifted one.
  if (DATE_ONLY.test(value)) {
    const d = instant(`${value}T00:00:00Z`);
    return d ? d.toLocaleString('ko-KR', { ...options, hour: undefined, minute: undefined, timeZone: 'UTC' }) : value;
  }
  const d = instant(value);
  return d ? d.toLocaleString('ko-KR', { ...options, timeZone: displayTimeZone() }) : value;
}

/** 10. 18. (토) 오후 02:00 */
export function dateTime(value: string | null | undefined, empty = '—'): string {
  return format(value, { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' }, empty);
}

/** 2026. 10. 18. */
export function dateOnly(value: string | null | undefined, empty = '—'): string {
  return format(value, { year: 'numeric', month: 'numeric', day: 'numeric' }, empty);
}

/** 10월 18일 (토) */
export function dayLabel(value: string | null | undefined, empty = '—'): string {
  return format(value, { month: 'long', day: 'numeric', weekday: 'short' }, empty);
}

/** 오후 02:00 */
export function timeOnly(value: string | null | undefined, empty = '—'): string {
  return format(value, { hour: '2-digit', minute: '2-digit' }, empty);
}

/** 2026년 10월, from 2026-10 or any date in that month. */
export function monthLabel(value: string | null | undefined, empty = '—'): string {
  if (!value) return empty;
  const m = /^(\d{4})-(\d{2})/.exec(value);
  return m ? `${m[1]}년 ${Number(m[2])}월` : value;
}

/** Full date and time, for audit-style rows. */
export function timestamp(value: string | null | undefined, empty = '기록 없음'): string {
  return format(value, { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }, empty);
}

export function relative(value: string | null | undefined, empty = '기록 없음'): string {
  if (!value) return empty;
  const d = instant(DATE_ONLY.test(value) ? `${value}T00:00:00Z` : value);
  if (!d) return value;
  const diff = Date.now() - d.getTime();
  const day = 86_400_000;
  if (diff < 0) return dateOnly(value);
  if (diff < 60_000) return '방금';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}분 전`;
  if (diff < day) return DATE_ONLY.test(value) ? '오늘' : `${Math.floor(diff / 3_600_000)}시간 전`;
  if (diff < 30 * day) return `${Math.floor(diff / day)}일 전`;
  return dateOnly(value);
}
