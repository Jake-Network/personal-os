'use client';

import { useState } from 'react';
import Link from 'next/link';

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
import { financeApi } from '@/features/finance/api';
import { SheetsHoldingsView } from '@/features/holdings/holdings-view';

import { RESOURCE_API, type Row } from '../api/resource-api';
import { RESOURCES, enumLabel, fieldLabel } from '../consts/resources';
import { useSchemaFields } from '../hooks/use-schema-fields';
import type { FieldSpec } from '../utils/schema-fields';
import { DataForm } from './data-form';
import { HISTORY_RESOURCES, ValueHistoryDialog } from './value-history-dialog';

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
  return resource === 'holdings' ? <SheetsHoldingsView /> : <LegacyDataTableView resource={resource} />;
}

function LegacyDataTableView({ resource }: { resource: string }) {
  const meta = RESOURCES.find(r => r.name === resource);
  const api = RESOURCE_API[resource];
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Row | 'new' | null>(null);
  const [historyOf, setHistoryOf] = useState<Row | null>(null);
  const sheetResource = ['accounts', 'holdings', 'fx-rates', 'other-assets', 'liabilities'].includes(resource);
  const sheets = useQuery({ queryKey: ['finance', 'settings'], queryFn: financeApi.settings, enabled: sheetResource });
  const readOnly = sheetResource && (sheets.isPending || !!sheets.error || !!sheets.data?.spreadsheet_id);

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
  const loadError = fields.error ?? rows.error ?? (sheetResource ? sheets.error : null);

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
          <Button variant='primary' disabled={!fields.data || readOnly} onClick={() => setEditing('new')}>
            추가
          </Button>
        }
      />
      {readOnly && (
        <Alert className='mb-3'>
          {sheets.data?.spreadsheet_id
            ? 'Google Sheets 연결 상태에서는 시트에서 수정하세요. 이 화면의 기존 수동 데이터는 포트폴리오 평가에 사용하지 않습니다. '
            : 'Google Sheets 연결 상태를 확인할 때까지 편집을 잠시 제한합니다. '}
          <Link href='/finance' className='underline'>
            동기화된 포트폴리오 보기
          </Link>
        </Alert>
      )}

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
                  {HISTORY_RESOURCES.has(resource) && (
                    <Button size='sm' variant='ghost' onClick={() => setHistoryOf(row)}>
                      이력
                    </Button>
                  )}
                  <Button size='sm' variant='ghost' disabled={readOnly} onClick={() => setEditing(row)}>
                    수정
                  </Button>
                  <Button
                    size='sm'
                    variant='ghost-destructive'
                    disabled={readOnly}
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

      <Dialog open={!!editing && !!fields.data && !readOnly} onOpenChange={open => !open && setEditing(null)}>
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

      {historyOf && (
        <ValueHistoryDialog
          resource={resource}
          id={historyOf.id}
          label={String(historyOf.name ?? historyOf.symbol ?? meta.label)}
          onClose={() => setHistoryOf(null)}
        />
      )}
    </PageContainer>
  );
}
