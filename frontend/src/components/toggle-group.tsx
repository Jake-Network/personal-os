import type { ReactNode } from 'react';

import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

/** One choice among a few views of the same data. */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  label,
  options,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  /** Accessible name of the group. */
  label: string;
  options: { value: T; label: ReactNode; icon?: LucideIcon; count?: number }[];
  className?: string;
}) {
  return (
    <div className={cn('inline-flex max-w-full overflow-x-auto rounded-md bg-muted p-0.5', className)} role='group' aria-label={label}>
      {options.map(option => (
        <button
          key={option.value}
          type='button'
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'inline-flex h-7 shrink-0 items-center gap-1 whitespace-nowrap rounded-sm px-3 text-ui text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            value === option.value && 'bg-card font-medium text-foreground shadow-sm',
          )}>
          {option.icon && <option.icon className='size-3.5' aria-hidden />}
          {option.label}
          {!!option.count && <span className='tabular-nums text-faint'>{option.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Any number of choices from a short list. */
export function ChipGroup<T extends string | number>({
  value,
  onChange,
  label,
  options,
}: {
  value: T[];
  onChange: (value: T[]) => void;
  /** Accessible name of the group. */
  label: string;
  options: { value: T; label: ReactNode }[];
}) {
  return (
    <div className='flex flex-wrap gap-1.5' role='group' aria-label={label}>
      {options.map(option => {
        const on = value.includes(option.value);
        return (
          <button
            key={option.value}
            type='button'
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter(v => v !== option.value) : [...value, option.value])}
            className={cn(
              'inline-flex h-7 items-center rounded-full border px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              on ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted',
            )}>
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
