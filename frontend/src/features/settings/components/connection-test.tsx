'use client';

import { CheckCircle2, CircleAlert } from 'lucide-react';

import { useTestConnection } from '@/api-client/generated/ai-provider/ai-provider';
import { notify } from '@/components/notify';
import { Button } from '@/components/ui/button';

/** Sends one fixed sentence (no personal data) to the selected provider, only when pressed. */
export function ConnectionTest() {
  const test = useTestConnection({ mutation: { onError: notify.error } });
  const result = test.data;
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <Button size='sm' disabled={test.isPending} onClick={() => test.mutate()}>
        {test.isPending ? '확인하는 중…' : '연결 테스트'}
      </Button>
      {result && (
        <span role='status' className={`flex items-center gap-1 text-xs ${result.ok ? 'text-success' : 'text-destructive'}`}>
          {result.ok ? <CheckCircle2 className='size-3.5' aria-hidden /> : <CircleAlert className='size-3.5' aria-hidden />}
          {result.message}
          {result.ok && result.model ? ` (${result.model})` : ''}
        </span>
      )}
      {!result && <span className='text-xs text-faint'>개인 데이터 없이 짧은 문장 하나를 보내 실제로 답하는지 확인합니다.</span>}
    </div>
  );
}
