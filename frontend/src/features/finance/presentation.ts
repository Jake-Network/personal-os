// API money remains a Decimal string. Numbers below are only used to position chart points.
export function money(value: string | null | undefined, currency = 'KRW'): string {
  if (value == null || value.trim() === '' || !/^-?\d+(\.\d+)?$/.test(value)) return '확인 필요';
  const [whole, fraction] = value.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction && /[1-9]/.test(fraction) ? `.${fraction}` : ''} ${currency}`;
}

export function timestamp(value: string | null | undefined): string {
  if (!value) return '기록 없음';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ko-KR');
}

export function allocationPercent(part: string | null | undefined, total: string | null | undefined): string {
  if (part == null || total == null || !/^\d+(\.\d+)?$/.test(part) || !/^\d+(\.\d+)?$/.test(total)) return '비율 확인 필요';
  const [partWhole, partFraction = ''] = part.split('.');
  const [totalWhole, totalFraction = ''] = total.split('.');
  const scale = Math.max(partFraction.length, totalFraction.length);
  const numerator = BigInt(partWhole + partFraction.padEnd(scale, '0'));
  const denominator = BigInt(totalWhole + totalFraction.padEnd(scale, '0'));
  if (denominator === 0n) return '비율 계산 불가';
  const hundredths = (numerator * 10000n + denominator / 2n) / denominator;
  return `${hundredths / 100n}.${String(hundredths % 100n).padStart(2, '0')}%`;
}

export function monthIndex(month: string): number {
  return Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1;
}

export function adjacentMonths(before: string, after: string): boolean {
  return monthIndex(after) - monthIndex(before) === 1;
}

export type PlotPoint = { month: string; value: string | null };

// Break the line at unknown values and absent months; never imply continuity through missing data.
export function chartSegments(points: PlotPoint[], min: number, max: number): string[] {
  const paths: string[] = [];
  let path = '';
  points.forEach((point, index) => {
    const numeric = point.value == null || point.value.trim() === '' ? NaN : Number(point.value);
    if (!Number.isFinite(numeric)) {
      if (path) paths.push(path);
      path = '';
      return;
    }
    if (index > 0 && !adjacentMonths(points[index - 1].month, point.month)) {
      if (path) paths.push(path);
      path = '';
    }
    const x = 20 + (points.length === 1 ? 380 : (index * 760) / (points.length - 1));
    const y = 180 - ((numeric - min) / (max - min || 1)) * 150;
    path += `${path ? ' L' : 'M'} ${x} ${y}`;
  });
  if (path) paths.push(path);
  return paths;
}
