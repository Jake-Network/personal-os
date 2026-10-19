import { cn } from '@/lib/utils';

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} />;
}

/** Placeholder rows while a list loads; announces loading once. */
export function ListSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div role='status' className={cn('flex flex-col gap-2 py-2', className)}>
      <span className='sr-only'>불러오는 중</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className='h-9 w-full' />
      ))}
    </div>
  );
}
