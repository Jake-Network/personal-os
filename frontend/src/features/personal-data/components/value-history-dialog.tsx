'use client';

import { useQuery } from '@tanstack/react-query';

import { getHistoryAccountsQueryOptions, getHistoryHoldingsQueryOptions } from '@/api-client/generated/personal-data/personal-data';
import type { ValueChangeItem } from '@/api-client/model';
import { EmptyState } from '@/components/empty-state';
import { Alert } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { dateOnly, dateTime, money, plain } from '@/lib/utils/format';

import { fieldLabel } from '../consts/resources';

/** Resources whose manual value edits are kept in the append-only history. */
export const HISTORY_RESOURCES = new Set(['accounts', 'holdings']);

const CHANGE_LABEL: Record<string, string> = { baseline: '기존 값', create: '등록', update: '수정', delete: '삭제' };

function historyQuery(resource: string, id: number) {
  return resource === 'accounts' ? getHistoryAccountsQueryOptions(id) : getHistoryHoldingsQueryOptions(id);
}

function value(row: ValueChangeItem, v: ValueChangeItem['new_value']): string {
  if (v === null || v === undefined) return '—';
  return row.field === 'quantity' ? plain(v) : money(v, row.currency);
}

export function ValueHistoryDialog({ resource, id, label, onClose }: { resource: string; id: number; label: string; onClose: () => void }) {
  const history = useQuery(historyQuery(resource, id));
  const rows = [...(history.data ?? [])].reverse();

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{label} 변경 기록</DialogTitle>
          <DialogDescription>직접 입력한 값이 바뀐 기록입니다. 차이는 입력 변경이며 수익이 아닙니다.</DialogDescription>
        </DialogHeader>
        {history.error && <Alert variant='destructive'>{history.error.message}</Alert>}
        {history.isPending && <EmptyState>불러오는 중…</EmptyState>}
        {rows.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>기준일</TableHead>
                <TableHead>항목</TableHead>
                <TableHead>구분</TableHead>
                <TableHead className='text-right'>이전</TableHead>
                <TableHead className='text-right'>변경 후</TableHead>
                <TableHead>기록 시각</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(row => (
                <TableRow key={row.id}>
                  <TableCell>{dateOnly(row.as_of)}</TableCell>
                  <TableCell>{fieldLabel(row.field)}</TableCell>
                  <TableCell>{CHANGE_LABEL[row.change_kind] ?? row.change_kind}</TableCell>
                  <TableCell className='text-right tabular-nums'>{value(row, row.old_value)}</TableCell>
                  <TableCell className='text-right tabular-nums'>{value(row, row.new_value)}</TableCell>
                  <TableCell className='text-faint'>{dateTime(row.recorded_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {history.data?.length === 0 && <EmptyState>아직 기록된 변경이 없습니다.</EmptyState>}
      </DialogContent>
    </Dialog>
  );
}
