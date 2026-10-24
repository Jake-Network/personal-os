import Link from 'next/link';

import { Badge, type BadgeProps } from '@/components/ui/badge';
import { RESOURCES } from '@/features/personal-data/consts/resources';

import { dataOperationHref, type DataOperation } from '../data-operations';

const STATUS: Record<DataOperation['status'], { label: string; tone: BadgeProps['variant'] }> = {
  saved: { label: '저장됨', tone: 'success' },
  read: { label: '조회 완료', tone: 'default' },
  needs_input: { label: '확인 필요', tone: 'warning' },
  failed: { label: '실패', tone: 'destructive' },
};

/** Only server execution receipts appear here; model proposals use their approval cards. */
export function DataOperationResults({ operations }: { operations: DataOperation[] }) {
  if (!operations.length) return null;
  return (
    <ul aria-label='데이터 처리 결과' className='mt-2 divide-y rounded-lg border bg-card px-3.5'>
      {operations.map((operation, index) => {
        const state = STATUS[operation.status];
        const label = operation.status === 'saved'
          ? operation.operation === 'delete' ? '삭제됨' : operation.operation === 'update' ? '수정됨' : state.label
          : state.label;
        const href = dataOperationHref(operation);
        const resourceLabel = RESOURCES.find(meta => meta.name === operation.resource)?.label ?? '개인 기록';
        const targetLabel = typeof operation.target_label === 'string' ? operation.target_label.trim() : '';
        return (
          <li key={index} className='flex flex-col gap-1.5 py-2.5'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='break-words text-ui font-medium'>{targetLabel ? `${resourceLabel} · ${targetLabel}` : resourceLabel}</span>
              <Badge variant={state.tone}>{label}</Badge>
              {href && <Link href={href} className='ml-auto text-xs text-primary hover:underline'>관리 화면</Link>}
            </div>
            <p className='whitespace-pre-wrap break-words text-ui text-muted-foreground'>{operation.message}</p>
          </li>
        );
      })}
    </ul>
  );
}
