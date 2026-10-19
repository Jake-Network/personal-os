import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { InfoPopover } from './info-popover';

export function PageContainer({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('mx-auto max-w-[1180px] px-4 pb-10 pt-4 md:px-7 md:pb-12 md:pt-6', className)}>{children}</div>;
}

/** One title, at most one short line about what to do here, and page actions. */
export function PageHeader({
  title,
  description,
  info,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  info?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('mb-5 flex flex-col items-start justify-between gap-3 md:flex-row md:items-end', className)}>
      <div className='min-w-0'>
        <div className='flex items-center gap-1'>
          <h1 className='text-xl font-bold tracking-tight'>{title}</h1>
          {info && <InfoPopover label={`${title} 안내`}>{info}</InfoPopover>}
        </div>
        {description && <p className='mt-1 text-muted-foreground'>{description}</p>}
      </div>
      {actions && <div className='flex flex-wrap items-center gap-2'>{actions}</div>}
    </div>
  );
}

/** A flat titled block; use Card only for things you act on. */
export function Section({
  title,
  count,
  actions,
  info,
  className,
  children,
}: {
  title?: ReactNode;
  count?: number;
  actions?: ReactNode;
  info?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn('mb-7', className)}>
      {(title || actions) && (
        <div className='mb-2 flex min-h-8 items-center gap-2 border-b pb-1.5'>
          {title && (
            <h2 className='flex items-center gap-1.5 text-title font-semibold'>
              {title}
              {count !== undefined && <span className='text-ui font-normal text-faint'>{count}</span>}
            </h2>
          )}
          {info && <InfoPopover>{info}</InfoPopover>}
          {actions && <div className='ml-auto flex items-center gap-1.5'>{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
