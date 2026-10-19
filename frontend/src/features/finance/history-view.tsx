'use client';

import { useState } from 'react';

import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { ListSkeleton } from '@/components/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { monthLabel } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import { financeApi, type Snapshot } from './api';
import { HistoryChart } from './history-chart';
import { PositionsTable } from './positions-table';
import { issueFlags, money, timestamp } from './presentation';
import { type CorrectionTarget, SnapshotCorrection } from './snapshot-correction';

const PERIODS = [
  ['6m', '6개월'],
  ['1y', '1년'],
  ['all', '전체'],
] as const;

function Change({ snapshot }: { snapshot: Snapshot }) {
  if (!snapshot.complete || snapshot.change_krw == null) return <span className='text-xs text-faint'>비교 불가</span>;
  const negative = snapshot.change_krw.startsWith('-');
  return (
    <span className={cn('tabular-nums', negative ? 'text-destructive' : 'text-success')}>
      {negative ? '' : '+'}
      {money(snapshot.change_krw)}
      <span className='block text-xs text-faint'>{snapshot.change_pct == null ? '비율 계산 불가' : `${snapshot.change_pct}%`}</span>
    </span>
  );
}

function SnapshotDetail({ snapshot, onClose, onSaved }: { snapshot: Snapshot; onClose: () => void; onSaved: (s: Snapshot) => void }) {
  const [correcting, setCorrecting] = useState(false);
  const audit = useQuery({ queryKey: ['finance', 'audit', snapshot.id], queryFn: () => financeApi.audit(snapshot.id) });
  return (
    <Sheet open onOpenChange={open => !open && onClose()}>
      <SheetContent side='right' className='w-[min(760px,100vw)] overflow-y-auto'>
        <div className='flex flex-col gap-4 p-5'>
          <div className='flex flex-wrap items-center gap-2 pr-8'>
            <SheetTitle className='text-title font-semibold'>{monthLabel(snapshot.month)} 월말 기록</SheetTitle>
            {snapshot.complete ? <Badge variant='success'>확정</Badge> : <QualityBadge flags={issueFlags(snapshot.issues)} label='근거 부족' />}
          </div>
          {correcting ? (
            <SnapshotCorrection
              target={{ kind: 'correct', snapshot }}
              onCancel={() => setCorrecting(false)}
              onSaved={saved => {
                setCorrecting(false);
                onSaved(saved);
              }}
            />
          ) : (
            <>
              <dl className='grid grid-cols-3 gap-3'>
                {[
                  ['순자산', snapshot.net_worth],
                  ['총자산', snapshot.total_assets],
                  ['부채', snapshot.total_liabilities],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className='text-xs text-muted-foreground'>{label}</dt>
                    <dd className='font-semibold tabular-nums'>{money(value)}</dd>
                  </div>
                ))}
              </dl>
              <PositionsTable data={snapshot} />
              <p className='text-ui text-muted-foreground'>
                {snapshot.reason} · {timestamp(snapshot.created_at)}
              </p>
              <div>
                <Button onClick={() => setCorrecting(true)}>정정하기</Button>
              </div>
              <section>
                <h3 className='mb-2 text-ui font-semibold'>변경 기록</h3>
                {audit.isPending && <ListSkeleton rows={2} />}
                {audit.error && <Alert variant='destructive'>{audit.error.message}</Alert>}
                <ol className='divide-y'>
                  {audit.data?.map((rev, i) => (
                    <li key={rev.id} className='flex flex-wrap items-baseline gap-x-3 py-2 text-ui'>
                      <span className='font-medium'>{i === 0 ? '최초 기록' : `정정 ${i}`}</span>
                      <span className='text-xs text-faint'>{timestamp(rev.created_at)}</span>
                      <span className='flex-1'>{rev.reason}</span>
                      <span className='tabular-nums'>{money(rev.net_worth)}</span>
                      {!rev.complete && <span className='text-xs text-warning'>근거 부족</span>}
                    </li>
                  ))}
                </ol>
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function CloseMonthSheet({ onClose, onSaved }: { onClose: () => void; onSaved: (s: Snapshot) => void }) {
  const [month, setMonth] = useState('');
  const [target, setTarget] = useState<CorrectionTarget | null>(null);
  return (
    <Sheet open onOpenChange={open => !open && onClose()}>
      <SheetContent side='right' className='w-[min(760px,100vw)] overflow-y-auto'>
        <div className='flex flex-col gap-4 p-5'>
          <SheetTitle className='pr-8 text-title font-semibold'>{target?.kind === 'create' ? `${monthLabel(target.month)} 월말 기록` : '월말 기록 만들기'}</SheetTitle>
          {target ? (
            <SnapshotCorrection target={target} onCancel={() => setTarget(null)} onSaved={onSaved} />
          ) : (
            <form
              className='flex items-end gap-2'
              onSubmit={e => {
                e.preventDefault();
                if (month) setTarget({ kind: 'create', month });
              }}>
              <div className='flex flex-col gap-1'>
                <Label htmlFor='close-month'>기록할 달</Label>
                <Input id='close-month' type='month' value={month} onChange={e => setMonth(e.target.value)} required />
              </div>
              <Button type='submit' variant='primary' disabled={!month}>
                다음
              </Button>
            </form>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function HistoryView() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number][0]>('6m');
  const [closing, setClosing] = useState(false);
  const [selected, setSelected] = useState<Snapshot | null>(null);
  const history = useQuery({ queryKey: ['finance', 'history', period], queryFn: () => financeApi.history(period) });
  const snapshots = [...(history.data?.snapshots ?? [])].sort((a, b) => a.month.localeCompare(b.month));
  const missing = history.data?.missing_months ?? [];

  return (
    <>
      <TabToolbar>
        <div className='inline-flex rounded-md bg-muted p-0.5' role='group' aria-label='조회 기간'>
          {PERIODS.map(([value, label]) => (
            <button
              key={value}
              type='button'
              aria-pressed={period === value}
              onClick={() => setPeriod(value)}
              className={cn('h-7 rounded-sm px-3 text-ui text-muted-foreground', period === value && 'bg-card font-medium text-foreground shadow-sm')}>
              {label}
            </button>
          ))}
        </div>
        <Button variant='primary' className='ml-auto' onClick={() => setClosing(true)}>
          <Plus /> 월말 기록 만들기
        </Button>
      </TabToolbar>

      {missing.length > 0 && (
        <Alert variant='warning' className='mb-4'>
          월말 기록이 없는 달: {missing.map(m => monthLabel(m)).join(', ')}
        </Alert>
      )}

      <Section
        title='순자산 추이'
        info={
          <>
            <p>그 달 말일의 수량·잔액과 유효한 종가·환율이 모두 있는 달만 확정합니다. 오늘의 수량이나 시세로 과거를 채우지 않습니다.</p>
            <p>월별 차이는 입출금·지출·평가 변동이 섞인 값이라, 거래 기록 없이 투자 수익이나 저축으로 단정할 수 없습니다.</p>
          </>
        }>
        <QueryStatus pending={history.isPending} error={history.error} retry={history.refetch} label='월별 기록' rows={3} />
        {history.data && (
          <HistoryChart
            months={snapshots.map(s => ({
              month: s.month,
              complete: s.complete,
              net_worth_krw: s.net_worth,
              total_assets_krw: s.total_assets,
              total_liabilities_krw: s.total_liabilities,
            }))}
          />
        )}
      </Section>

      <Section title='월별 기록' count={snapshots.length}>
        {history.data && !snapshots.length && (
          <EmptyState
            action={
              <Button size='sm' variant='primary' onClick={() => setClosing(true)}>
                <Plus /> 월말 기록 만들기
              </Button>
            }>
            선택한 기간에 월말 기록이 없습니다.
          </EmptyState>
        )}
        {snapshots.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>월</TableHead>
                <TableHead className='text-right'>순자산</TableHead>
                <TableHead className='hidden text-right md:table-cell'>총자산</TableHead>
                <TableHead className='hidden text-right md:table-cell'>부채</TableHead>
                <TableHead className='text-right'>전월 대비</TableHead>
                <TableHead>상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...snapshots].reverse().map(snapshot => (
                <TableRow key={snapshot.id} className='cursor-pointer' onClick={() => setSelected(snapshot)}>
                  <TableCell>
                    <button type='button' className='font-medium hover:underline' onClick={() => setSelected(snapshot)}>
                      {monthLabel(snapshot.month)}
                    </button>
                    {snapshot.revision > 1 && <span className='ml-1.5 text-xs text-faint'>정정됨</span>}
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>{money(snapshot.net_worth)}</TableCell>
                  <TableCell className='hidden text-right tabular-nums md:table-cell'>{money(snapshot.total_assets)}</TableCell>
                  <TableCell className='hidden text-right tabular-nums md:table-cell'>{money(snapshot.total_liabilities)}</TableCell>
                  <TableCell className='text-right'>
                    <Change snapshot={snapshot} />
                  </TableCell>
                  <TableCell onClick={e => e.stopPropagation()}>
                    {snapshot.complete ? <span className='text-xs text-faint'>확정</span> : <QualityBadge flags={issueFlags(snapshot.issues)} label='근거 부족' />}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {selected && <SnapshotDetail key={selected.id} snapshot={selected} onClose={() => setSelected(null)} onSaved={setSelected} />}
      {closing && (
        <CloseMonthSheet
          onClose={() => setClosing(false)}
          onSaved={snapshot => {
            setClosing(false);
            setSelected(snapshot);
          }}
        />
      )}
    </>
  );
}
