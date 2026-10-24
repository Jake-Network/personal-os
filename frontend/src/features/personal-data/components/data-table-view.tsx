'use client';

import { type ReactNode, useState } from 'react';

import { Plus } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { dateOnly, dateTime, money, plain } from '@/lib/utils/format';
import { formatDuration } from '@/lib/utils/duration';
import { cn } from '@/lib/utils';

import type { Row } from '../api/resource-api';
import { RESOURCES, enumLabel, fieldLabel } from '../consts/resources';
import { useResourceRows } from '../hooks/use-resource';
import { useRecordParam } from '../hooks/use-record-param';
import { useSchemaFields } from '../hooks/use-schema-fields';
import type { FieldSpec } from '../utils/schema-fields';
import { RecordSheet } from './record-sheet';

const MONEY_FIELDS = new Set(['balance', 'value', 'amount', 'monthly_payment', 'avg_cost', 'last_price']);
const NUMERIC_FIELDS = new Set([
  ...MONEY_FIELDS,
  'quantity',
  'rate',
  'weight',
  'interest_rate',
  'duration_seconds',
  'estimate_minutes',
  'current_value',
  'target_value',
]);

export function cellText(row: Row, col: string, field?: FieldSpec): string {
  const v = row[col];
  if (v === null || v === undefined || v === '') return '—';
  if (col === 'duration_seconds') return formatDuration(v);
  if (MONEY_FIELDS.has(col)) return money(v as string, (row.currency as string) ?? 'KRW');
  if (field?.kind === 'enum') return enumLabel(v);
  if (field?.kind === 'boolean') return v ? '예' : '아니오';
  if (field?.kind === 'date') return dateOnly(v as string);
  if (field?.kind === 'datetime') return dateTime(v as string);
  return plain(v);
}

interface Props {
  resource: string;
  title?: string;
  columns?: string[];
  /** Deep-linked record from `?record=`; only one table per page should take it. */
  recordId?: number | null;
  addLabel?: string;
  emptyText?: string;
  info?: ReactNode;
  /** Custom rendering for a column. */
  render?: Partial<Record<string, (row: Row) => ReactNode>>;
}

/** A plain list of one record type with add/edit in the record sheet. For reference data without a richer view. */
export function ResourceTable({ resource, title, columns, recordId = null, addLabel, emptyText, info, render }: Props) {
  const meta = RESOURCES.find(r => r.name === resource)!;
  const rows = useResourceRows(resource);
  const fields = useSchemaFields(resource);
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const cols = columns ?? meta.columns;
  const fieldMap = Object.fromEntries((fields.data ?? []).map(f => [f.name, f]));
  const editing = selected === null ? null : (rows.data?.find(r => r.id === selected) ?? null);

  return (
    <Section
      title={title ?? meta.label}
      count={rows.data?.length}
      info={info}
      actions={
        <Button size='sm' onClick={() => setCreating(true)}>
          <Plus /> {addLabel ?? '추가'}
        </Button>
      }>
      <QueryStatus pending={rows.isPending} error={rows.error} retry={rows.refetch} label={meta.label} />
      {rows.data && rows.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              {cols.map(c => (
                <TableHead key={c} className={cn(NUMERIC_FIELDS.has(c) && 'text-right')}>
                  {fieldLabel(c)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.data.map(row => (
              <TableRow key={row.id} className='cursor-pointer' onClick={() => setSelected(row.id)}>
                {cols.map((c, i) => (
                  <TableCell key={c} className={cn(NUMERIC_FIELDS.has(c) && 'text-right tabular-nums')}>
                    {i === 0 ? (
                      <button type='button' className='text-left font-medium hover:underline' onClick={() => setSelected(row.id)}>
                        {render?.[c]?.(row) ?? cellText(row, c, fieldMap[c])}
                      </button>
                    ) : (
                      (render?.[c]?.(row) ?? cellText(row, c, fieldMap[c]))
                    )}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {rows.data?.length === 0 && (
        <EmptyState
          action={
            <Button size='sm' variant='primary' onClick={() => setCreating(true)}>
              <Plus /> {addLabel ?? `${meta.label} 추가`}
            </Button>
          }>
          {emptyText ?? `아직 기록된 ${meta.label} 항목이 없습니다.`}
        </EmptyState>
      )}
      <RecordSheet
        resource={resource}
        record={creating ? null : editing}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false);
          setSelected(null);
        }}
      />
    </Section>
  );
}
