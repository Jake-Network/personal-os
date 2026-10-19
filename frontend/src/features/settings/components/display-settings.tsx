'use client';

import { useEffect, useState } from 'react';

import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';

import { Section } from '@/components/page-container';
import { cn } from '@/lib/utils';

const THEMES = [
  { value: 'system', label: '시스템 설정', icon: Monitor },
  { value: 'light', label: '밝게', icon: Sun },
  { value: 'dark', label: '어둡게', icon: Moon },
] as const;

export function DisplaySettings() {
  const { theme, setTheme } = useTheme();
  // The stored theme is only known in the browser.
  const [mounted, setMounted] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- next-themes resolves the theme after hydration
  useEffect(() => setMounted(true), []);

  return (
    <div className='max-w-[720px]'>
      <Section title='테마'>
        <div role='radiogroup' aria-label='테마' className='grid grid-cols-1 gap-2 py-2 sm:grid-cols-3'>
          {THEMES.map(t => {
            const selected = mounted && theme === t.value;
            return (
              <button
                key={t.value}
                type='button'
                role='radio'
                aria-checked={selected}
                onClick={() => setTheme(t.value)}
                className={cn(
                  'flex h-11 items-center gap-2 rounded-lg border bg-card px-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  selected ? 'border-primary bg-accent font-semibold text-accent-foreground' : 'hover:bg-muted',
                )}>
                <t.icon className='size-4' aria-hidden />
                {t.label}
              </button>
            );
          })}
        </div>
      </Section>
    </div>
  );
}
