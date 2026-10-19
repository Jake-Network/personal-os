import { money as formatMoney } from '@/lib/utils/format';

export { timestamp } from '@/lib/utils/format';

// API money remains a Decimal string. In finance views a missing amount is one the backend could not establish.
export function money(value: string | null | undefined, currency = 'KRW'): string {
  return formatMoney(value, currency, '확인 필요');
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
    const x = chartX(index, points.length);
    const y = chartY(numeric, min, max);
    path += `${path ? ' L' : 'M'} ${x} ${y}`;
  });
  if (path) paths.push(path);
  return paths;
}

export const POSITION_KIND_LABEL: Record<string, string> = { cash: '현금', holding: '투자', liability: '부채', other: '기타 자산' };

// Valuation and ledger checks report in English for the model; the screen shows the same finding in Korean.
const PROBLEM_TEXT: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^Missing explicit (\w+) coverage$/, m => `${POSITION_KIND_LABEL[m[1]] ?? m[1]} 항목을 모두 입력했는지 확인 전`],
  [/^Unknown position kind$/, () => '알 수 없는 항목 종류'],
  [/^Missing or duplicate position ID$/, () => '항목 구분값이 없거나 중복됨'],
  [/^Invalid currency$/, () => '통화 코드 오류'],
  [/^Missing month-end balance\/quantity evidence$/, () => '월말 잔액·수량 근거 없음'],
  [/^Missing or future balance date$/, () => '잔액 기준일이 없거나 미래 날짜'],
  [/^Stale balance\/quantity$/, () => '잔액·수량 기준일이 오래됨'],
  [/^Missing or invalid FX evidence$/, () => '원화 환율 없음'],
  [/^Stale FX rate$/, () => '환율이 오래됨'],
  [/^Missing quantity$/, () => '수량 없음'],
  [/^Missing applicable close\/price$/, () => '적용할 가격 없음'],
  [/^Stale price; latest valid market close unconfirmed$/, () => '시세가 오래됨'],
  [/^Last valid month-end market close unconfirmed$/, () => '월말 종가 확인 전'],
  [/^GOOGLEFINANCE API values have not been verified$/, () => '자동 시세 검증 전'],
  [/^GOOGLEFINANCE FX values have not been verified$/, () => '자동 환율 검증 전'],
  [/^Valuation unavailable$/, () => '평가 불가'],
  [/^Ledger coverage is not declared complete; recorded flows only$/, () => '거래 기록이 완전하다고 확인되지 않아 기록된 흐름만 합산했습니다'],
  [
    /^Asset changes include unexplained differences; ledger entries alone do not establish investment returns$/,
    () => '자산 변화에 설명되지 않은 차이가 있어 거래 기록만으로 투자 수익을 판단할 수 없습니다',
  ],
];

function problemText(problem: string): string {
  for (const [pattern, text] of PROBLEM_TEXT) {
    const m = problem.match(pattern);
    if (m) return text(m);
  }
  return problem;
}

/** "Label: Problem" findings keep the label and translate the problem. */
export function issueText(issue: string): string {
  const i = issue.lastIndexOf(': ');
  if (i > 0) {
    const translated = problemText(issue.slice(i + 2));
    if (translated !== issue.slice(i + 2)) return `${issue.slice(0, i)}: ${translated}`;
  }
  return problemText(issue);
}

/** Findings as QualityBadge flags (their text is already final, so it is passed as the code). */
export function issueFlags(issues: string[] | undefined): { code: string }[] {
  return (issues ?? []).map(issue => ({ code: issueText(issue) }));
}

/** About `count` round tick values covering [min, max], for the chart's y-axis. */
export function axisTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (max === min) return [min];
  const raw = (max - min) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * power).find(s => s >= raw) ?? 10 * power;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Math.round(v / step) * step);
  return ticks;
}

/** Y coordinate used by chartSegments, so ticks and lines line up. */
export function chartY(value: number, min: number, max: number): number {
  return 180 - ((value - min) / (max - min || 1)) * 150;
}

/** X coordinate used by chartSegments. */
export function chartX(index: number, count: number): number {
  return 20 + (count === 1 ? 380 : (index * 760) / (count - 1));
}
