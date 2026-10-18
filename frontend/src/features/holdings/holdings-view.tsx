'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input, fieldClassName } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { financeApi } from '@/features/finance/api';
import { money, timestamp } from '@/features/finance/presentation';
import { holdingDraft, holdingsApi, type HoldingInput, type SheetHolding } from './api';

const blank = (): HoldingInput => ({
  position_id: crypto.randomUUID(),
  request_id: crypto.randomUUID(),
  ticker: '',
  quantity: '',
  currency: 'USD',
  label: '',
  avg_cost: null,
  asset_class: 'equity',
  quote_mode: 'auto',
  manual_price: null,
  price_as_of: null,
});

export function SheetsHoldingsView() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ['finance', 'settings'], queryFn: financeApi.settings });
  const google = useQuery({ queryKey: ['finance', 'google'], queryFn: financeApi.googleStatus });
  const configured = true;
  const holdings = useQuery({ queryKey: ['finance', 'holdings'], queryFn: holdingsApi.list, enabled: true });
  const [draft, setDraft] = useState<HoldingInput | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const invalidate = () => client.invalidateQueries({ queryKey: ['finance'] });
  const refresh = useMutation({
    mutationFn: holdingsApi.refresh,
    onSuccess: data => {
      client.setQueryData(['finance', 'holdings'], data);
      void client.invalidateQueries({ queryKey: ['finance', 'portfolio'] });
    },
  });
  const { mutate: refreshQuotes, isPending: refreshing } = refresh;
  const refreshRef = useRef(() => refreshQuotes());
  useEffect(() => {
    refreshRef.current = () => {
      if (!refreshing) refreshQuotes();
    };
  }, [refreshQuotes, refreshing]);
  const initialized = !!holdings.data?.initialized;
  useEffect(() => {
    if (!initialized) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshRef.current();
    }, 300_000);
    return () => window.clearInterval(timer);
  }, [initialized]);
  const initialize = useMutation({ mutationFn: holdingsApi.initialize, onSuccess: invalidate });
  const save = useMutation({
    mutationFn: holdingsApi.save,
    onSuccess: data => {
      setDraft(null);
      setSavedMessage(
        data.quote_status === 'ready' ? '로컬 DB에 저장했습니다.' : '로컬 DB에 저장했습니다. 자동 시세 연결 후 가격을 갱신할 수 있습니다.',
      );
      void invalidate();
      refresh.mutate();
    },
  });
  const update = (values: Partial<HoldingInput>) => {
    setDraft(current => (current ? { ...current, ...values, request_id: crypto.randomUUID() } : current));
  };
  const edit = (row: SheetHolding) => {
    setSavedMessage(null);
    save.reset();
    setDraft(holdingDraft(row, crypto.randomUUID()));
  };
  const canWrite = !!holdings.data?.can_write;
  const busy = save.isPending || initialize.isPending || refresh.isPending;
  const error = settings.error ?? google.error ?? holdings.error ?? initialize.error ?? save.error ?? refresh.error;

  return (
    <PageContainer className='space-y-4'>
      <PageHeader
        title='보유 종목'
        description='종목·수량·원가는 이 컴퓨터에 저장합니다. Google에는 공개 시세 조회용 티커만 전송합니다.'
        actions={
          <Button asChild>
            <Link href='/finance'>포트폴리오 · 시세 연결</Link>
          </Button>
        }
      />
      <Alert>
        시세는 최대 20분 지연될 수 있습니다. 이 화면이 열려 있는 동안 5분마다 조회합니다. 시세·환율·평가액은 읽기 전용이며 누락 값은 0으로 계산하지
        않습니다.
      </Alert>
      {error && <Alert variant='destructive'>{error.message}</Alert>}
      {holdings.data?.warning && <Alert variant='warning'>{holdings.data.warning}</Alert>}
      {holdings.data?.portfolio.stale && (
        <Alert variant='warning'>시세 또는 동기화 정보가 오래되었습니다. 마지막 성공 값과 기준일을 확인하세요.</Alert>
      )}
      {holdings.data && !holdings.data.portfolio.complete && (
        <Alert variant='warning'>평가가 불완전합니다. {holdings.data.portfolio.issues.join(' · ')}</Alert>
      )}
      {savedMessage && <Alert>{savedMessage}</Alert>}
      {configured && (
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='primary'
            disabled={!canWrite || !initialized || busy}
            onClick={() => {
              setDraft(blank());
              setSavedMessage(null);
              save.reset();
            }}>
            종목 추가
          </Button>
          <Button disabled={!initialized || busy} onClick={() => refresh.mutate()}>
            시세 다시 조회
          </Button>
          <span className='self-center text-xs text-muted-foreground'>최근 동기화: {timestamp(holdings.data?.settings.last_success_at)}</span>
        </div>
      )}
      {draft && (
        <Card>
          <CardContent>
            <form
              className='grid gap-3 sm:grid-cols-2'
              onSubmit={event => {
                event.preventDefault();
                save.mutate({ ...draft, ticker: draft.ticker.trim().toUpperCase(), label: draft.label.trim() || draft.ticker.trim().toUpperCase() });
              }}>
              <fieldset className='contents' disabled={save.isPending || !canWrite}>
                <label>
                  종목 코드 *<Input required value={draft.ticker} placeholder='NASDAQ:AAPL' onChange={e => update({ ticker: e.target.value })} />
                </label>
                <label>
                  이름
                  <Input value={draft.label} placeholder='Apple' onChange={e => update({ label: e.target.value })} />
                </label>
                <label>
                  보유 수량 *
                  <Input
                    required
                    inputMode='decimal'
                    pattern='[0-9]+(\.[0-9]+)?'
                    value={draft.quantity}
                    onChange={e => update({ quantity: e.target.value })}
                  />
                </label>
                <label>
                  평균 매수가
                  <Input
                    inputMode='decimal'
                    pattern='[0-9]+(\.[0-9]+)?'
                    value={draft.avg_cost ?? ''}
                    onChange={e => update({ avg_cost: e.target.value || null })}
                  />
                </label>
                <label>
                  통화 *
                  <Input
                    required
                    pattern='[A-Z]{3}'
                    value={draft.currency}
                    placeholder='USD / KRW'
                    onChange={e => update({ currency: e.target.value.toUpperCase() })}
                  />
                </label>
                <label>
                  자산 종류
                  <select
                    className={fieldClassName}
                    value={draft.asset_class}
                    onChange={e => update({ asset_class: e.target.value as HoldingInput['asset_class'] })}>
                    <option value='equity'>주식</option>
                    <option value='etf'>ETF</option>
                    <option value='crypto'>가상자산</option>
                    <option value='bond'>채권</option>
                    <option value='other'>기타</option>
                  </select>
                </label>
                <label>
                  가격 조회
                  <select
                    className={fieldClassName}
                    value={draft.quote_mode}
                    onChange={e => update({ quote_mode: e.target.value as 'auto' | 'manual' })}>
                    <option value='auto'>GOOGLEFINANCE 자동 시세</option>
                    <option value='manual'>수동 가격 (미지원 종목)</option>
                  </select>
                </label>
                {draft.quote_mode === 'manual' && (
                  <>
                    <label>
                      수동 가격 *
                      <Input
                        required
                        inputMode='decimal'
                        pattern='[0-9]+(\.[0-9]+)?'
                        value={draft.manual_price ?? ''}
                        onChange={e => update({ manual_price: e.target.value || null })}
                      />
                    </label>
                    <label>
                      가격 기준일 *
                      <Input required type='date' value={draft.price_as_of ?? ''} onChange={e => update({ price_as_of: e.target.value || null })} />
                    </label>
                  </>
                )}
                <p className='text-xs text-muted-foreground sm:col-span-2'>
                  자동 시세는 거래소를 포함한 코드(예: NASDAQ:AAPL)를 사용하세요. 지원하지 않는 종목은 수동 가격을 선택하세요. 외화는 로컬에 기록된
                  환율로 KRW 평가합니다.
                </p>
                <div className='flex gap-2 sm:col-span-2'>
                  <Button type='submit' variant='primary' disabled={busy || !canWrite}>
                    로컬에 저장
                  </Button>
                  <Button type='button' disabled={save.isPending} onClick={() => setDraft(null)}>
                    취소
                  </Button>
                </div>
              </fieldset>
            </form>
          </CardContent>
        </Card>
      )}
      {holdings.isPending && configured && <p role='status'>로컬 보유 종목을 불러오는 중…</p>}
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              {['종목', '수량', '평균 매수가', '시세 / 기준일', 'KRW 평가액', '상태', ''].map((heading, i) => (
                <TableHead key={i}>{heading}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {(holdings.data?.rows ?? []).map(row => {
              const line = holdings.data?.portfolio.lines.find(item => item.kind === 'holding' && item.id === row.position_id);
              return (
                <TableRow key={row.position_id}>
                  <TableCell>
                    {row.label || row.ticker}
                    <small className='block text-faint'>
                      {row.ticker} · {row.currency} · 로컬 ID {row.record_id ?? row.position_id}
                    </small>
                  </TableCell>
                  <TableCell>{row.quantity ?? '확인 필요'}</TableCell>
                  <TableCell>{money(row.avg_cost, row.currency)}</TableCell>
                  <TableCell>
                    {money(line?.price, row.currency)}
                    <small className='block text-faint'>{timestamp(line?.price_as_of)}</small>
                  </TableCell>
                  <TableCell>{money(line?.value_krw)}</TableCell>
                  <TableCell>
                    {row.quote_status && row.quote_status !== 'ready' && (
                      <p>
                        {(
                          { pending: '시세 계산 대기', unsupported: '미지원 / 가격 없음', provider_error: '시세 제공자 오류' } as Record<
                            string,
                            string
                          >
                        )[row.quote_status] ?? row.quote_status}
                      </p>
                    )}
                    {line?.issues.length
                      ? line.issues.join(' · ')
                      : line?.price
                        ? row.quote_mode === 'manual'
                          ? '수동 가격'
                          : '자동 시세'
                        : '시세 계산 대기 / 지원 여부 확인 필요'}
                  </TableCell>
                  <TableCell>
                    <Button size='sm' disabled={!canWrite || busy} onClick={() => edit(row)}>
                      수정
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {holdings.data && !holdings.data.rows.length && <p className='p-4 text-muted-foreground'>로컬에 저장된 보유 종목이 없습니다.</p>}
      </Card>
    </PageContainer>
  );
}
