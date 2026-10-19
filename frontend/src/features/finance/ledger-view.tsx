'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import { notify } from '@/components/notify';
import { ListSkeleton } from '@/components/skeleton';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';

import { DataForm } from '@/features/personal-data/components/data-form';
import { useSchemaFields } from '@/features/personal-data/hooks/use-schema-fields';

import { TRANSACTION_KIND_LABEL } from './transaction-kinds';

const LABELS = {
  kind: '거래 종류',
  occurred_at: '거래 시각',
  account_id: '출금·기록 계좌',
  counterparty_account_id: '받는 계좌',
  holding_id: '보유 종목',
  amount: '금액',
  currency: '통화',
  quantity: '바뀐 수량',
  source: '근거·출처',
  note: '메모',
  reverses_id: '취소할 거래',
};

export type LedgerEntry = {
  id: number;
  kind: string;
  occurred_at: string;
  recorded_at: string;
  amount: string | null;
  currency: string;
  source: string;
  note: string | null;
  reverses_id?: number | null;
  is_reversed: boolean;
};

export interface LedgerDraft {
  /** Generated when the sheet opens and kept across retries, so a lost response can't record twice. */
  request_id: string;
  kind?: string;
  reverses_id?: number;
  currency?: string;
}

/** Append-only ledger entry form. Recording a transaction does not change balances or quantities. */
export function LedgerEntrySheet({
  draft,
  title,
  onClose,
  allowedKinds,
}: {
  draft: LedgerDraft;
  title: string;
  allowedKinds?: string[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const schema = useSchemaFields('/api/finance/transactions');
  const record = useMutation({
    retry: false,
    mutationFn: (data: Record<string, unknown>) => customInstance({ url: '/api/finance/transactions', method: 'POST', data }),
    onSuccess: () => {
      notify.success('거래를 기록했습니다. 잔액과 수량은 따로 갱신하세요');
      onClose();
    },
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['finance'] }), client.invalidateQueries({ queryKey: ['/api/dashboard'] })]),
  });
  return (
    <Sheet open onOpenChange={open => !open && onClose()}>
      <SheetContent side='right' className='w-[min(480px,100vw)] overflow-y-auto'>
        <div className='flex flex-col gap-3 p-5'>
          <SheetTitle className='pr-8 text-title font-semibold'>{title}</SheetTitle>
          {schema.isPending && <ListSkeleton rows={5} />}
          {schema.data && (
            <DataForm
              fields={schema.data.map(field =>
                field.name === 'kind' && allowedKinds ? { ...field, options: field.options?.filter(option => allowedKinds.includes(option)) } : field,
              )}
              labels={LABELS}
              enumLabels={TRANSACTION_KIND_LABEL}
              hidden={['request_id', ...(draft.reverses_id ? ['reverses_id', 'kind', 'currency'] : [])]}
              current={{ currency: 'KRW', ...draft }}
              submitLabel='기록'
              onCancel={onClose}
              onSubmit={record.mutateAsync}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
