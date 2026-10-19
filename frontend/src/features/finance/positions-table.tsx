import { QualityBadge } from '@/components/quality-badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly } from '@/lib/utils/format';

import { quantityText } from '@/features/holdings/api';

import type { FinanceLine, Portfolio } from './api';
import { issueFlags, money, POSITION_KIND_LABEL } from './presentation';

const ORDER = ['cash', 'holding', 'other', 'liability'];

function lineAmount(line: FinanceLine): string {
  if (line.kind === 'holding') return line.quantity == null ? '수량 확인 필요' : `${quantityText(line.quantity)}주`;
  return money(line.balance, line.currency);
}

/** Every valued position with its own as-of date and findings; read-only. */
export function PositionsTable({ data }: { data: Portfolio }) {
  const lines = [...data.lines].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  if (!lines.length) return null;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>항목</TableHead>
          <TableHead className='text-right'>잔액·수량</TableHead>
          <TableHead className='hidden text-right md:table-cell'>가격 · 환율</TableHead>
          <TableHead className='text-right'>원화 평가액</TableHead>
          <TableHead>상태</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {lines.map((line, index) => (
          <TableRow key={`${line.kind}-${line.id}-${index}`}>
            <TableCell>
              <span className='font-medium'>{line.label}</span>
              <span className='block text-xs text-faint'>
                {POSITION_KIND_LABEL[line.kind] ?? line.kind}
                {line.ticker ? ` · ${line.ticker}` : ''} · {line.currency}
                {line.as_of ? ` · ${dateOnly(line.as_of)} 기준` : ''}
              </span>
            </TableCell>
            <TableCell className='text-right tabular-nums'>{lineAmount(line)}</TableCell>
            <TableCell className='hidden text-right tabular-nums md:table-cell'>
              {line.kind === 'holding' && (
                <span className='block'>
                  {money(line.price, line.currency)}
                  {line.price_as_of && <span className='block text-xs text-faint'>{dateOnly(line.price_as_of)}</span>}
                </span>
              )}
              {line.currency !== 'KRW' && <span className='block text-xs text-faint'>환율 {line.fx_rate ?? '확인 필요'}</span>}
            </TableCell>
            <TableCell className={`text-right tabular-nums ${line.kind === 'liability' ? 'text-destructive' : ''}`}>
              {line.kind === 'liability' && line.value_krw ? '−' : ''}
              {money(line.value_krw)}
            </TableCell>
            <TableCell>{line.issues.length ? <QualityBadge flags={issueFlags(line.issues)} /> : <span className='text-xs text-faint'>확인됨</span>}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
