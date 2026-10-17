'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { dateOnly, dateTime, money, plain } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import { RESOURCE_API, type Row } from '../api/resource-api';
import { RESOURCES, enumLabel, fieldLabel } from '../consts/resources';
import { useSchemaFields } from '../hooks/use-schema-fields';
import type { FieldSpec } from '../utils/schema-fields';
import { DataForm } from './data-form';

const MONEY_FIELDS = new Set(['balance', 'value', 'amount', 'monthly_payment', 'avg_cost', 'last_price']);
const NUMERIC_FIELDS = new Set([
  ...MONEY_FIELDS,
  'quantity',
  'rate',
  'weight',
  'interest_rate',
  'duration_minutes',
  'estimate_minutes',
  'current_value',
  'target_value',
]);

function cell(row: Row, col: string, field?: FieldSpec): string {
  const v = row[col];
  if (v === null || v === undefined || v === '') return '—';
  if (MONEY_FIELDS.has(col)) return money(v as string, (row.currency as string) ?? 'KRW');
  if (field?.kind === 'enum') return enumLabel(v);
  if (field?.kind === 'date') return dateOnly(v as string);
  if (field?.kind === 'datetime') return dateTime(v as string);
  return plain(v);
}

export function DataTableView({ resource }: { resource: string }) {
  const meta = RESOURCES.find(r => r.name === resource);
  const api = RESOURCE_API[resource];
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Row | 'new' | null>(null);

  const fields = useSchemaFields(resource);
  const rows = useQuery({ queryKey: api?.queryKey ?? ['unknown', resource], queryFn: () => api.list(), enabled: !!api });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: api.queryKey });
  const save = useMutation({
    mutationFn: (payload: Record<string, unknown>) => (editing === 'new' ? api.create(payload) : api.update((editing as Row).id, payload)),
    onSuccess: () => {
      setEditing(null);
      return invalidate();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.remove(id), onSuccess: invalidate, onError: notify.error });

  if (!meta || !api) {
    return (
      <PageContainer>
        <EmptyState>알 수 없는 데이터 종류입니다.</EmptyState>
      </PageContainer>
    );
  }
  const fieldMap = Object.fromEntries((fields.data ?? []).map(f => [f.name, f]));
  const loadError = fields.error ?? rows.error;

  return (
    <PageContainer>
      <PageHeader
        eyebrow={meta.group}
        title={meta.label}
        description={
          meta.financial
            ? '직접 입력한 값만 사용합니다. AI는 이 데이터를 변경할 수 없고, 모든 변경은 감사로그에 남습니다.'
            : 'AI 상담이 이 데이터를 조회해 답변합니다.'
        }
        actions={
          <Button variant='primary' disabled={!fields.data} onClick={() => setEditing('new')}>
            추가
          </Button>
        }
      />

      {loadError && (
        <Alert variant='destructive' className='mb-3'>
          {loadError.message}
        </Alert>
      )}

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              {meta.columns.map(c => (
                <TableHead key={c} className={cn(NUMERIC_FIELDS.has(c) && 'text-right')}>
                  {fieldLabel(c)}
                </TableHead>
              ))}
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {(rows.data ?? []).map(row => (
              <TableRow key={row.id}>
                {meta.columns.map(c => (
                  <TableCell key={c} className={cn(NUMERIC_FIELDS.has(c) && 'text-right tabular-nums')}>
                    {cell(row, c, fieldMap[c])}
                  </TableCell>
                ))}
                <TableCell className='whitespace-nowrap text-right'>
                  <Button size='sm' variant='ghost' onClick={() => setEditing(row)}>
                    수정
                  </Button>
                  <Button
                    size='sm'
                    variant='ghost-destructive'
                    onClick={() => confirm(`이 ${meta.label} 항목을 삭제할까요?`) && remove.mutate(row.id)}>
                    삭제
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {rows.data?.length === 0 && <EmptyState>아직 등록된 {meta.label}이(가) 없습니다.</EmptyState>}
        {rows.isPending && <EmptyState>불러오는 중…</EmptyState>}
      </Card>

      <Dialog open={!!editing && !!fields.data} onOpenChange={open => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {meta.label} {editing === 'new' ? '추가' : '수정'}
            </DialogTitle>
            <DialogDescription>필수 항목은 *로 표시됩니다.</DialogDescription>
          </DialogHeader>
          {editing && fields.data && (
            <DataForm
              fields={fields.data}
              current={editing === 'new' ? undefined : editing}
              submitLabel={editing === 'new' ? '추가' : '저장'}
              onSubmit={save.mutateAsync}
              onCancel={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
