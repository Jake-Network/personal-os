'use client';

import { useState } from 'react';

import Link from 'next/link';

import { useQueryClient } from '@tanstack/react-query';
import { Undo2 } from 'lucide-react';

import { useUndoDataOperation } from '@/api-client/generated/advisor/advisor';
import { notify } from '@/components/notify';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RESOURCES } from '@/features/personal-data/consts/resources';

import { canUndo, dataOperationHref, type DataOperation, invalidateDataOperationQueries } from '../data-operations';

const STATUS: Record<DataOperation['status'], { label: string; tone: BadgeProps['variant'] }> = {
  saved: { label: '저장됨', tone: 'success' },
  read: { label: '조회 완료', tone: 'default' },
  needs_input: { label: '확인 필요', tone: 'warning' },
  failed: { label: '실패', tone: 'destructive' },
};

/** Only server execution receipts appear here; model proposals use their approval cards. */
function UndoButton({ operation, onUndone }: { operation: DataOperation; onUndone: () => void }) {
  const client = useQueryClient();
  const undo = useUndoDataOperation();
  return (
    <Button
      size='sm'
      variant='ghost'
      disabled={undo.isPending}
      onClick={() =>
        undo.mutate(
          { receiptId: operation.receipt_id! },
          {
            onSuccess: async () => {
              onUndone();
              notify.success(operation.operation === 'create' ? '저장한 기록을 지웠습니다' : '이전 값으로 되돌렸습니다');
              await invalidateDataOperationQueries(client, [operation]);
            },
            onError: notify.error,
          },
        )
      }>
      <Undo2 /> 되돌리기
    </Button>
  );
}

export function DataOperationResults({ operations }: { operations: DataOperation[] }) {
  const [undone, setUndone] = useState<Set<number>>(new Set());
  if (!operations.length) return null;
  return (
    <ul aria-label='데이터 처리 결과' className='mt-2 divide-y rounded-lg border bg-card px-3.5'>
      {operations.map((operation, index) => {
        const state = STATUS[operation.status];
        const reverted = operation.undone || (operation.receipt_id !== undefined && undone.has(operation.receipt_id));
        const label = reverted ? '되돌림' : operation.status === 'saved'
          ? operation.operation === 'delete' ? '삭제됨' : operation.operation === 'update' ? '수정됨' : state.label
          : state.label;
        const href = dataOperationHref(operation);
        const resourceLabel = RESOURCES.find(meta => meta.name === operation.resource)?.label ?? '개인 기록';
        const targetLabel = typeof operation.target_label === 'string' ? operation.target_label.trim() : '';
        return (
          <li key={index} className='flex flex-col gap-1.5 py-2.5'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='break-words text-ui font-medium'>{targetLabel ? `${resourceLabel} · ${targetLabel}` : resourceLabel}</span>
              <Badge variant={reverted ? 'default' : state.tone}>{label}</Badge>
              <span className='ml-auto flex items-center gap-2'>
                {canUndo(operation) && !reverted && (
                  <UndoButton operation={operation} onUndone={() => setUndone(current => new Set(current).add(operation.receipt_id!))} />
                )}
                {href && !reverted && <Link href={href} className='text-xs text-primary hover:underline'>관리 화면</Link>}
              </span>
            </div>
            <p className='whitespace-pre-wrap break-words text-ui text-muted-foreground'>{operation.message}</p>
          </li>
        );
      })}
    </ul>
  );
}
