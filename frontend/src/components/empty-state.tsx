import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

export function EmptyState({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('px-4 py-7 text-center text-faint', className)}>{children}</div>;
}
