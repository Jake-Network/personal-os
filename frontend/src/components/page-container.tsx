import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

export function PageContainer({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('mx-auto max-w-[1180px] px-4 pb-10 pt-4 md:px-7 md:pb-12 md:pt-6', className)}>{children}</div>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className='mb-[18px] flex flex-col items-start justify-between gap-4 md:flex-row md:items-end'>
      <div>
        {eyebrow && <div className='text-xs text-faint'>{eyebrow}</div>}
        <h1 className='text-xl'>{title}</h1>
        {description && <p className='mt-1 text-muted-foreground'>{description}</p>}
      </div>
      {actions && <div className='flex flex-wrap items-center gap-2'>{actions}</div>}
    </div>
  );
}
