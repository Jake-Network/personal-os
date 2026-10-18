'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { financeApi, type Snapshot } from './api';
import { HistoryChart } from './history-chart';
import { Holdings, Totals } from './portfolio-view';
import { money, timestamp } from './presentation';
import { SnapshotCorrection } from './snapshot-correction';

export function HistoryView() {
  const client = useQueryClient();
  const [period, setPeriod] = useState('6m');
  const [month, setMonth] = useState('');
  const [closing, setClosing] = useState(false);
  const [selected, setSelected] = useState<Snapshot | null>(null);
  const history = useQuery({ queryKey: ['finance', 'history', period], queryFn: () => financeApi.history(period) });
  const audit = useQuery({ queryKey: ['finance', 'audit', selected?.id], queryFn: () => financeApi.audit(selected!.id), enabled: !!selected });
  const create = useMutation({ mutationFn: financeApi.create, onSuccess: () => client.invalidateQueries({ queryKey: ['finance'] }) });
  const snapshots = [...(history.data?.snapshots ?? [])].sort((a, b) => a.month.localeCompare(b.month));
  return (
    <PageContainer className='space-y-4'>
      <PageHeader
        title='월별 순자산 기록'
        description='월말 보유 수량과 유효한 종가·환율을 보존합니다. 오늘의 보유 수량으로 과거를 추정하지 않습니다.'
        actions={
          <Button asChild>
            <Link href='/finance'>포트폴리오</Link>
          </Button>
        }
      />
      {(history.error || create.error) && <Alert variant='destructive'>{(history.error ?? create.error)?.message}</Alert>}
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex gap-2' aria-label='조회 기간'>
          {[
            ['6m', '6M'],
            ['1y', '1Y'],
            ['all', 'All'],
          ].map(([value, label]) => (
            <Button key={value} aria-pressed={period === value} variant={period === value ? 'primary' : 'default'} onClick={() => setPeriod(value)}>
              {label}
            </Button>
          ))}
        </div>
        <form
          className='flex items-end gap-2'
          onSubmit={event => {
            event.preventDefault();
            if (month) setClosing(true);
          }}>
          <label className='text-xs'>
            월말 기록 생성
            <Input type='month' value={month} onChange={event => setMonth(event.target.value)} required />
          </label>
          <Button disabled={!month || create.isPending} type='submit'>
            기록 생성
          </Button>
        </form>
      </div>
      {closing && month && (
        <Card>
          <CardContent>
            <h2 className='mb-3 font-semibold'>{month} 월말 근거 입력</h2>
            <SnapshotCorrection
              snapshot={{ rows: [], coverage: [] } as unknown as Snapshot}
              createMonth={month}
              onSaved={snapshot => {
                setClosing(false);
                setSelected(snapshot);
              }}
            />
            <Button className='mt-2' onClick={() => setClosing(false)}>
              취소
            </Button>
          </CardContent>
        </Card>
      )}
      <p className='text-xs text-muted-foreground'>
        당시 수량·잔액·종가·환율과 포함 범위가 충족된 월만 확정합니다. 기존 기록의 정정은 새 revision으로 보존합니다.
      </p>
      {history.data?.missing_months.length ? (
        <Alert variant='warning'>월말 기록 없음: {history.data.missing_months.map(value => value.slice(0, 7)).join(', ')}</Alert>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>순자산 · 총자산 · 부채 추이</CardTitle>
        </CardHeader>
        <CardContent>
          <HistoryChart
            months={snapshots.map(snapshot => ({
              month: snapshot.month,
              complete: snapshot.complete,
              net_worth_krw: snapshot.net_worth,
              total_assets_krw: snapshot.total_assets,
              total_liabilities_krw: snapshot.total_liabilities,
            }))}
          />
        </CardContent>
      </Card>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              {['월', '순자산', '총자산', '부채', '전월 대비 KRW / %', '현금 / 투자', '완전성', '검토'].map(label => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {snapshots.map(snapshot => {
              const comparable = snapshot.complete && snapshot.change_krw != null;
              return (
                <TableRow key={snapshot.id}>
                  <TableCell>
                    {snapshot.month.slice(0, 7)}
                    <small className='block text-faint'>수정 {snapshot.revision}</small>
                  </TableCell>
                  <TableCell>{money(snapshot.net_worth)}</TableCell>
                  <TableCell>{money(snapshot.total_assets)}</TableCell>
                  <TableCell>{money(snapshot.total_liabilities)}</TableCell>
                  <TableCell>
                    {comparable ? (
                      <>
                        {money(snapshot.change_krw)}
                        <small className='block'>{snapshot.change_pct == null ? '비율 계산 불가' : `${snapshot.change_pct}%`}</small>
                      </>
                    ) : (
                      '비교 불가'
                    )}
                  </TableCell>
                  <TableCell>
                    {money(snapshot.cash)}
                    <small className='block'>{money(snapshot.investments)}</small>
                  </TableCell>
                  <TableCell>
                    {snapshot.complete ? '완전' : '불완전'}
                    <small className='block text-warning'>{snapshot.issues.join(' · ')}</small>
                  </TableCell>
                  <TableCell>
                    <Button size='sm' onClick={() => setSelected(snapshot)}>
                      명세 · 감사 이력
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {!snapshots.length && (
          <p className='p-5 text-muted-foreground'>{history.isPending ? '불러오는 중…' : '선택한 기간에 월말 기록이 없습니다.'}</p>
        )}
      </Card>
      {selected && (
        <Card>
          <CardHeader>
            <CardTitle>{selected.month.slice(0, 7)} 월말 검토</CardTitle>
            <Button onClick={() => setSelected(null)}>닫기</Button>
          </CardHeader>
          <CardContent className='space-y-4'>
            <Totals data={selected} />
            <Holdings data={selected} />
            <p>
              기록 사유: {selected.reason} · {timestamp(selected.created_at)}
            </p>
            <SnapshotCorrection key={selected.id} snapshot={selected} onSaved={setSelected} />
            <h3 className='font-semibold'>감사 이력 (원본 보존)</h3>
            {audit.error && <Alert variant='destructive'>{audit.error.message}</Alert>}
            {audit.isPending && <p>감사 이력 불러오는 중…</p>}
            {audit.data?.map(revision => (
              <p key={revision.id}>
                수정 {revision.revision} · {timestamp(revision.created_at)} · {revision.reason} · {money(revision.net_worth)} ·{' '}
                {revision.complete ? '완전' : '불완전'}
              </p>
            ))}
          </CardContent>
        </Card>
      )}
    </PageContainer>
  );
}
