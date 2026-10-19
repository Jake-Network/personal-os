export type ReviewPeriod = 'month' | 'quarter' | 'year';

const pad = (n: number) => String(n).padStart(2, '0');

/** The half-open date range [start_on, end_on) the API expects for one month, quarter or year. */
export function periodRange(period: ReviewPeriod, year: number, index = 1): { start_on: string; end_on: string } {
  const months = period === 'month' ? 1 : period === 'quarter' ? 3 : 12;
  const firstMonth = period === 'month' ? index : period === 'quarter' ? (index - 1) * 3 + 1 : 1;
  const endTotal = year * 12 + (firstMonth - 1) + months;
  return {
    start_on: `${year}-${pad(firstMonth)}-01`,
    end_on: `${Math.floor(endTotal / 12)}-${pad((endTotal % 12) + 1)}-01`,
  };
}

/** "2026년 9월 회고" from a stored review's period and start date. */
export function periodTitle(period: string, startOn: string): string {
  const year = Number(startOn.slice(0, 4));
  const month = Number(startOn.slice(5, 7));
  if (period === 'month') return `${year}년 ${month}월`;
  if (period === 'quarter') return `${year}년 ${Math.floor((month - 1) / 3) + 1}분기`;
  return `${year}년`;
}

/** The most recent finished period, a sensible default for a new review. */
export function previousPeriod(period: ReviewPeriod, today: string): { year: number; index: number } {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  if (period === 'year') return { year: year - 1, index: 1 };
  if (period === 'quarter') {
    const q = Math.floor((month - 1) / 3) + 1;
    return q === 1 ? { year: year - 1, index: 4 } : { year, index: q - 1 };
  }
  return month === 1 ? { year: year - 1, index: 12 } : { year, index: month - 1 };
}
