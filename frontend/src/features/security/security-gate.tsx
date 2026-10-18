'use client';

import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import type { SecurityStatus as Status } from '@/api-client/model/securityStatus';
import { errorMessage } from '@/api-client/api-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { clearPrivateSession, getCsrfToken, setCsrfToken } from './session';

/** The private tree only mounts after a live server session has been checked. */
export function SecurityGate({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [status, setStatus] = useState<Status | null>(null);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const channel = useRef<BroadcastChannel | null>(null);
  const lastActivity = useRef(0);
  const active = useRef(false);
  const generation = useRef(0);

  const purge = useCallback(() => {
    generation.current += 1;
    active.current = false;
    clearPrivateSession();
    void client.cancelQueries();
    client.clear();
    toast.dismiss();
    setPassword('');
    setStatus(value => (value ? { ...value, authenticated: false, csrf_token: null } : value));
  }, [client]);
  const apply = useCallback(
    (value: Status) => {
      if (!value.authenticated) {
        if (active.current) channel.current?.postMessage('locked');
        purge();
      }
      active.current = value.authenticated;
      setCsrfToken(value.csrf_token);
      setStatus(value);
    },
    [purge],
  );
  const refresh = useCallback(async () => {
    const before = generation.current;
    try {
      const value = await customInstance<Status>({ url: '/api/security/status', method: 'GET' });
      if (before === generation.current) {
        apply(value);
        setError('');
      }
    } catch (e) {
      purge();
      setError(errorMessage(e));
    }
  }, [apply, purge]);
  const lock = useCallback(async () => {
    // Send with the current CSRF proof, then remove the entire private UI immediately.
    const request = customInstance({ url: '/api/security/lock', method: 'POST', headers: { 'X-CSRF-Token': getCsrfToken() ?? '' } });
    purge();
    channel.current?.postMessage('locked');
    try {
      await request;
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [purge]);

  useEffect(() => {
    const broadcast = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('personal-os-session') : null;
    channel.current = broadcast;
    const expired = () => {
      purge();
      broadcast?.postMessage('locked');
    };
    const message = (event: MessageEvent) => {
      if (event.data === 'locked') purge();
      else if (event.data === 'unlocked') void refresh();
    };
    broadcast?.addEventListener('message', message);
    window.addEventListener('personal-os:locked', expired);
    const activity = () => {
      if (!active.current || document.hidden || Date.now() - lastActivity.current < 30_000) return;
      lastActivity.current = Date.now();
      const before = generation.current;
      void customInstance<Status>({ url: '/api/security/activity', method: 'POST' })
        .then(value => {
          if (before === generation.current) apply(value);
        })
        .catch(() => expired());
    };
    const visible = () => {
      if (!document.hidden) void refresh();
    };
    window.addEventListener('pointerdown', activity);
    window.addEventListener('keydown', activity);
    document.addEventListener('visibilitychange', visible);
    const timer = window.setInterval(() => {
      if (active.current) void refresh();
    }, 15_000);
    const startup = window.setTimeout(() => void refresh(), 0);
    return () => {
      window.clearTimeout(startup);
      broadcast?.close();
      channel.current = null;
      window.removeEventListener('personal-os:locked', expired);
      window.removeEventListener('pointerdown', activity);
      window.removeEventListener('keydown', activity);
      document.removeEventListener('visibilitychange', visible);
      window.clearInterval(timer);
    };
  }, [apply, purge, refresh]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const submittedGeneration = ++generation.current;
    setPending(true);
    setError('');
    try {
      const value = await customInstance<Status>({
        url: `/api/security/${status?.configured ? 'unlock' : 'setup'}`,
        method: 'POST',
        data: { password },
      });
      if (submittedGeneration !== generation.current) return;
      apply(value);
      setPassword('');
      lastActivity.current = Date.now();
      channel.current?.postMessage('unlocked');
    } catch (e) {
      if (submittedGeneration === generation.current) setError(errorMessage(e));
    } finally {
      setPending(false);
    }
  }
  if (status?.authenticated)
    return (
      <div className='flex h-dvh flex-col'>
        <div className='flex h-11 shrink-0 items-center justify-end border-b bg-card px-3'>
          <Button size='sm' variant='default' onClick={() => void lock()}>
            전체 잠금
          </Button>
        </div>
        <div className='min-h-0 flex-1'>{children}</div>
      </div>
    );
  return (
    <main className='flex min-h-screen items-center justify-center p-6'>
      <form onSubmit={submit} className='w-full max-w-sm space-y-4 rounded-xl border bg-card p-6 shadow-sm'>
        <h1 className='text-xl font-semibold'>Personal OS {status?.configured ? '잠금 해제' : status ? '소유자 설정' : '연결 확인'}</h1>
        <p className='text-sm text-muted-foreground'>개인 데이터를 열려면 비밀번호가 필요합니다. 잠금 중에도 승인한 백그라운드 작업은 계속됩니다.</p>
        {status && (
          <>
            <label htmlFor='owner-password' className='block text-sm'>
              비밀번호{!status.configured && ' (12자 이상)'}
            </label>
            <Input
              id='owner-password'
              type='password'
              autoComplete={status.configured ? 'current-password' : 'new-password'}
              value={password}
              onChange={event => setPassword(event.target.value)}
              minLength={status.configured ? 1 : 12}
              maxLength={1024}
              required
              autoFocus
              disabled={pending}
            />
            <Button type='submit' disabled={pending} className='w-full'>
              {pending ? '확인 중…' : status.configured ? '잠금 해제' : '비밀번호 설정'}
            </Button>
          </>
        )}
        {error && (
          <p role='alert' className='text-sm text-destructive'>
            {error}
          </p>
        )}
        {!status && (
          <Button type='button' variant='default' onClick={() => void refresh()}>
            다시 연결
          </Button>
        )}
      </form>
    </main>
  );
}
