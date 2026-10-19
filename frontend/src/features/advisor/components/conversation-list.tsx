'use client';

import { useEffect, useState } from 'react';

import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';

import { ChevronDown, Plus, Search } from 'lucide-react';
import Link from 'next/link';

import { getListConversationsQueryKey, listConversations, useSearchMessages } from '@/api-client/generated/advisor/advisor';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { cn } from '@/lib/utils';
import { dateTime, relative } from '@/lib/utils/format';

import { DOMAINS } from '../consts';

const PAGE = 30;

const PERIODS = [
  { value: '', label: '전체 기간' },
  { value: '7', label: '최근 7일' },
  { value: '30', label: '최근 30일' },
  { value: '90', label: '최근 3개월' },
  { value: '365', label: '최근 1년' },
];

/** Start of a "last N days" window as an instant; the server compares instants, so no zone is implied. */
function sinceOf(days: string, now: number): string | undefined {
  return days ? new Date(now - Number(days) * 86_400_000).toISOString() : undefined;
}

export function ConversationList({ activeId, onNavigate }: { activeId: number | null; onNavigate?: () => void }) {
  // The window start is fixed when the period is picked, so the query key stays stable between renders.
  const [period, setPeriod] = useState<{ days: string; since?: string }>({ days: '' });
  const since = period.since;
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const search = useSearchMessages({ q: debounced || ' ', limit: PAGE, since }, { query: { enabled: !!debounced } });
  const filters = { q: debounced || undefined, since };
  // Same key prefix as the generated list, so existing invalidations refresh it.
  const list = useInfiniteQuery({
    queryKey: [...getListConversationsQueryKey(filters), 'pages'],
    queryFn: ({ pageParam, signal }) => listConversations({ ...filters, limit: PAGE, offset: pageParam }, undefined, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.length < PAGE ? undefined : pages.length * PAGE),
    placeholderData: keepPreviousData,
  });
  const conversations = list.data?.pages.flat() ?? [];

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='flex flex-col gap-2 border-b p-3'>
        <div className='flex'>
          <Button asChild variant='primary' className='flex-1 rounded-r-none'>
            <Link href='/advisor' onClick={onNavigate}>
              <Plus /> 새 상담
            </Link>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant='primary' size='icon' className='rounded-l-none border-l border-l-primary-foreground/30' aria-label='분야를 골라 새 상담'>
                <ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>분야를 정해 시작</DropdownMenuLabel>
              {DOMAINS.map(d => (
                <DropdownMenuItem key={d.key} asChild>
                  <Link href={`/advisor?domain=${d.key}`} onClick={onNavigate}>
                    {d.label} 상담
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className='relative'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint' aria-hidden />
          <Input
            aria-label='상담 제목과 내용 검색'
            placeholder='상담 검색'
            className='pl-8'
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
        <NativeSelect
          aria-label='기간'
          value={period.days}
          onChange={e => setPeriod({ days: e.target.value, since: sinceOf(e.target.value, Date.now()) })}>
          {PERIODS.map(p => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className='flex-1 overflow-y-auto'>
        {debounced && !!search.data?.length && (
          <div className='border-b'>
            <p className='px-3.5 pb-1 pt-2 text-2xs font-medium text-faint'>내용에서 찾음</p>
            {search.data.map(m => (
              <Link
                key={`match-${m.id}`}
                href={`/advisor/${m.conversation_id}?message=${m.id}#message-${m.id}`}
                onClick={onNavigate}
                className='block px-3.5 py-2 text-ui hover:bg-muted'>
                <p className='line-clamp-2'>{m.content}</p>
                <span className='text-2xs text-faint'>{dateTime(m.created_at)}</span>
              </Link>
            ))}
          </div>
        )}
        {list.isSuccess && conversations.length === 0 && (
          <p className='px-4 py-7 text-center text-ui text-muted-foreground'>{debounced || period.days ? '찾는 상담이 없습니다' : '아직 상담이 없습니다'}</p>
        )}
        {conversations.map(c => (
          <Link
            key={c.id}
            href={`/advisor/${c.id}`}
            onClick={onNavigate}
            aria-current={c.id === activeId ? 'page' : undefined}
            className={cn('block px-3.5 py-2 text-foreground hover:bg-muted', c.id === activeId && 'bg-accent hover:bg-accent')}>
            <div className='truncate text-ui font-medium'>{c.title}</div>
            <div className='text-2xs text-faint'>
              {relative(c.updated_at)}
              {c.domain && ` · ${DOMAINS.find(d => d.key === c.domain)?.label ?? ''}`}
            </div>
          </Link>
        ))}
        {list.hasNextPage && (
          <div className='p-2'>
            <Button size='sm' variant='ghost' className='w-full' disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
              더 보기
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
