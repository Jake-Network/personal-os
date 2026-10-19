'use client';

import { useState } from 'react';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { DataForm } from '@/features/personal-data/components/data-form';
import { useSchemaFields } from '@/features/personal-data/hooks/use-schema-fields';

import { POSITION_KIND_LABEL } from './presentation';

type Preview = { rows: { kind: string; row: Record<string, string>; existing_position_id: string | null; issues: string[] }[] };

export const CSV_FORMAT_HELP = (
  <>
    <p>필수 열: kind, id, currency. kind는 cash, holding, liability, other 중 하나입니다.</p>
    <p>잔액 행은 balance와 as_of, 보유 행은 ticker와 quantity가 필요합니다.</p>
    <p>선택 열: label, avg_cost, price, price_as_of, source, asset_class, account_id, account_label. account_id는 같은 CSV 안 cash 행의 id입니다.</p>
    <p>원본 번호와 행 id로 구분해 옮기므로, 다시 실행할 때는 같은 원본 번호와 같은 CSV를 쓰세요. 수입·지출은 거래로 따로 기록합니다.</p>
  </>
);

/** Moves balances and holdings from a CSV into local records, always after a preview. */
export function FinanceImport() {
  const client = useQueryClient();
  const schema = useSchemaFields('/api/market-data/csv/preview');
  const [body, setBody] = useState<Record<string, unknown> | null>(null);
  const preview = useMutation({
    mutationFn: (data: Record<string, unknown>) => customInstance<Preview>({ url: '/api/market-data/csv/preview', method: 'POST', data }),
  });
  const commit = useMutation({
    mutationFn: () => customInstance<{ imported: number }>({ url: '/api/market-data/csv/import', method: 'POST', data: body }),
    onSuccess: async result => {
      notify.success(`${result.imported}개 항목을 로컬 기록으로 옮겼습니다`);
      setBody(null);
      preview.reset();
      await client.invalidateQueries({ queryKey: ['finance'] });
    },
    onError: notify.error,
  });
  return (
    <div className='flex flex-col gap-3'>
      {(schema.error || preview.error) && <Alert variant='destructive'>{(schema.error ?? preview.error)?.message}</Alert>}
      {schema.data && (
        <DataForm
          fields={schema.data}
          labels={{ source_id: '원본 번호 (다시 실행해도 같게)', csv_text: 'CSV 내용' }}
          submitLabel='미리보기'
          onCancel={() => {
            setBody(null);
            preview.reset();
          }}
          onSubmit={async data => {
            setBody(data);
            await preview.mutateAsync(data);
          }}
        />
      )}
      {preview.data && (
        <>
          <ul className='divide-y rounded-lg border'>
            {preview.data.rows.map((entry, i) => (
              <li key={i} className='flex flex-wrap items-baseline gap-x-2 px-3 py-2 text-ui'>
                <span className='text-xs text-faint'>{POSITION_KIND_LABEL[entry.kind] ?? entry.kind}</span>
                <span className='font-medium'>{entry.row.label || entry.row.id}</span>
                <span className='ml-auto text-xs'>{entry.existing_position_id ? '이미 옮김' : '새 항목'}</span>
                {entry.issues.map(issue => (
                  <span key={issue} className='basis-full text-xs text-destructive'>
                    {issue}
                  </span>
                ))}
              </li>
            ))}
          </ul>
          <div>
            <Button variant='primary' disabled={commit.isPending || preview.data.rows.some(row => row.issues.length > 0)} onClick={() => commit.mutate()}>
              확인하고 로컬로 옮기기
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
