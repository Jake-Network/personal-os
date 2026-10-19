'use client';

import { TriangleAlert } from 'lucide-react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { flagDetail, flagText } from '@/lib/labels';
import { cn } from '@/lib/utils';

export interface QualityFlag {
  code: string;
  detail?: string | null;
}

/** Data-quality flags as a compact marker next to the value they qualify; the details open on demand. */
export function QualityBadge({ flags, label = '확인 필요', className }: { flags: QualityFlag[]; label?: string; className?: string }) {
  if (!flags.length) return null;
  return (
    <Popover>
      <PopoverTrigger
        className={cn(
          'inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-px text-2xs text-warning focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          className,
        )}>
        <TriangleAlert className='size-3' aria-hidden />
        {label}
        {flags.length > 1 && ` ${flags.length}`}
      </PopoverTrigger>
      <PopoverContent>
        <ul className='flex flex-col gap-1.5'>
          {flags.map((f, i) => {
            const detail = flagDetail(f.code, f.detail ?? undefined);
            return (
              <li key={`${f.code}-${i}`}>
                {flagText(f.code)}
                {detail && <span className='block text-xs text-faint'>{detail}</span>}
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
