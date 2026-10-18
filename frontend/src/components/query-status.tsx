'use client';

import { errorMessage } from '@/api-client/api-error';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

export function QueryStatus({ pending, error, retry, label }: { pending: boolean; error: unknown; retry: () => unknown; label: string }) {
  if (error)
    return (
      <Alert variant='destructive'>
        <span>
          {label}을 불러오지 못했습니다. {errorMessage(error)}
        </span>
        <Button type='button' size='sm' onClick={() => void retry()}>
          다시 시도
        </Button>
      </Alert>
    );
  if (pending)
    return (
      <p role='status' className='p-3 text-sm text-muted-foreground'>
        {label}을 불러오는 중…
      </p>
    );
  return null;
}
