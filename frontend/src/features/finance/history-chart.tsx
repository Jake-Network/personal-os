import { chartSegments } from './presentation';

export type ChartMonth = {
  month: string;
  complete: boolean;
  net_worth_krw: string | null;
  total_assets_krw: string | null;
  total_liabilities_krw: string | null;
};

const SERIES = [
  { key: 'net_worth_krw', label: '순자산', color: '#2563eb' },
  { key: 'total_assets_krw', label: '총자산', color: '#059669' },
  { key: 'total_liabilities_krw', label: '부채', color: '#d97706' },
] as const;

export function HistoryChart({ months }: { months: ChartMonth[] }) {
  const values = months.flatMap(month =>
    month.complete
      ? SERIES.map(series => month[series.key])
          .filter(value => value != null && value.trim() !== '')
          .map(Number)
          .filter(Number.isFinite)
      : [],
  );
  if (!values.length)
    return <p className='py-8 text-center text-muted-foreground'>완전한 월말 평가가 아직 없습니다. 아래 표에서 누락 정보를 확인하세요.</p>;
  const min = Math.min(0, ...values);
  const max = Math.max(...values);
  return (
    <div>
      <div className='mb-2 flex flex-wrap gap-4 text-xs'>
        {SERIES.map(series => (
          <span key={series.key} style={{ color: series.color }}>
            ● {series.label}
          </span>
        ))}
      </div>
      <svg viewBox='0 0 800 210' className='w-full' role='img' aria-label='월별 순자산, 총자산, 부채 추이 (KRW). 정확한 값은 아래 표에 표시됩니다.'>
        <line x1='20' y1='180' x2='780' y2='180' stroke='currentColor' opacity='.15' />
        <text x='20' y='15' fill='currentColor' fontSize='10'>
          {max.toLocaleString('ko-KR')} KRW
        </text>
        <text x='20' y='207' fill='currentColor' fontSize='10'>
          {months[0]?.month.slice(0, 7)}
        </text>
        <text x='780' y='207' fill='currentColor' fontSize='10' textAnchor='end'>
          {months.at(-1)?.month.slice(0, 7)}
        </text>
        {SERIES.flatMap(series =>
          chartSegments(
            months.map(month => ({ month: month.month, value: month.complete ? month[series.key] : null })),
            min,
            max,
          ).map((path, index) =>
            path.includes(' L') ? (
              <path key={`${series.key}-${index}`} d={path} stroke={series.color} strokeWidth='2.5' strokeLinecap='round' fill='none' />
            ) : (
              <circle key={`${series.key}-${index}`} cx={path.split(' ')[1]} cy={path.split(' ')[2]} r='3' fill={series.color} />
            ),
          ),
        )}
      </svg>
      <p className='text-xs text-faint'>누락·불완전한 월은 선을 연결하지 않습니다. 변화 원인은 거래·입출금 기록 없이는 확정할 수 없습니다.</p>
    </div>
  );
}
