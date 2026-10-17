'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { financeApi, type Portfolio } from './api';
import { allocationPercent, money, timestamp } from './presentation';

function GoogleConnectionControls() {
  const client = useQueryClient();
  const params = useSearchParams();
  const connection = useQuery({ queryKey: ['finance', 'google'], queryFn: financeApi.googleStatus });
  const login = useMutation({
    mutationFn: financeApi.googleLogin,
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  const disconnect = useMutation({
    mutationFn: financeApi.googleDisconnect,
    onSettled: () => client.invalidateQueries({ queryKey: ['finance'] }),
  });
  const data = connection.data;
  const error = connection.error ?? login.error ?? disconnect.error;
  const busy = connection.isPending || login.isPending || disconnect.isPending;
  return (
    <div className='space-y-2'>
      <p className='text-sm'>
        {connection.isPending
          ? 'Google 연결 상태를 확인하는 중…'
          : data?.connected
            ? `Google 계정 연결됨${data.email ? ` · ${data.email}` : ''}`
            : data?.status === 'needs_reauth'
              ? 'Google 인증이 만료되었거나 취소되었습니다. 다시 연결하세요.'
              : data?.status === 'disconnected'
                ? 'Google 연결이 해제되었습니다. 다시 연결하면 동기화할 수 있습니다.'
                : data?.credential_source === 'application_default'
                  ? 'Google 계정을 연결해 비공개 시트를 읽어오세요. 서버 인증정보 설정도 사용할 수 있습니다.'
                  : 'Google 계정을 연결해 비공개 시트를 읽어오세요.'}
      </p>
      {data && !data.configured && (
        <p className='text-xs text-muted-foreground'>Google 로그인 설정이 필요합니다. 서버의 Google OAuth 설정 안내를 확인하세요.</p>
      )}
      <div className='flex flex-wrap gap-2'>
        <Button type='button' disabled={busy || !data?.configured} onClick={() => login.mutate()}>
          {data?.connected || data?.status === 'needs_reauth' ? 'Google 다시 연결' : 'Google 계정으로 연결'}
        </Button>
        {(data?.connected || data?.status === 'needs_reauth') && (
          <Button type='button' disabled={busy} onClick={() => disconnect.mutate()}>
            Google 연결 해제
          </Button>
        )}
      </div>
      <p className='text-xs text-muted-foreground'>
        시트 읽기 및 연결 계정 확인 권한을 요청합니다. 연결한 계정이 볼 수 있는 시트의 ID를 아래에 입력하세요. Google 연결은 Personal OS 로그인이나
        ChatGPT 연결과 별개입니다.
      </p>
      {params.get('google_oauth') === 'error' && (
        <Alert variant='destructive'>Google 연결을 완료하지 못했습니다. 다시 연결하거나 서버 설정을 확인하세요.</Alert>
      )}
      {error && <Alert variant='destructive'>{error.message}</Alert>}
      {data?.last_error_code && <Alert variant='warning'>Google 연결에 문제가 있습니다. 계정을 다시 연결하고 시트 접근 권한을 확인하세요.</Alert>}
    </div>
  );
}

export function Totals({ data }: { data: Portfolio }) {
  return (
    <div className='grid gap-3 sm:grid-cols-3'>
      {[
        ['총자산', data.total_assets],
        ['부채', data.total_liabilities],
        ['순자산', data.net_worth],
      ].map(([label, value]) => (
        <Card key={label}>
          <CardContent>
            <p className='text-muted-foreground'>{label}</p>
            <p className='mt-2 text-lg tabular-nums'>{money(value)}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function Holdings({ data }: { data: Portfolio }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>자산·부채 명세 (읽기 전용)</CardTitle>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            {['항목 / 통화', '잔액 / 수량', '평균단가', '적용 가격', '기록 환율 → KRW', '평가액 KRW', '미실현 손익 KRW', '상태'].map(label => (
              <TableHead key={label}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.lines.map((line, index) => (
            <TableRow key={`${line.kind}-${line.id}-${index}`}>
              <TableCell>
                {line.label}
                <small className='block text-faint'>
                  {line.ticker ?? line.kind} · {line.currency}
                </small>
              </TableCell>
              <TableCell>{line.kind === 'holding' ? (line.quantity ?? '확인 필요') : money(line.balance, line.currency)}</TableCell>
              <TableCell>{line.kind === 'holding' ? money(line.avg_cost, line.currency) : '—'}</TableCell>
              <TableCell>
                {line.kind === 'holding' ? (
                  <>
                    {money(line.price, line.currency)}
                    <small className='block text-faint'>{timestamp(line.price_as_of)}</small>
                  </>
                ) : (
                  '—'
                )}
              </TableCell>
              <TableCell>
                {line.fx_rate ?? '확인 필요'}
                <small className='block text-faint'>{timestamp(line.fx_as_of)}</small>
              </TableCell>
              <TableCell className='tabular-nums'>{money(line.value_krw)}</TableCell>
              <TableCell className='tabular-nums'>{line.kind === 'holding' ? money(line.unrealized_gain_krw) : '—'}</TableCell>
              <TableCell>{line.issues.length ? line.issues.join(' · ') : '확인됨'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!data.lines.length && <p className='p-4 text-muted-foreground'>동기화된 항목이 없습니다.</p>}
    </Card>
  );
}

export function PortfolioView() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ['finance', 'settings'], queryFn: financeApi.settings });
  const portfolio = useQuery({ queryKey: ['finance', 'portfolio'], queryFn: financeApi.portfolio });
  const [spreadsheet, setSpreadsheet] = useState<string | null>(null);
  const action = useMutation({
    mutationFn: (operation: 'save' | 'verify' | 'sync') =>
      operation === 'save' ? financeApi.save((spreadsheet ?? settings.data?.spreadsheet_id ?? '').trim()) : financeApi[operation](),
    onSettled: () => client.invalidateQueries({ queryKey: ['finance'] }),
  });
  const error = action.error ?? settings.error ?? portfolio.error;
  const configured = !!settings.data?.spreadsheet_id;
  return (
    <PageContainer className='space-y-4'>
      <PageHeader
        title='포트폴리오'
        description='Google Sheets의 수동 입력을 기준으로 평가합니다. 금액과 수량은 시트에서 수정하세요.'
        actions={
          <Button asChild>
            <Link href='/finance/history'>월별 순자산 기록</Link>
          </Button>
        }
      />
      {error && <Alert variant='destructive'>{error.message}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>비공개 Google Sheets 연결</CardTitle>
        </CardHeader>
        <CardContent className='space-y-3'>
          <Suspense fallback={<p role='status'>Google 연결 상태를 확인하는 중…</p>}>
            <GoogleConnectionControls />
          </Suspense>
          <form
            className='flex flex-wrap items-end gap-2'
            onSubmit={event => {
              event.preventDefault();
              action.mutate('save');
            }}>
            <label className='min-w-48 flex-1'>
              스프레드시트 ID
              <Input
                value={spreadsheet ?? settings.data?.spreadsheet_id ?? ''}
                onChange={event => setSpreadsheet(event.target.value)}
                placeholder='스프레드시트 URL의 /d/ 다음 ID'
                autoComplete='off'
              />
            </label>
            <Button type='submit' disabled={action.isPending || !(spreadsheet ?? settings.data?.spreadsheet_id ?? '').trim()}>
              ID 저장
            </Button>
            <Button type='button' disabled={!configured || action.isPending} onClick={() => action.mutate('verify')}>
              현재값 조회 검증
            </Button>
            <Button type='button' variant='primary' disabled={!configured || action.isPending} onClick={() => action.mutate('sync')}>
              동기화
            </Button>
          </form>
          <p className='text-xs text-muted-foreground'>
            Google 계정 연결 없이 서버 서비스 계정을 사용하는 경우 해당 계정에 시트를 공유하세요. 지원하지 않는 종목은 시트에 수동 가격과 기준일을
            입력하세요. GOOGLEFINANCE는 지연될 수 있으며 과거 결과는 API로 가져올 수 없습니다.
          </p>
          <dl className='grid gap-2 text-xs sm:grid-cols-3'>
            <div>
              <dt>조회 검증</dt>
              <dd>{timestamp(settings.data?.verified_at)}</dd>
            </div>
            <div>
              <dt>최근 동기화 시도</dt>
              <dd>{timestamp(settings.data?.last_sync_at)}</dd>
            </div>
            <div>
              <dt>최근 성공</dt>
              <dd>{timestamp(settings.data?.last_success_at)}</dd>
            </div>
          </dl>
          {settings.data?.last_error && <Alert variant='destructive'>{settings.data.last_error}</Alert>}
        </CardContent>
      </Card>
      {portfolio.isPending && <p role='status'>평가 정보를 불러오는 중…</p>}
      {portfolio.data && (
        <>
          {(portfolio.data.stale || !portfolio.data.complete) && (
            <Alert variant='warning'>
              {portfolio.data.stale ? '가격 또는 동기화 데이터가 오래되었습니다. ' : ''}
              {!portfolio.data.complete ? '평가가 불완전합니다. 누락 값은 0으로 계산하지 않습니다. ' : ''}
              {portfolio.data.issues.join(' · ')}
            </Alert>
          )}
          <p className='text-xs text-faint'>평가 데이터 동기화: {timestamp(portfolio.data.synced_at)}</p>
          <Totals data={portfolio.data} />
          <Card>
            <CardHeader>
              <CardTitle>자산 배분 (KRW · 총자산 대비)</CardTitle>
            </CardHeader>
            <CardContent className='flex flex-wrap gap-6'>
              {[
                ['현금', portfolio.data.cash],
                ['투자', portfolio.data.investments],
                ['기타', portfolio.data.allocation.other],
              ].map(([label, value]) => (
                <span key={label}>
                  {label}: {money(value)}
                  <small className='block text-faint'>{allocationPercent(value, portfolio.data.total_assets)}</small>
                </span>
              ))}
            </CardContent>
          </Card>
          <Holdings data={portfolio.data} />
        </>
      )}
    </PageContainer>
  );
}
