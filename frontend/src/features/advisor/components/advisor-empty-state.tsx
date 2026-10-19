'use client';

import Link from 'next/link';

import type { Category } from '@/api-client/model';
import { ALL_CATEGORIES, CATEGORY_LABEL } from '@/lib/labels';

/** A new consultation: what it can draw on, and questions to start from (they fill the box, not send). */
export function AdvisorEmptyState({
  suggestions,
  excluded,
  disabled,
  onPick,
}: {
  suggestions: string[];
  excluded: Category[];
  disabled?: boolean;
  onPick: (text: string) => void;
}) {
  const shared = ALL_CATEGORIES.filter(c => c !== 'profile' && !excluded.includes(c));
  return (
    <div className='mx-auto flex w-full max-w-[760px] flex-col gap-4 py-6'>
      <div>
        <h2 className='text-xl font-bold tracking-tight'>무엇을 함께 살펴볼까요?</h2>
        <p className='mt-1 text-muted-foreground'>
          {shared.length ? `${shared.map(c => CATEGORY_LABEL[c]).join('·')} 기록을 바탕으로 답합니다.` : '지금은 상담에 공유하는 기록이 없습니다.'}{' '}
          <Link href='/settings/privacy' className='text-primary hover:underline'>
            공유 설정
          </Link>
        </p>
      </div>
      <div className='grid gap-2 sm:grid-cols-2'>
        {suggestions.map(s => (
          <button
            key={s}
            type='button'
            disabled={disabled}
            onClick={() => onPick(s)}
            className='rounded-lg border bg-card px-3.5 py-3 text-left text-ui hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50'>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
