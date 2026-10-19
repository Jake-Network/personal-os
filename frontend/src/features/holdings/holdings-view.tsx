'use client';

import { useEffect, useRef, useState } from 'react';

import Link from 'next/link';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly, relative } from '@/lib/utils/format';

import { ResourceTable } from '@/features/personal-data/components/data-table-view';
import type { FinanceLine } from '@/features/finance/api';
import { useMarketStatus } from '@/features/finance/market-connection';
import { issueFlags, money } from '@/features/finance/presentation';

import { holdingDraft, holdingsApi, quantityText, type HoldingInput, type SheetHolding } from './api';

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

const QUOTE_FAILED: Record<string, string> = { unsupported: '자동 시세를 지원하지 않는 종목입니다', provider_error: '시세 제공처 오류' };

/** One status per holding: saved and priced, waiting for a quote, quote failed, or the valuation needs checking. */
function HoldingStatus({ row, line }: { row: SheetHolding; line?: FinanceLine }) {
  if (row.quote_status && QUOTE_FAILED[row.quote_status])
    return (
      <Badge variant='destructive' title={QUOTE_FAILED[row.quote_status]}>
        시세 실패
      </Badge>
    );
  if (row.quote_status === 'pending' || (!line?.price && row.quote_mode === 'auto')) return <Badge variant='warning'>시세 대기</Badge>;
  if (line?.issues.length) return <QualityBadge flags={issueFlags(line.issues)} />;
  return (
    <span className='inline-flex items-center gap-1.5'>
      <Badge variant='success'>저장됨</Badge>
      <span className='text-xs text-faint'>{row.quote_mode === 'manual' ? '수동 가격' : '자동 시세'}</span>
    </span>
  );
}

