'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';

import { useListAccounts } from '@/api-client/generated/personal-data/personal-data';
import { useBalanceCheckIn } from '@/api-client/generated/portfolio/portfolio';
import type { BalanceCheckInResult } from '@/api-client/model';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { relative } from '@/lib/utils/format';
import { todayKey } from '@/lib/utils/zoned';

import { money } from './presentation';

/** Every account's balance on one screen. An empty amount means "still the same as of today". */
export function BalanceCheckInSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const client = useQueryClient();
  const accounts = useListAccounts({ query: { enabled: open } });
  const checkIn = useBalanceCheckIn();
  const today = todayKey();
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [results, setResults] = useState<Record<number, BalanceCheckInResult>>({});
  const rows = accounts.data ?? [];
  const pendingRows = rows.filter(a => !skipped.has(a.id) && results[a.id]?.status !== 'updated' && results[a.id]?.status !== 'confirmed');
  const invalid = pendingRows.some(a => amounts[a.id]?.trim() && !/^-?\d+(\.\d{1,4})?$/.test(amounts[a.id].replaceAll(',', '').trim()));

  const close = (next: boolean) => {
    if (!next) {
      setAmounts({});
      setSkipped(new Set());
      setResults({});
    }
    onOpenChange(next);
  };
  const submit = () =>
    checkIn.mutate(
      {
        data: {
          items: pendingRows.map(a => ({
            account_id: a.id,
            expected_version: a.version,
            balance: amounts[a.id]?.trim() ? amounts[a.id].replaceAll(',', '').trim() : null,
          })),
        },
      },
      {
        onSuccess: async response => {
          setResults(current => ({ ...current, ...Object.fromEntries(response.map(r => [r.account_id, r])) }));
          const failed = response.filter(r => r.status === 'conflict' || r.status === 'not_found').length;
          if (failed) notify.error(`${failed}개 계좌는 저장하지 못했습니다. 최신 값을 확인하세요.`);
          else notify.success('잔고를 오늘 기준으로 맞췄습니다');
          await Promise.all([
            client.invalidateQueries({ queryKey: ['finance'] }),
            client.invalidateQueries({ queryKey: ['/api/data/accounts'] }),
            client.invalidateQueries({ queryKey: ['/api/dashboard/summary'] }),
          ]);
          if (!failed) close(false);
        },
        onError: notify.error,
      },
    );

  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent side='right' className='w-[min(440px,100vw)] overflow-y-auto p-4'>
        <SheetTitle className='text-title font-semibold'>잔고 한 번에 업데이트</SheetTitle>
        <p className='mt-1 text-xs text-muted-foreground'>바뀐 계좌만 금액을 입력하세요. 비워 둔 계좌는 기존 잔액이 오늘도 맞는 것으로 확인합니다. 확인하지 않을 계좌는 체크를 해제하세요.</p>
        <QueryStatus pending={accounts.isPending} error={accounts.error} retry={accounts.refetch} label='계좌' rows={3} />
        {accounts.data?.length === 0 && <p className='mt-4 text-ui text-muted-foreground'>등록한 계좌가 없습니다.</p>}
        <ul className='mt-3 divide-y'>
          {rows.map(a => {
            const result = results[a.id];
            const done = result?.status === 'updated' || result?.status === 'confirmed';
            return (
              <li key={a.id} className='flex flex-col gap-1.5 py-2.5'>
                <div className='flex items-center gap-2'>
                  <Checkbox
                    aria-label={`${a.name} 포함`}
                    checked={!skipped.has(a.id)}
                    disabled={done}
                    onCheckedChange={() =>
                      setSkipped(s => {
                        const next = new Set(s);
                        if (next.has(a.id)) next.delete(a.id);
                        else next.add(a.id);
                        return next;
                      })
                    }
                  />
                  <span className='min-w-0 flex-1 truncate font-medium'>{a.name}</span>
                  <span className={a.balance_as_of === today ? 'text-xs text-success' : a.balance_stale ? 'text-xs text-warning' : 'text-xs text-faint'}>
                    {a.balance_as_of === today ? '오늘 확인' : relative(a.balance_as_of)}
                  </span>
                </div>
                <div className='flex items-center gap-2 pl-6'>
                  <Input
                    aria-label={`${a.name} 새 잔액`}
                    inputMode='decimal'
                    placeholder={`${money(a.balance, a.currency)} 그대로`}
                    value={amounts[a.id] ?? ''}
                    disabled={done || skipped.has(a.id)}
                    onChange={e => setAmounts(m => ({ ...m, [a.id]: e.target.value }))}
                    className='h-8'
                  />
                  <span className='text-xs text-faint'>{a.currency}</span>
                </div>
                {result && <p className={`pl-6 text-xs ${done ? 'text-success' : 'text-destructive'}`}>{result.message}</p>}
              </li>
            );
          })}
        </ul>
        {invalid && <p className='text-xs text-destructive'>금액은 숫자로, 소수점 넷째 자리까지 입력하세요.</p>}
        <div className='mt-4 flex justify-end gap-2'>
          <Button onClick={() => close(false)}>닫기</Button>
          <Button variant='primary' disabled={!pendingRows.length || invalid || checkIn.isPending} onClick={submit}>
            {pendingRows.length}개 계좌 저장
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
