'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { useListConversations, useSearchMessages } from '@/api-client/generated/advisor/advisor';
import { cn } from '@/lib/utils';
import { relative } from '@/lib/utils/format';

import { DOMAINS } from '../consts';

export function ConversationList({ activeId, onNavigate }: { activeId: number | null; onNavigate?: () => void }) {
  const [offset, setOffset] = useState(0);
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const search = useSearchMessages({ q: debounced || ' ', limit: 30, since: since ? `${since}T00:00:00Z` : undefined, until: until ? `${until}T00:00:00Z` : undefined }, { query: { enabled: !!debounced } });

  const { data: conversations = [] } = useListConversations(
    {
      q: debounced || undefined,
      limit: 30,
      offset,
      since: since ? `${since}T00:00:00Z` : undefined,
      until: until ? `${until}T00:00:00Z` : undefined,
    },
    { query: { placeholderData: prev => prev } },
  );

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
        <Input
          aria-label='상담 제목과 본문 검색'
          placeholder='제목·본문 검색'
          value={query}
          onChange={e => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <label className='text-xs'>
          시작일 (UTC)
          <Input
            type='date'
            value={since}
            onChange={e => {
              setSince(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label className='text-xs'>
          종료일 미포함 (UTC)
          <Input
            type='date'
            value={until}
            onChange={e => {
              setUntil(e.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      <div className='flex-1 overflow-y-auto'>
        {debounced && search.data?.map(m => <Link key={`match-${m.id}`} href={`/advisor/${m.conversation_id}?message=${m.id}#message-${m.id}`} onClick={onNavigate} className='block border-b p-3 text-sm'><span className='text-xs text-faint'>원문 메시지 #{m.id}</span><p className='line-clamp-3'>{m.content}</p></Link>)}
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
      <div className='flex justify-between p-2'>
        <Button size='sm' disabled={!offset} onClick={() => setOffset(v => Math.max(0, v - 30))}>
          이전
        </Button>
        <Button size='sm' disabled={conversations.length < 30} onClick={() => setOffset(v => v + 30)}>
          다음
        </Button>
      </div>
    </div>
  );
}