function HoldingSheet({
  draft,
  isNew,
  canWrite,
  saving,
  error,
  onChange,
  onSubmit,
  onClose,
}: {
  draft: HoldingInput;
  isNew: boolean;
  canWrite: boolean;
  saving: boolean;
  error: Error | null;
  onChange: (values: Partial<HoldingInput>) => void;
  onSubmit: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet open onOpenChange={open => !open && onClose()}>
      <SheetContent side='right' className='w-[min(480px,100vw)] overflow-y-auto'>
        <form
          className='flex flex-col gap-3 p-5'
          onSubmit={event => {
            event.preventDefault();
            onSubmit();
          }}>
          <SheetTitle className='pr-8 text-title font-semibold'>{isNew ? '종목 추가' : '종목 수정'}</SheetTitle>
          <fieldset className='grid grid-cols-1 gap-3 sm:grid-cols-2' disabled={saving || !canWrite}>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-ticker'>종목 코드 *</Label>
              <Input id='h-ticker' required value={draft.ticker} placeholder='NASDAQ:AAPL' onChange={e => onChange({ ticker: e.target.value })} />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-label'>이름</Label>
              <Input id='h-label' value={draft.label} placeholder='Apple' onChange={e => onChange({ label: e.target.value })} />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-qty'>보유 수량 *</Label>
              <Input
                id='h-qty'
                required
                inputMode='numeric'
                pattern='[0-9]+'
                title='보유 수량은 0 이상의 정수로 입력하세요.'
                value={draft.quantity}
                onChange={e => onChange({ quantity: e.target.value })}
              />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-cost'>평균 매수가</Label>
              <Input id='h-cost' inputMode='decimal' pattern='[0-9]+(\.[0-9]+)?' value={draft.avg_cost ?? ''} onChange={e => onChange({ avg_cost: e.target.value || null })} />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-cur'>통화 *</Label>
              <Input id='h-cur' required pattern='[A-Z]{3}' value={draft.currency} placeholder='USD' onChange={e => onChange({ currency: e.target.value.toUpperCase() })} />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='h-class'>자산 종류</Label>
              <NativeSelect id='h-class' value={draft.asset_class} onChange={e => onChange({ asset_class: e.target.value as HoldingInput['asset_class'] })}>
                <option value='equity'>주식</option>
                <option value='etf'>ETF</option>
                <option value='crypto'>가상자산</option>
                <option value='bond'>채권</option>
                <option value='other'>기타</option>
              </NativeSelect>
            </div>
            <div className='flex flex-col gap-1 sm:col-span-2'>
              <Label htmlFor='h-mode'>가격</Label>
              <NativeSelect id='h-mode' value={draft.quote_mode} onChange={e => onChange({ quote_mode: e.target.value as 'auto' | 'manual' })}>
                <option value='auto'>자동 시세</option>
                <option value='manual'>직접 입력 (자동 시세 미지원 종목)</option>
              </NativeSelect>
              <p className='text-xs text-faint'>
                {draft.quote_mode === 'auto' ? '거래소를 포함한 코드로 조회합니다. 외화는 기록된 환율로 원화 평가합니다.' : '가격과 그 기준일을 함께 입력하세요.'}
              </p>
            </div>
            {draft.quote_mode === 'manual' && (
              <>
                <div className='flex flex-col gap-1'>
                  <Label htmlFor='h-price'>가격 *</Label>
                  <Input
                    id='h-price'
                    required
                    inputMode='decimal'
                    pattern='[0-9]+(\.[0-9]+)?'
                    value={draft.manual_price ?? ''}
                    onChange={e => onChange({ manual_price: e.target.value || null })}
                  />
                </div>
                <div className='flex flex-col gap-1'>
                  <Label htmlFor='h-asof'>가격 기준일 *</Label>
                  <Input id='h-asof' required type='date' value={draft.price_as_of ?? ''} onChange={e => onChange({ price_as_of: e.target.value || null })} />
                </div>
              </>
            )}
          </fieldset>
          {error && <Alert variant='destructive'>{error.message}</Alert>}
          <div className='mt-2 flex justify-end gap-2'>
            <Button type='button' disabled={saving} onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={saving || !canWrite}>
              {isNew ? '추가' : '저장'}
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function QuoteConnectionLine() {
  const status = useMarketStatus();
  const data = status.data;
  const text = !data
    ? null
    : !data.configured
      ? '자동 시세가 연결되지 않았습니다. 직접 입력한 가격으로만 평가합니다.'
      : !data.account_matches
        ? '시세 파일과 Google 계정이 달라 자동 시세를 갱신하지 않습니다.'
        : `자동 시세 연결됨 · 최근 갱신 ${relative(data.last_success_at, '없음')}`;
  if (!text) return null;
  return (
    <p className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
      {text}
      <Link href='/settings/market' className='text-primary hover:underline'>
        시세 연결 설정
      </Link>
    </p>
  );
}

function Holdings() {
  const client = useQueryClient();
  const holdings = useQuery({ queryKey: ['finance', 'holdings'], queryFn: holdingsApi.list });
  const [draft, setDraft] = useState<{ value: HoldingInput; isNew: boolean } | null>(null);
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
  const save = useMutation({
    mutationFn: holdingsApi.save,
    onSuccess: data => {
      setDraft(null);
      notify.success(data.quote_status === 'ready' ? '저장했습니다' : '저장했습니다. 시세를 받아오는 중입니다');
      void invalidate();
      refresh.mutate();
    },
  });
  // Every edit is a new intent; a retry of the same unchanged submission keeps its request ID.
  const update = (values: Partial<HoldingInput>) =>
    setDraft(current => (current ? { ...current, value: { ...current.value, ...values, request_id: crypto.randomUUID() } } : current));
  const open = (row: SheetHolding | null) => {
    save.reset();
    setDraft(row ? { value: holdingDraft(row, crypto.randomUUID()), isNew: false } : { value: blank(), isNew: true });
  };
  const canWrite = !!holdings.data?.can_write;
  const busy = save.isPending || refresh.isPending;
  const portfolio = holdings.data?.portfolio;
  const rows = holdings.data?.rows ?? [];
  const lineOf = (row: SheetHolding) => portfolio?.lines.find(item => item.kind === 'holding' && item.id === row.position_id);
  const flags = portfolio && (portfolio.stale || !portfolio.complete) ? issueFlags(portfolio.issues) : [];

  return (
    <Section
      title={
        <span className='flex items-center gap-2'>
          보유 종목 {flags.length > 0 && <QualityBadge flags={flags} label={portfolio?.complete ? '확인 필요' : '일부 제외'} />}
        </span>
      }
      count={holdings.data?.rows.length}
      info={
        <>
          <p>종목·수량·원가는 이 컴퓨터에만 저장합니다. Google에는 시세 조회용 종목 코드만 보냅니다.</p>
          <p>자동 시세는 최대 20분 늦을 수 있고, 이 화면이 열려 있는 동안 5분마다 다시 조회합니다.</p>
          <p>가격이나 환율이 없는 종목은 0으로 계산하지 않고 합계에서 뺍니다.</p>
        </>
      }
      actions={
        <>
          <Button size='sm' variant='ghost' disabled={!initialized || busy} onClick={() => refresh.mutate()}>
            <RefreshCw className={refreshing ? 'animate-spin' : undefined} /> 시세 조회
          </Button>
          <Button size='sm' disabled={!canWrite || !initialized || busy} onClick={() => open(null)}>
            <Plus /> 종목 추가
          </Button>
        </>
      }>
      <div className='mb-2'>
        <QuoteConnectionLine />
      </div>
      <QueryStatus pending={holdings.isPending} error={holdings.error} retry={holdings.refetch} label='보유 종목' rows={3} />
      {refresh.error && <Alert variant='destructive' className='mb-2'>시세를 조회하지 못했습니다. {refresh.error.message}</Alert>}
      {holdings.data?.warning && (
        <Alert variant='warning' className='mb-2'>
          {holdings.data.warning}
        </Alert>
      )}
      {holdings.data && !rows.length && (
        <EmptyState
          action={
            <Button size='sm' variant='primary' disabled={!canWrite || !initialized} onClick={() => open(null)}>
              <Plus /> 종목 추가
            </Button>
          }>
          아직 기록한 보유 종목이 없습니다.
        </EmptyState>
      )}
      {rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>종목</TableHead>
              <TableHead className='text-right'>수량</TableHead>
              <TableHead className='hidden text-right md:table-cell'>평균 매수가</TableHead>
              <TableHead className='text-right'>시세</TableHead>
              <TableHead className='text-right'>원화 평가액</TableHead>
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(row => {
              const line = lineOf(row);
              return (
                <TableRow key={row.position_id} className={canWrite ? 'cursor-pointer' : undefined} onClick={() => canWrite && !busy && open(row)}>
                  <TableCell>
                    <button type='button' className='text-left font-medium hover:underline disabled:no-underline' disabled={!canWrite || busy} onClick={() => open(row)}>
                      {row.label || row.ticker}
                    </button>
                    <span className='block text-xs text-faint'>
                      {row.ticker} · {row.currency}
                    </span>
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>{row.quantity == null ? '확인 필요' : quantityText(row.quantity)}</TableCell>
                  <TableCell className='hidden text-right tabular-nums md:table-cell'>{money(row.avg_cost, row.currency)}</TableCell>
                  <TableCell className='text-right tabular-nums'>
                    {money(line?.price, row.currency)}
                    {line?.price_as_of && <span className='block text-xs text-faint'>{dateOnly(line.price_as_of)}</span>}
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>{money(line?.value_krw)}</TableCell>
                  <TableCell onClick={e => e.stopPropagation()}>
                    <HoldingStatus row={row} line={line} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {draft && (
        <HoldingSheet
          draft={draft.value}
          isNew={draft.isNew}
          canWrite={canWrite}
          saving={save.isPending}
          error={save.error}
          onChange={update}
          onSubmit={() => {
            const ticker = draft.value.ticker.trim().toUpperCase();
            save.mutate({ ...draft.value, ticker, label: draft.value.label.trim() || ticker });
          }}
          onClose={() => !save.isPending && setDraft(null)}
        />
      )}
    </Section>
  );
}

export function InvestmentsView() {
  return (
    <>
      <Holdings />
      <ResourceTable
        resource='fx-rates'
        title='환율'
        addLabel='환율 추가'
        emptyText='외화 자산이 있다면 원화 환율을 기록하세요. 환율이 없는 외화 항목은 원화 합계에서 빠집니다.'
        info='외화 계좌와 종목은 여기 기록된 원화 환율로 평가합니다. 기준일이 오래된 환율은 확인 필요로 표시됩니다.'
      />
    </>
  );
}
