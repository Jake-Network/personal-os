'use client';

import { Suspense, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { financeApi, type GoogleConnection, type Portfolio } from './api';
import { googleEnvironmentTemplate, googleOriginMismatch } from './google-setup';
import { allocationPercent, money, timestamp } from './presentation';

// An origin cannot change within this document; a navigation creates a new document.
const subscribeToOrigin = () => () => undefined;
const browserOrigin = () => window.location.origin;
const serverOrigin = () => '';

function GoogleSetupGuidance({ data, originMismatch }: { data: GoogleConnection; originMismatch: boolean }) {
  const setup = data.setup;
  return (
    <div className='space-y-3'>
      {originMismatch && setup && (
        <Alert variant='warning'>
          <p>
            현재 접속 주소가 서버의 Google 로그인 주소와 다릅니다. 연결은{' '}
            <a className='underline' href={setup.login_url}>
              {setup.login_url}
            </a>
            에서 진행하세요. 127.0.0.1은 브라우저를 실행한 컴퓨터를 가리킵니다. 다른 기기에서는 HTTPS 도메인을 서버 주소로 설정해야 합니다.
          </p>
        </Alert>
      )}
      {setup && (!setup.redirect_uri_supported || !setup.callback_host_matches_frontend) && (
        <Alert variant='warning'>
          Google 콜백 주소 설정을 수정해야 합니다. HTTP 사설 IP 주소는 Google 콜백으로 사용할 수 없습니다. 로컬에서는 127.0.0.1 또는 localhost를
          사용하고, 외부 접속에는 HTTPS 도메인을 사용하세요. 프론트엔드와 콜백의 호스트도 같아야 합니다.
        </Alert>
      )}
      {!data.configured && (
        <div className='space-y-3 rounded-lg border p-4 text-sm'>
          <p className='font-medium'>Google 계정 연결을 위한 초기 설정이 필요합니다</p>
          <p>Google Cloud에서 앱의 OAuth 클라이언트를 먼저 발급해야 로그인할 수 있습니다. 개인 Google 계정으로 발급할 수 있습니다.</p>
          {setup && setup.missing_fields.length > 0 && (
            <p>
              서버에 없는 설정: <code className='break-all'>{setup.missing_fields.join(', ')}</code>
            </p>
          )}
          <ol className='list-decimal space-y-2 pl-5'>
            <li>
              <a href='https://console.cloud.google.com/apis/library/sheets.googleapis.com' target='_blank' rel='noreferrer' className='underline'>
                Google Cloud Console
              </a>
              에서 프로젝트를 선택하거나 만들고 Google Sheets API를 사용 설정하세요.
            </li>
            <li>
              <a href='https://console.cloud.google.com/auth/branding' target='_blank' rel='noreferrer' className='underline'>
                Google Auth Platform
              </a>
              에서 앱 이름과 지원 이메일을 설정하세요. 대상은 외부(External)로 설정하고, 테스트 모드라면{' '}
              <a href='https://console.cloud.google.com/auth/audience' target='_blank' rel='noreferrer' className='underline'>
                테스트 사용자
              </a>
              에 본인 Google 이메일을 추가하세요.
            </li>
            <li>
              <a href='https://console.cloud.google.com/auth/clients' target='_blank' rel='noreferrer' className='underline'>
                클라이언트
              </a>
              에서 OAuth 클라이언트를 만들고 유형을 웹 애플리케이션으로 선택하세요. 승인된 리디렉션 URI에 아래 주소를 정확히 등록하세요.
              {setup ? (
                <input
                  aria-label='Google 승인된 리디렉션 URI'
                  readOnly
                  value={setup.redirect_uri}
                  onFocus={event => event.target.select()}
                  className='mt-2 w-full rounded border bg-muted p-2 font-mono text-xs'
                />
              ) : (
                <p className='mt-1'>서버의 GOOGLE_OAUTH_REDIRECT_URI 값을 확인하세요. 서버 업데이트 후 여기에서도 주소를 확인할 수 있습니다.</p>
              )}
            </li>
            <li>
              발급한 클라이언트 ID와 보안 비밀번호를 서버에 설정하세요. Docker Compose는 docker/.env를 사용하고, 직접 실행할 때는 서버를 시작하는
              셸에서 환경 변수를 export하세요. 보안 비밀번호는 브라우저에 입력하거나 공유하지 마세요.
            </li>
            <li>환경 설정을 적용해 서버를 다시 시작하고 이 페이지를 새로고침한 뒤 Google 계정으로 연결하세요.</li>
          </ol>
          {setup && (
            <div>
              <label htmlFor='google-oauth-env' className='mb-1 block'>
                서버 환경 설정 템플릿 (클라이언트 값은 서버에서 입력)
              </label>
              <textarea
                id='google-oauth-env'
                readOnly
                rows={4}
                value={googleEnvironmentTemplate(setup)}
                onFocus={event => event.target.select()}
                className='w-full rounded border bg-muted p-2 font-mono text-xs'
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GoogleConnectionControls() {
  const client = useQueryClient();
  const params = useSearchParams();
  const connection = useQuery({ queryKey: ['finance', 'google'], queryFn: financeApi.googleStatus });
  const login = useMutation({
    mutationFn: () => financeApi.googleLogin(),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  const disconnect = useMutation({
    mutationFn: financeApi.googleDisconnect,
    onSettled: () => client.invalidateQueries({ queryKey: ['finance'] }),
  });
  const data = connection.data;
  const origin = useSyncExternalStore(subscribeToOrigin, browserOrigin, serverOrigin);
  const originMismatch = googleOriginMismatch(origin, data?.setup);
  const error = connection.error ?? login.error ?? disconnect.error;
  const busy = connection.isPending || login.isPending || disconnect.isPending;
  const invalidCallback = !!data?.setup && (!data.setup.redirect_uri_supported || !data.setup.callback_host_matches_frontend);
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
      {data && <GoogleSetupGuidance data={data} originMismatch={originMismatch} />}
      <div className='flex flex-wrap gap-2'>
        {data?.configured && originMismatch && data.setup && !busy && !invalidCallback ? (
          <Button asChild>
            <a href={data.setup.login_url}>Google 로그인 주소로 이동</a>
          </Button>
        ) : (
          <Button type='button' disabled={busy || !data?.configured || originMismatch || invalidCallback} onClick={() => login.mutate()}>
            {data?.connected || data?.status === 'needs_reauth' ? 'Google 다시 연결' : 'Google 계정으로 연결'}
          </Button>
        )}
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
        description='Google Sheets의 입력값을 기준으로 평가합니다. 보유 종목 화면에서도 시트에 종목과 수량을 저장할 수 있습니다.'
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
          <Link href='/data/holdings' className='text-sm underline'>
            보유 종목 입력 · 자동 시세 보기
          </Link>
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
