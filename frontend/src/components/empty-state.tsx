import type { ReactNode } from 'react';

import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

/** No data yet: say so in one line and offer the next step. */
export function EmptyState({
  icon: Icon,
  title,
  action,
  className,
  children,
}: {
  icon?: LucideIcon;
  title?: string;
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={cn('flex flex-col items-center gap-2 px-4 py-8 text-center text-muted-foreground', className)}>
      {Icon && <Icon className='size-6 text-faint' aria-hidden />}
      {title && <p className='font-medium text-foreground'>{title}</p>}
      {children && <div className='text-ui'>{children}</div>}
      {action && <div className='mt-1'>{action}</div>}
    </div>
  );
}
