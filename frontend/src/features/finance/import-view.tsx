'use client';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DataForm } from '@/features/personal-data/components/data-form';
import { useSchemaFields } from '@/features/personal-data/hooks/use-schema-fields';

type Preview = { rows: { kind: string; row: Record<string, string>; existing_position_id: string | null; issues: string[] }[] };
export function FinanceImport() {
  const client = useQueryClient();
  const schema = useSchemaFields('/api/market-data/csv/preview');
  const [body, setBody] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState('');
  const preview = useMutation({
    mutationFn: (data: Record<string, unknown>) => customInstance<Preview>({ url: '/api/market-data/csv/preview', method: 'POST', data }),
  });
  const commit = useMutation({
    mutationFn: () => customInstance<{ imported: number }>({ url: '/api/market-data/csv/import', method: 'POST', data: body }),
    onSuccess: async result => {
      setMessage(`${result.imported}개 로컬 항목을 편입했습니다. 기존 원격 파일은 그대로 남아 있습니다.`);
      setBody(null);
      preview.reset();
      await client.invalidateQueries({ queryKey: ['finance'] });
    },
  });
  const coverage = useMutation({
    mutationFn: () => customInstance({ url: '/api/finance/coverage', method: 'PUT', data: { kinds: ['cash', 'holding', 'liability', 'other'] } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['finance'] }),
  });
  return (
    <Card>
      <CardContent className='space-y-3'>
        <h2 className='font-semibold'>CSV로 로컬 재무 기록 이전</h2>
        <p className='text-sm'>
          원본 ID별로 편입하며 같은 종목의 서로 다른 행을 합치지 않습니다. 재실행할 때 같은 원본 ID와 같은 CSV를 사용하세요. 수입·지출은 거래 기록에
          별도로 입력합니다.
        </p>
        <p className='break-words text-xs text-muted-foreground'>
          필수 열: kind,id,currency. kind는 cash,holding,liability,other. 잔액 행은 balance,as_of가 필요하며 보유 행은 ticker,quantity를 포함합니다.
          선택 열: label,avg_cost,price,price_as_of,source,asset_class,account_id,account_label. account_id는 CSV 안 cash 행의 id입니다.
        </p>
        {(schema.error || preview.error || commit.error || coverage.error) && (
          <Alert variant='destructive'>{(schema.error ?? preview.error ?? commit.error ?? coverage.error)?.message}</Alert>
        )}
        {message && <Alert>{message}</Alert>}
        {schema.data && (
          <DataForm
            fields={schema.data}
            labels={{ source_id: '원본 ID (재실행 시 유지)', csv_text: 'CSV 내용' }}
            submitLabel='저장 없이 이전 미리보기'
            onCancel={() => {
              setBody(null);
              preview.reset();
            }}
            onSubmit={async data => {
              setBody(data);
              setMessage('');
              await preview.mutateAsync(data);
            }}
          />
        )}
        {preview.data && (
          <div className='space-y-2'>
            {preview.data.rows.map((entry, i) => (
              <div key={i} className='rounded border p-2 text-sm'>
                {entry.kind} · {entry.row.label || entry.row.id} · {entry.existing_position_id ? '이미 편입됨' : '새 로컬 항목'}
                {entry.issues.map(issue => (
                  <p key={issue} className='text-destructive'>
                    {issue}
                  </p>
                ))}
              </div>
            ))}
            <Button disabled={commit.isPending || preview.data.rows.some(row => row.issues.length > 0)} onClick={() => commit.mutate()}>
              확인한 자료를 로컬에 편입
            </Button>
          </div>
        )}
        <div className='border-t pt-3'>
          <p className='mb-2 text-sm'>
            현금·투자·부채·기타의 모든 항목을 입력했고 기록이 없는 분류에는 실제 보유가 없음을 확인한 경우에만 전체 범위를 확정하세요.
          </p>
          <Button disabled={coverage.isPending} onClick={() => coverage.mutate()}>
            전체 재무 범위 입력 완료 확인
          </Button>
          {coverage.isSuccess && <p className='mt-2 text-sm'>분류별 기록 범위를 확인했습니다.</p>}
        </div>
      </CardContent>
    </Card>
  );
}
