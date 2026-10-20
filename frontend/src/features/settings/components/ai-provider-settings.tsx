'use client';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';

import { useEffect, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';

import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { useConfirm } from '@/components/confirm-dialog';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { ListSkeleton } from '@/components/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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

import { CALLBACK_ERROR, OUTCOME, PROVIDER_LABEL, PROVIDERS } from '../consts';
import { TransferPolicySettings } from './transfer-policy-settings';

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
  const confirmDialog = useConfirm();
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
      queryClient.invalidateQueries({ queryKey: getSummaryQueryKey() }),
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

  const askDisconnect = async () => {
    const ok = await confirmDialog({
      title: 'ChatGPT 연결을 해제할까요?',
      description: '저장된 로그인 정보를 지우고 철회합니다. 다시 연결하기 전까지 상담을 할 수 없습니다.',
      confirmLabel: '연결 해제',
      destructive: true,
    });
    if (ok) disconnect.mutate();
  };
  const chooseProvider = async (provider: string) => {
    if (provider === 'openai_api_key') {
      const ok = await confirmDialog({
        title: 'OpenAI API 키로 바꿀까요?',
        description: '이후 상담은 OpenAI API 계정에 요금이 청구됩니다. 자동으로 다시 바뀌지 않습니다.',
        confirmLabel: '바꾸기',
      });
      if (!ok) return;
    }
    select.mutate({ data: { provider, model: null } });
  };

  return (
    <div className='max-w-[860px]'>
      {notice && (
        <Alert variant={notice.tone} className='mb-4'>
          {notice.text}
        </Alert>
      )}
      {status.error && (
        <Alert variant='destructive' className='mb-4'>
          {status.error.message}
        </Alert>
      )}

      <Section
        title='ChatGPT 계정'
        info={<p>ChatGPT 로그인은 모델을 쓰기 위한 인증입니다. ChatGPT의 대화나 메모리는 읽지 않으며, 로그인 정보는 서버에만 암호화해 저장합니다.</p>}
        actions={
          s &&
          (s.connected ? (
            usable ? (
              <Badge variant='success'>연결됨</Badge>
            ) : (
              <Badge variant='warning'>구독 사용 권한 없음</Badge>
            )
          ) : s.status === 'needs_reauth' ? (
            <Badge variant='destructive'>다시 로그인 필요</Badge>
          ) : (
            <Badge>연결 안 됨</Badge>
          ))
        }>
        {!s ? (
          <ListSkeleton rows={2} />
        ) : s.connected || s.status === 'needs_reauth' ? (
          <div className='flex flex-col gap-3 py-2'>
            <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
              <Info label='계정' value={s.display_name ? `${s.display_name}${s.email ? ` (${s.email})` : ''}` : (s.email ?? '—')} />
              <Info label='로그인 유지' value={s.access_expires_at ? `${dateTime(s.access_expires_at)}까지 · 자동 갱신` : '—'} />
            </div>
            {s.status === 'needs_reauth' && <Alert variant='destructive'>로그인이 만료되었거나 철회되었습니다. 다시 로그인하세요.</Alert>}
            {s.connected && !s.plan_usage_enabled && (
              <Alert variant='warning'>구독 사용 권한이 없어 상담할 수 없습니다. 권한을 포함해 다시 연결하세요. 유료 API로 자동 전환하지 않습니다.</Alert>
            )}
            <div className='flex flex-wrap items-center gap-2'>
              <Button disabled={busy} onClick={() => startLogin(!s.plan_usage_enabled)}>
                {s.plan_usage_enabled ? '다시 로그인' : '권한 포함해 다시 연결'}
              </Button>
              <Button asChild>
                <a href={s.usage_url} target='_blank' rel='noreferrer'>
                  사용량 확인 <ExternalLink />
                </a>
              </Button>
              <Button variant='destructive' className='ml-auto' disabled={disconnect.isPending} onClick={() => void askDisconnect()}>
                연결 해제
              </Button>
            </div>
            <details className='text-ui'>
              <summary className='cursor-pointer text-muted-foreground'>고급</summary>
              <div className='mt-2 grid grid-cols-1 gap-3 md:grid-cols-2'>
                <Info label='승인된 권한' value={s.scopes?.join(' ') || '—'} mono />
                <Info label='최근 오류 코드' value={s.last_error_code ?? '없음'} mono />
              </div>
            </details>
          </div>
        ) : (
          <div className='flex flex-col items-start gap-3 py-2'>
            <p className='text-muted-foreground'>ChatGPT Plus·Pro 구독 사용량으로 상담합니다.</p>
            <Button variant='primary' disabled={busy} onClick={() => startLogin()}>
              ChatGPT로 로그인
            </Button>
          </div>
        )}
      </Section>

      <TransferPolicySettings provider={s?.provider} />

      <Section title='AI 제공자와 모델'>
        <div className='flex flex-col gap-4 py-2'>
          <RadioGroup value={s?.provider ?? ''} onValueChange={p => void chooseProvider(p)} aria-label='AI 제공자'>
            {PROVIDERS.map(p => (
              <label key={p.key} className='flex cursor-pointer items-start gap-2'>
                <RadioGroupItem value={p.key} disabled={p.key === 'codex_app_server'} className='mt-0.5' />
                <span>
                  <span className='font-medium'>{p.label}</span>
                  <span className='block text-xs text-muted-foreground'>{p.note}</span>
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
            {!models.data && !models.error && <span className='text-xs text-faint'>계정을 연결하면 쓸 수 있는 모델이 나옵니다.</span>}
            {models.error && <span className='text-xs text-destructive'>{models.error.message}</span>}
          </div>
        </div>
      </Section>

      <Section title='최근 모델 호출' info={<p>호출 결과와 사용량만 기록합니다. 질문·답변 원문과 로그인 정보는 기록하지 않습니다.</p>}>
        <QueryStatus pending={usage.isPending} error={usage.error} retry={usage.refetch} label='호출 기록' rows={3} />
        {usage.data && usage.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>시각</TableHead>
                <TableHead>제공자</TableHead>
                <TableHead>모델</TableHead>
                <TableHead>결과</TableHead>
                <TableHead className='text-right'>입력/출력 토큰</TableHead>
                <TableHead className='text-right'>걸린 시간</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usage.data.map(u => (
                <TableRow key={u.id}>
                  <TableCell>{dateTime(u.created_at)}</TableCell>
                  <TableCell>{PROVIDER_LABEL[u.provider] ?? u.provider}</TableCell>
                  <TableCell>{u.model ?? '—'}</TableCell>
                  <TableCell>
                    <Badge
                      variant={u.outcome === 'completed' ? 'success' : u.outcome === 'quota_exceeded' ? 'warning' : 'destructive'}
                      title={u.error_code ?? undefined}>
                      {OUTCOME[u.outcome] ?? u.outcome}
                    </Badge>
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>
                    {u.input_tokens ?? '—'} / {u.output_tokens ?? '—'}
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>{u.latency_ms != null ? `${(u.latency_ms / 1000).toFixed(1)}초` : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {usage.data?.length === 0 && <EmptyState>호출 기록이 없습니다.</EmptyState>}
      </Section>
    </div>
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
