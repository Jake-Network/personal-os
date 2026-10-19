'use client';

import { useState } from 'react';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { History } from 'lucide-react';
import Link from 'next/link';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { dateOnly } from '@/lib/utils/format';
import { todayKey } from '@/lib/utils/zoned';

import { careerApi } from './api';

const KIND_LABEL: Record<string, string> = {
  employment: '재직',
  role: '역할',
  project: '프로젝트',
  contribution: '기여',
  achievement: '성과',
  feedback: '피드백',
  evidence: '근거',
  decision: '결정',
  goal: '목표일',
  financial_change: '재무 값 변경',
  monthly_snapshot: '월말 기록',
};
const DOMAINS = [
  ['', '전체'],
  ['career', '커리어'],
  ['decisions', '결정'],
  ['goals', '목표'],
  ['finance', '재무'],
] as const;
const PAGE = 50;
const MAX = 500; // the API's page limit

/** Dates keep the precision they were recorded with: a year, a month, or a day. */
export function periodText(value: string | null | undefined): string {
  if (!value) return '시점 미기록';
  if (/^\d{4}$/.test(value)) return `${value}년`;
  const m = /^(\d{4})-(\d{2})$/.exec(value);
  if (m) return `${m[1]}년 ${Number(m[2])}월`;
  return dateOnly(value);
}

/** Career, decisions, goals and finance changes in one chronological list. */
export function TimelineView() {
  const thisYear = Number(todayKey().slice(0, 4));
  const [year, setYear] = useState('');
  const [domain, setDomain] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const params = {
    start: year ? `${year}-01-01` : undefined,
    end: year ? `${Number(year) + 1}-01-01` : undefined,
    domain: domain || undefined,
    offset: 0,
    limit,
  };
  const timeline = useQuery({ queryKey: ['/api/timeline', params], queryFn: () => careerApi.timeline(params), placeholderData: keepPreviousData });
  const items = timeline.data?.items ?? [];

  return (
    <>
      <TabToolbar className='items-end'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='timeline-year'>기간</Label>
          <NativeSelect
            id='timeline-year'
            value={year}
            onChange={e => {
              setYear(e.target.value);
              setLimit(PAGE);
            }}>
            <option value=''>전체 기간</option>
            {Array.from({ length: 30 }, (_, i) => thisYear + 1 - i).map(y => (
              <option key={y} value={y}>
                {y}년
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='timeline-domain'>종류</Label>
          <NativeSelect
            id='timeline-domain'
            value={domain}
            onChange={e => {
              setDomain(e.target.value);
              setLimit(PAGE);
            }}>
            {DOMAINS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
        {timeline.data && <span className='ml-auto pb-1.5 text-ui text-muted-foreground'>{timeline.data.total}개 기록</span>}
      </TabToolbar>

      <QueryStatus pending={timeline.isPending} error={timeline.error} retry={timeline.refetch} label='타임라인' />
      {timeline.data?.total === 0 && (
        <EmptyState icon={History} title='이 기간의 기록이 없습니다'>
          경력·결정·목표·재무 기록을 남기면 여기에 시간순으로 모입니다.
        </EmptyState>
      )}
      <ol className='flex flex-col'>
        {items.map((item, i) => {
          const y = item.occurred_on?.slice(0, 4) ?? '';
          const header = i === 0 || y !== (items[i - 1].occurred_on?.slice(0, 4) ?? '');
          return (
            <li key={`${item.source_kind}-${item.source_id}`}>
              {header && <h2 className='mt-5 border-b pb-1 text-title font-semibold first:mt-0'>{y ? `${y}년` : '시점 미기록'}</h2>}
              <div className='flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b py-2'>
                <span className='w-32 shrink-0 text-ui tabular-nums text-muted-foreground'>
                  {periodText(item.occurred_on)}
                  {item.ended_on ? ` – ${periodText(item.ended_on)}` : ''}
                </span>
                <span className='text-xs text-faint'>{KIND_LABEL[item.source_kind] ?? '기록'}</span>
                <Link href={item.href} className='font-medium hover:underline'>
                  {item.title}
                </Link>
                {item.company && <span className='text-xs text-muted-foreground'>{item.company}</span>}
                {item.status === 'draft' && <Badge variant='warning'>확인 전 초안</Badge>}
              </div>
            </li>
          );
        })}
      </ol>
      {timeline.data && items.length < timeline.data.total && limit >= MAX && (
        <p className='mt-4 text-center text-ui text-muted-foreground'>최근 {MAX}개까지 보여 줍니다. 기간이나 종류를 좁혀 보세요.</p>
      )}
      {timeline.data && items.length < timeline.data.total && limit < MAX && (
        <div className='mt-4 flex justify-center'>
          <Button disabled={timeline.isFetching} onClick={() => setLimit(l => Math.min(MAX, l + PAGE))}>
            {timeline.isFetching ? '불러오는 중…' : '더 보기'}
          </Button>
        </div>
      )}
    </>
  );
}
