'use client';

import type { ReactNode } from 'react';

import { Info } from 'lucide-react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/** Explanations of how a value is derived live here, not in permanent helper text. */
export function InfoPopover({ label = '자세히', className, children }: { label?: string; className?: string; children: ReactNode }) {
  return (
    <Popover>
      <PopoverTrigger
        aria-label={label}
        className={cn(
          'inline-flex size-6 items-center justify-center rounded-md text-faint hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          className,
        )}>
        <Info className='size-3.5' />
      </PopoverTrigger>
      <PopoverContent className='flex flex-col gap-1.5 text-muted-foreground'>{children}</PopoverContent>
    </Popover>
  );
}
