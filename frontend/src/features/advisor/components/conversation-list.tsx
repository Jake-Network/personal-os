'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { useListConversations } from '@/api-client/generated/advisor/advisor';
import { cn } from '@/lib/utils';
import { relative } from '@/lib/utils/format';

import { DOMAINS } from '../consts';

export function ConversationList({ activeId, onNavigate }: { activeId: number | null; onNavigate?: () => void }) {
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const { data: conversations = [] } = useListConversations(debounced ? { q: debounced } : undefined, { query: { placeholderData: prev => prev } });

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='flex flex-col gap-2.5 border-b p-3'>
        <Button asChild variant='primary'>
          <Link href='/advisor' onClick={onNavigate}>
            새 상담
          </Link>
        </Button>
        <div className='flex flex-wrap gap-1'>
          {DOMAINS.map(d => (
            <Link
              key={d.key}
              href={`/advisor?domain=${d.key}`}
              onClick={onNavigate}
              title={`${d.label} 상담 시작`}
              className='rounded-full border bg-muted px-2 py-px text-[11.5px] text-muted-foreground hover:bg-accent'>
              {d.label}
            </Link>
          ))}
        </div>
        <Input placeholder='상담 검색' value={query} onChange={e => setQuery(e.target.value)} />
      </div>
      <div className='flex-1 overflow-y-auto'>
        {conversations.length === 0 && <div className='px-4 py-7 text-center text-faint'>상담 기록이 없습니다</div>}
        {conversations.map(c => (
          <Link
            key={c.id}
            href={`/advisor/${c.id}`}
            onClick={onNavigate}
            className={cn('block border-b px-3.5 py-2 text-foreground hover:bg-muted', c.id === activeId && 'bg-accent hover:bg-accent')}>
            <div className='truncate font-medium'>{c.title}</div>
            <div className='text-xs text-faint'>
              {relative(c.updated_at)}
              {c.domain && ` · ${DOMAINS.find(d => d.key === c.domain)?.label}`}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
