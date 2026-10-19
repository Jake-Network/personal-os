'use client';

import { useState } from 'react';

import { monthLabel, moneyShort } from '@/lib/utils/format';

import { axisTicks, chartSegments, chartX, chartY, money } from './presentation';

export type ChartMonth = {
  month: string;
  complete: boolean;
  net_worth_krw: string | null;
  total_assets_krw: string | null;
  total_liabilities_krw: string | null;
};

const SERIES = [
  { key: 'net_worth_krw', label: '순자산', color: 'hsl(var(--primary))' },
  { key: 'total_assets_krw', label: '총자산', color: 'hsl(var(--success))' },
  { key: 'total_liabilities_krw', label: '부채', color: 'hsl(var(--warning))' },
] as const;

/** Monthly totals; a missing or incomplete month breaks the line instead of being bridged. */
export function HistoryChart({ months }: { months: ChartMonth[] }) {
  const [active, setActive] = useState<number | null>(null);
  const values = months.flatMap(month =>
    month.complete
      ? SERIES.map(series => month[series.key])
          .filter(value => value != null && value.trim() !== '')
          .map(Number)
          .filter(Number.isFinite)
      : [],
  );
  if (!values.length) return <p className='py-8 text-center text-muted-foreground'>확정된 월말 기록이 아직 없습니다. 아래 표에서 빠진 근거를 확인하세요.</p>;
  const ticks = axisTicks(Math.min(0, ...values), Math.max(...values));
  // Scale to the tick range so the top tick sits on the plot edge.
  const min = Math.min(0, ...values, ...ticks);
  const max = Math.max(...values, ...ticks);
  const point = active === null ? null : months[active];

  return (
    <div>
      <div className='mb-2 flex flex-wrap gap-4 text-xs text-muted-foreground'>
        {SERIES.map(series => (
          <span key={series.key} className='inline-flex items-center gap-1.5'>
            <span className='h-0.5 w-4 rounded-full' style={{ background: series.color }} aria-hidden />
            {series.label}
          </span>
        ))}
        <span>선이 끊긴 곳은 기록이 없거나 확정되지 않은 달입니다.</span>
      </div>
      <div className='relative'>
        <svg viewBox='-64 0 864 210' className='w-full text-foreground' role='img' aria-label='월별 순자산, 총자산, 부채 추이. 정확한 값은 아래 표와 각 달의 설명에 있습니다.'>
          {ticks.map(t => (
            <g key={t}>
              <line x1='20' x2='780' y1={chartY(t, min, max)} y2={chartY(t, min, max)} stroke='currentColor' opacity={t === 0 ? 0.25 : 0.08} />
              <text x='12' y={chartY(t, min, max) + 3} fill='currentColor' opacity='.6' fontSize='10' textAnchor='end'>
                {moneyShort(t)}
              </text>
            </g>
          ))}
          {months.length > 0 && (
            <>
              <text x={chartX(0, months.length)} y='204' fill='currentColor' opacity='.6' fontSize='10' textAnchor='middle'>
                {monthLabel(months[0].month)}
              </text>
              {months.length > 1 && (
                <text x={chartX(months.length - 1, months.length)} y='204' fill='currentColor' opacity='.6' fontSize='10' textAnchor='middle'>
                  {monthLabel(months.at(-1)!.month)}
                </text>
              )}
            </>
          )}
          {active !== null && <line x1={chartX(active, months.length)} x2={chartX(active, months.length)} y1='25' y2='180' stroke='currentColor' opacity='.2' />}
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
        {/* One focusable column per month for hover and keyboard reading. */}
        <div className='absolute inset-y-0 flex' style={{ left: `${(84 / 864) * 100}%`, right: `${(20 / 864) * 100}%` }} onMouseLeave={() => setActive(null)}>
          {months.map((m, i) => (
            <button
              key={m.month}
              type='button'
              className='h-full flex-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
              style={months.length > 1 ? { flexBasis: 0 } : undefined}
              aria-label={`${monthLabel(m.month)}${m.complete ? '' : ' (확정 안 됨)'}: 순자산 ${money(m.net_worth_krw)}, 총자산 ${money(m.total_assets_krw)}, 부채 ${money(m.total_liabilities_krw)}`}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            />
          ))}
        </div>
        {point && active !== null && (
          <div
            role='presentation'
            className='pointer-events-none absolute top-1 z-10 w-48 -translate-x-1/2 rounded-md border bg-popover p-2 text-xs shadow-md'
            style={{ left: `${((chartX(active, months.length) + 64) / 864) * 100}%` }}>
            <p className='mb-1 font-semibold'>{monthLabel(point.month)}</p>
            {point.complete ? (
              SERIES.map(s => (
                <p key={s.key} className='flex justify-between gap-2'>
                  <span className='text-muted-foreground'>{s.label}</span>
                  <span className='tabular-nums'>{moneyShort(point[s.key], '확인 필요')}</span>
                </p>
              ))
            ) : (
              <p className='text-warning'>근거가 부족해 확정되지 않은 달입니다</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
