'use client';

import { errorMessage } from '@/api-client/api-error';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { ListSkeleton } from './skeleton';

/** Loading and failure for one query; renders nothing once data is there. */
export function QueryStatus({ pending, error, retry, label, rows }: { pending: boolean; error: unknown; retry: () => unknown; label: string; rows?: number }) {
  if (error)
    return (
      <Alert variant='destructive'>
        <span className='flex-1'>
          {label} 불러오기 실패 · {errorMessage(error)}
        </span>
        <Button type='button' size='sm' onClick={() => void retry()}>
          다시 시도
        </Button>
      </Alert>
    );
  if (pending) return <ListSkeleton rows={rows} />;
  return null;
}
