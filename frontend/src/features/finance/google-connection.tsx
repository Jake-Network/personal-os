'use client';

import { useSyncExternalStore } from 'react';

import { useSearchParams } from 'next/navigation';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { financeApi, type GoogleConnection } from './api';
import { googleEnvironmentTemplate, googleOriginMismatch } from './google-setup';

// An origin cannot change within this document; a navigation creates a new document.
const subscribeToOrigin = () => () => undefined;
const browserOrigin = () => window.location.origin;
const serverOrigin = () => '';

const link = (href: string, text: string) => (
  <a href={href} target='_blank' rel='noreferrer' className='text-primary underline'>
    {text}
  </a>
);

/** Server-side OAuth client setup. Shown only when the server is not configured, inside 고급. */
function GoogleSetupGuide({ data }: { data: GoogleConnection }) {
  const setup = data.setup;
  return (
    <details className='rounded-lg border p-4 text-ui' open={!data.configured}>
      <summary className='cursor-pointer font-medium'>고급 · 서버에 Google 로그인 설정하기</summary>
      <div className='mt-3 flex flex-col gap-3 text-muted-foreground'>
        <p>Google 로그인을 쓰려면 서버에 Google OAuth 클라이언트가 설정되어 있어야 합니다. 개인 Google 계정으로 발급할 수 있습니다.</p>
        {setup && setup.missing_fields.length > 0 && (
          <p>
            서버에 없는 설정: <code className='break-all text-foreground'>{setup.missing_fields.join(', ')}</code>
          </p>
        )}
        <ol className='list-decimal space-y-2 pl-5'>
          <li>{link('https://console.cloud.google.com/apis/library/sheets.googleapis.com', 'Google Cloud Console')}에서 프로젝트를 고르고 Google Sheets API를 켭니다.</li>
          <li>
            {link('https://console.cloud.google.com/auth/branding', 'Google Auth Platform')}에서 앱 이름과 지원 이메일을 정하고 대상을 외부로 둡니다. 테스트 모드라면{' '}
            {link('https://console.cloud.google.com/auth/audience', '테스트 사용자')}에 본인 이메일을 추가합니다.
          </li>
          <li>
            {link('https://console.cloud.google.com/auth/clients', '클라이언트')}에서 웹 애플리케이션 유형의 OAuth 클라이언트를 만들고, 승인된 리디렉션 URI에 아래 주소를 그대로 등록합니다.
            {setup && (
              <input
                aria-label='Google 승인된 리디렉션 URI'
                readOnly
                value={setup.redirect_uri}
                onFocus={event => event.target.select()}
                className='mt-2 w-full rounded-md border bg-muted p-2 font-mono text-xs text-foreground'
              />
            )}
          </li>
          <li>발급한 클라이언트 ID와 보안 비밀번호를 서버 환경 설정에 넣고 서버를 다시 시작합니다. 보안 비밀번호는 브라우저에 입력하거나 공유하지 마세요.</li>
        </ol>
        {setup && (
          <div>
            <label htmlFor='google-oauth-env' className='mb-1 block'>
              서버 환경 설정 예시 (값은 서버에서 채움)
            </label>
            <textarea
              id='google-oauth-env'
              readOnly
              rows={4}
              value={googleEnvironmentTemplate(setup)}
              onFocus={event => event.target.select()}
              className='w-full rounded-md border bg-muted p-2 font-mono text-xs text-foreground'
            />
          </div>
        )}
      </div>
    </details>
  );
}

function statusText(data: GoogleConnection | undefined, pending: boolean): string {
  if (pending) return 'Google 연결 상태를 확인하는 중…';
  if (data?.connected) return `Google 계정 연결됨${data.email ? ` · ${data.email}` : ''}`;
  if (data?.status === 'needs_reauth') return 'Google 인증이 만료되었거나 취소되었습니다. 다시 연결하세요.';
  if (data?.status === 'disconnected') return 'Google 연결을 해제했습니다.';
  if (data && !data.configured) return '서버에 Google 로그인이 설정되지 않았습니다.';
  return 'Google 계정이 연결되지 않았습니다.';
}

/** Google account connection for quotes only; independent of the app lock and the AI connection. */
export function GoogleConnectionControls() {
  const client = useQueryClient();
  const params = useSearchParams();
  const connection = useQuery({ queryKey: ['finance', 'google'], queryFn: financeApi.googleStatus });
  const login = useMutation({
    mutationFn: () => financeApi.googleLogin(),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  const disconnect = useMutation({
    mutationFn: financeApi.googleDisconnect,
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: ['finance'] }), client.invalidateQueries({ queryKey: ['market-data'] })]),
  });
  const data = connection.data;
  const setup = data?.setup;
  const origin = useSyncExternalStore(subscribeToOrigin, browserOrigin, serverOrigin);
  const originMismatch = googleOriginMismatch(origin, setup);
  const error = connection.error ?? login.error ?? disconnect.error;
  const busy = connection.isPending || login.isPending || disconnect.isPending;
  const invalidCallback = !!setup && (!setup.redirect_uri_supported || !setup.callback_host_matches_frontend);
  const linked = data?.connected || data?.status === 'needs_reauth';

  return (
    <div className='flex flex-col gap-3'>
      <p className='text-ui'>{statusText(data, connection.isPending)}</p>
      <div className='flex flex-wrap gap-2'>
        {data?.configured && originMismatch && setup && !busy && !invalidCallback ? (
          <Button asChild>
            <a href={setup.login_url}>Google 로그인 주소로 이동</a>
          </Button>
        ) : (
          <Button type='button' variant={linked ? 'default' : 'primary'} disabled={busy || !data?.configured || originMismatch || invalidCallback} onClick={() => login.mutate()}>
            {linked ? 'Google 다시 연결' : 'Google 계정 연결'}
          </Button>
        )}
        {linked && (
          <Button type='button' variant='ghost' disabled={busy} onClick={() => disconnect.mutate()}>
            연결 해제
          </Button>
        )}
      </div>
      {originMismatch && setup && (
        <Alert variant='warning'>
          지금 주소가 서버에 설정된 접속 주소와 달라 여기서는 연결할 수 없습니다. {setup.login_url}에서 연결하세요.
        </Alert>
      )}
      {invalidCallback && (
        <Alert variant='warning'>
          서버의 Google 콜백 주소를 고쳐야 합니다. 이 컴퓨터에서는 127.0.0.1 또는 localhost를, 다른 기기에서는 HTTPS 도메인을 쓰고, 화면 주소와 같은 호스트로 맞추세요.
        </Alert>
      )}
      {params.get('google_oauth') === 'error' && <Alert variant='destructive'>Google 연결을 완료하지 못했습니다. 다시 시도하거나 서버 설정을 확인하세요.</Alert>}
      {error && <Alert variant='destructive'>{error.message}</Alert>}
      {data?.requires_scope_reset && (
        <Alert variant='warning'>예전에 승인한 넓은 Google 권한을 Google 계정 설정에서 해제한 뒤 다시 연결하세요. 그 전에는 시세 파일에 쓰지 않습니다.</Alert>
      )}
      {data?.last_error_code && <Alert variant='warning'>Google 연결에 문제가 있습니다. 계정을 다시 연결하고 파일 접근 권한을 확인하세요.</Alert>}
      {data && (!data.configured || invalidCallback) && <GoogleSetupGuide data={data} />}
    </div>
  );
}
