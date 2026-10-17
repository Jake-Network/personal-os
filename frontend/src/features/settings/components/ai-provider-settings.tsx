'use client';

import { useEffect, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';

import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { errorMessage } from '@/api-client/api-error';
import {
  getGetStatusQueryKey,
  getListModelsQueryKey,
  useDisconnect,
  useGetStatus,
  useListModels,
  useSelectProvider,
  useStartLogin,
  useUsageEvents,
} from '@/api-client/generated/ai-provider/ai-provider';
import { cn } from '@/lib/utils';
import { dateTime } from '@/lib/utils/format';

import { CALLBACK_ERROR, OUTCOME, PROVIDERS } from '../consts';

type Notice = { tone: 'success' | 'destructive' | 'warning'; text: string };

/** Result flags from the OAuth callback redirect (never tokens). */
export interface OAuthCallbackResult {
  chatgpt?: string;
  plan_usage?: string;
  code?: string;
}

function callbackNotice({ chatgpt, plan_usage, code = '' }: OAuthCallbackResult): Notice | null {
  if (!chatgpt) return null;
  if (chatgpt === 'connected') {
    return plan_usage === 'enabled'
      ? { tone: 'success', text: 'ChatGPT 계정이 연결되었습니다.' }
      : { tone: 'warning', text: 'ChatGPT 로그인은 되었지만 구독 사용 권한이 승인되지 않았습니다. 권한을 포함해 다시 연결하세요.' };
  }
  return { tone: 'destructive', text: CALLBACK_ERROR[code] ?? `연결에 실패했습니다 (${code || '알 수 없는 오류'}).` };
}

export function AIProviderSettings({ callback }: { callback: OAuthCallbackResult }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const [notice, setNotice] = useState<Notice | null>(() => callbackNotice(callback));

  // Drop the callback flags from the URL so a reload does not show the notice again.
  useEffect(() => {
    if (callback.chatgpt) router.replace(pathname);
  }, [callback.chatgpt, router, pathname]);

  const status = useGetStatus();
  const usage = useUsageEvents({ limit: 20 });
  const s = status.data;
  const usable = !!s?.connected && !!s.plan_usage_enabled;
  const models = useListModels({ query: { enabled: !!s && (s.provider !== 'chatgpt_plan' || usable) } });

  const refreshStatus = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: getGetStatusQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getListModelsQueryKey() }),
    ]);

  const login = useStartLogin({
    mutation: {
      onSuccess: ({ authorize_url }) => {
        window.location.href = authorize_url;
      },
      onError: e => setNotice({ tone: 'destructive', text: errorMessage(e) }),
    },
  });
  const disconnect = useDisconnect({ mutation: { onSuccess: refreshStatus, onError: notify.error } });
  const select = useSelectProvider({ mutation: { onSuccess: refreshStatus, onError: notify.error } });

  const startLogin = (forceConsent = false) => login.mutate({ params: forceConsent ? { force_consent: true } : undefined });
  const busy = login.isPending || login.isSuccess; // stays busy while the browser leaves for ChatGPT

  return (
    <PageContainer className='max-w-[860px]'>
      <PageHeader title='AI Provider' description='ChatGPT 로그인은 모델 사용을 위한 인증 수단입니다. ChatGPT의 대화나 메모리는 읽지 않습니다.' />

      {notice && (
        <Alert variant={notice.tone} className='mb-3.5'>
          {notice.text}
        </Alert>
      )}
      {status.error && (
        <Alert variant='destructive' className='mb-3.5'>
          {status.error.message}
        </Alert>
      )}

      <Card className='mb-3.5'>
        <CardHeader>
          <CardTitle>ChatGPT 계정</CardTitle>
          {s &&
            (s.connected ? (
              usable ? (
                <Badge variant='success'>연결됨 · 구독 사용 가능</Badge>
              ) : (
                <Badge variant='warning'>구독 사용 권한 없음</Badge>
              )
            ) : s.status === 'needs_reauth' ? (
              <Badge variant='destructive'>재인증 필요</Badge>
            ) : (
              <Badge>연결 안 됨</Badge>
            ))}
        </CardHeader>
        <CardContent className='flex flex-col gap-2.5'>
          {!s ? (
            <div className='text-xs text-faint'>불러오는 중…</div>
          ) : s.connected || s.status === 'needs_reauth' ? (
            <>
              <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2'>
                <Info label='계정' value={s.display_name ? `${s.display_name} (${s.email ?? ''})` : (s.email ?? '—')} />
                <Info label='토큰 만료' value={s.access_expires_at ? `${dateTime(s.access_expires_at)} (자동 갱신)` : '—'} />
                <Info label='승인된 권한' value={s.scopes?.join(' ') || '—'} mono />
                <Info label='최근 오류' value={s.last_error_code ?? '없음'} mono />
              </div>
              {s.status === 'needs_reauth' && <Alert variant='destructive'>인증이 만료되었거나 철회되었습니다. 다시 로그인하세요.</Alert>}
              {s.connected && !s.plan_usage_enabled && (
                <Alert variant='warning'>
                  구독 사용 권한(chatgpt.tokens.use.direct)이 없어 상담을 할 수 없습니다. 유료 API로 자동 전환하지 않습니다.
                </Alert>
              )}
              <div className='flex flex-wrap items-center gap-2'>
                <Button disabled={busy} onClick={() => startLogin(!s.plan_usage_enabled)}>
                  {s.plan_usage_enabled ? '재인증' : '권한 포함해 다시 연결'}
                </Button>
                <Button asChild>
                  <a href={s.usage_url} target='_blank' rel='noreferrer'>
                    사용량 확인 <ExternalLink />
                  </a>
                </Button>
                <span className='flex-1' />
                <Button
                  variant='destructive'
                  disabled={disconnect.isPending}
                  onClick={() => confirm('ChatGPT 연결을 해제할까요? 저장된 토큰이 삭제되고 철회됩니다.') && disconnect.mutate()}>
                  연결 해제
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className='text-muted-foreground'>
                ChatGPT Plus/Pro 구독 사용량으로 AI 상담을 이용합니다. 토큰은 서버에만 암호화해 저장되고 브라우저에는 노출되지 않습니다.
              </div>
              <div>
                <Button variant='primary' disabled={busy} onClick={() => startLogin()}>
                  Continue with ChatGPT
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className='mb-3.5'>
        <CardHeader>
          <CardTitle>Inference Provider · 모델</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-3'>
          <RadioGroup
            value={s?.provider ?? ''}
            onValueChange={provider => {
              if (provider === 'openai_api_key' && !confirm('API Key provider는 OpenAI API 계정에 과금됩니다. 전환할까요?')) return;
              select.mutate({ data: { provider, model: null } });
            }}>
            {PROVIDERS.map(p => (
              <label key={p.key} className='flex cursor-pointer items-start gap-2'>
                <RadioGroupItem value={p.key} disabled={p.key === 'codex_app_server'} className='mt-0.5' />
                <span>
                  <strong>{p.label}</strong>
                  <div className='text-xs text-faint'>{p.note}</div>
                </span>
              </label>
            ))}
          </RadioGroup>
          <div className='flex max-w-[360px] flex-col gap-1'>
            <Label htmlFor='model'>모델</Label>
            <NativeSelect
              id='model'
              value={s?.model ?? ''}
              disabled={!models.data}
              onChange={e => s && select.mutate({ data: { provider: s.provider, model: e.target.value || null } })}>
              <option value=''>자동 (계정의 첫 번째 모델)</option>
              {models.data?.map(m => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </NativeSelect>
            {!models.data && !models.error && <span className='text-xs text-faint'>계정을 연결하면 사용 가능한 모델 목록이 표시됩니다.</span>}
            {models.error && <span className='text-xs text-destructive'>{models.error.message}</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>최근 모델 호출</CardTitle>
          <span className='text-xs text-faint'>토큰 원문은 기록하지 않습니다</span>
        </CardHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>시각</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>모델</TableHead>
              <TableHead>결과</TableHead>
              <TableHead className='text-right'>입력/출력 토큰</TableHead>
              <TableHead className='text-right'>지연</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {usage.data?.map(u => (
              <TableRow key={u.id}>
                <TableCell>{dateTime(u.created_at)}</TableCell>
                <TableCell>{u.provider}</TableCell>
                <TableCell>{u.model ?? '—'}</TableCell>
                <TableCell>
                  <Badge variant={u.outcome === 'completed' ? 'success' : u.outcome === 'quota_exceeded' ? 'warning' : 'destructive'}>
                    {OUTCOME[u.outcome] ?? u.outcome}
                  </Badge>
                  {u.error_code && <span className='font-mono text-xs text-faint'> {u.error_code}</span>}
                </TableCell>
                <TableCell className='text-right tabular-nums'>
                  {u.input_tokens ?? '—'} / {u.output_tokens ?? '—'}
                </TableCell>
                <TableCell className='text-right tabular-nums'>{u.latency_ms != null ? `${(u.latency_ms / 1000).toFixed(1)}s` : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {usage.data?.length === 0 && <EmptyState>호출 기록이 없습니다.</EmptyState>}
      </Card>
    </PageContainer>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className='text-xs text-faint'>{label}</div>
      <div className={cn('break-all', mono && 'font-mono text-xs')}>{value}</div>
    </div>
  );
}
