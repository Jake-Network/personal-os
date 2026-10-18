'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input, fieldClassName } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { financeApi } from '@/features/finance/api';
import { googleOriginMismatch } from '@/features/finance/google-setup';
import { money, timestamp } from '@/features/finance/presentation';
import { holdingDraft, holdingsApi, type HoldingInput, type SheetHolding } from './api';

const subscribe = () => () => undefined;
const origin = () => window.location.origin;
const serverOrigin = () => '';
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
  const configured = !!settings.data?.spreadsheet_id;
  const holdings = useQuery({ queryKey: ['finance', 'holdings'], queryFn: holdingsApi.list, enabled: configured });
  const [draft, setDraft] = useState<HoldingInput | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const browserOrigin = useSyncExternalStore(subscribe, origin, serverOrigin);
  const mismatch = googleOriginMismatch(browserOrigin, google.data?.setup);
  const invalidCallback = !!google.data?.setup && (!google.data.setup.redirect_uri_supported || !google.data.setup.callback_host_matches_frontend);
  const login = useMutation({
    mutationFn: () => financeApi.googleLogin(true, 'holdings'),
    onSuccess: data => window.location.assign(data.authorize_url),
  });
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
    if (!configured || !initialized || mismatch) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshRef.current();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [configured, initialized, mismatch]);
  const initialize = useMutation({ mutationFn: holdingsApi.initialize, onSuccess: invalidate });
  const save = useMutation({
    mutationFn: holdingsApi.save,
    onSuccess: data => {
      setDraft(null);
      setSavedMessage(
        data.quote_status === 'ready'
          ? 'Google Sheets에 저장했습니다.'
          : 'Google Sheets에 저장했습니다. 시세 계산을 기다리는 중이며 자동으로 다시 조회합니다.',
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
  const canWrite = !!holdings.data?.can_write && !mismatch;
  const busy = save.isPending || initialize.isPending || refresh.isPending;
  const error = settings.error ?? google.error ?? holdings.error ?? login.error ?? initialize.error ?? save.error ?? refresh.error;

  return (
    <PageContainer className='space-y-4'>
      <PageHeader
        title='보유 종목'
        description='종목과 수량을 입력하면 Google Sheets에 저장하고 GOOGLEFINANCE 시세로 평가합니다.'
        actions={
          <Button asChild>
            <Link href='/finance'>포트폴리오 · 시트 설정</Link>
          </Button>
        }
      />
      <Alert>
        시세는 최대 20분 지연될 수 있습니다. 이 화면이 열려 있는 동안 60초마다 조회합니다. 시세·환율·평가액은 읽기 전용이며 누락 값은 0으로 계산하지
        않습니다.
      </Alert>
      {error && <Alert variant='destructive'>{error.message}</Alert>}
      {!configured && (
        <Alert variant='warning'>
          <Link href='/finance' className='underline'>
            포트폴리오 설정
          </Link>
          에서 Google 계정 연결 후 비공개 스프레드시트 ID를 저장하세요.
        </Alert>
      )}
      {mismatch && google.data?.setup && (
        <Alert variant='warning'>
          현재 주소에서는 시트 변경을 수행할 수 없습니다.{' '}
          <a className='underline' href={new URL('/data/holdings', google.data.setup.frontend_url).href}>
            Google 로그인 주소의 보유 종목 화면으로 이동
          </a>
          하세요.
        </Alert>
      )}
      {configured && !canWrite && (
        <Card>
          <CardContent className='space-y-3'>
            <p>앱에서 보유 종목을 저장하려면 Google Sheets 읽기·쓰기 권한으로 계정을 연결하세요. 기존 읽기 권한만으로는 저장할 수 없습니다.</p>
            {mismatch && google.data?.setup ? (
              <Button asChild>
                <a href={new URL('/data/holdings', google.data.setup.frontend_url).href}>Google 로그인 주소로 이동</a>
              </Button>
            ) : (
              <Button disabled={!google.data?.configured || login.isPending || invalidCallback || google.isPending} onClick={() => login.mutate()}>
                보유 종목 저장 권한 연결
              </Button>
            )}
            <p className='text-xs text-muted-foreground'>
              Google 연결 및 권한 설정은{' '}
              <Link href='/finance' className='underline'>
                포트폴리오 설정
              </Link>
              에서 확인할 수 있습니다.
            </p>
          </CardContent>
        </Card>
      )}
      {configured && canWrite && !initialized && (
        <Card>
          <CardContent className='space-y-3'>
            <p>선택한 스프레드시트에 포트폴리오용 워크시트를 준비하세요. 이 버튼은 없는 탭과 조회 검증용 수식을 추가합니다.</p>
            <Button disabled={busy} onClick={() => initialize.mutate()}>
              시트 워크시트 준비
            </Button>
          </CardContent>
        </Card>
      )}
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
          <Button disabled={!initialized || busy || mismatch} onClick={() => refresh.mutate()}>
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
                  자동 시세는 거래소를 포함한 코드(예: NASDAQ:AAPL)를 사용하세요. 지원하지 않는 종목은 수동 가격을 선택하세요. 외화는 시트에 기록된
                  환율로 KRW 평가합니다.
                </p>
                <div className='flex gap-2 sm:col-span-2'>
                  <Button type='submit' variant='primary' disabled={busy || !canWrite}>
                    Google Sheets에 저장
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
      {holdings.isPending && configured && <p role='status'>시트 보유 종목을 불러오는 중…</p>}
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
                      {row.ticker} · {row.currency}
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
        {holdings.data && !holdings.data.rows.length && <p className='p-4 text-muted-foreground'>시트에 저장된 보유 종목이 없습니다.</p>}
      </Card>
    </PageContainer>
  );
}
