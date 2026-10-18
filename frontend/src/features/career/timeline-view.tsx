'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { errorMessage } from '@/api-client/api-error';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { careerApi } from './api';

const NAMES: Record<string, string> = {
  employment: '재직',
  role: '역할',
  project: '프로젝트',
  contribution: '기여',
  achievement: '성과',
  feedback: '피드백',
  evidence: '근거',
  decision: '결정',
  goal: '목표 기한',
  financial_change: '재무 값 기록',
  monthly_snapshot: '월말 기록',
};

export function TimelineView() {
  const [year, setYear] = useState('');
  const [month, setMonth] = useState('');
  const [project, setProject] = useState('');
  const projects = useQuery({ queryKey: ['career-records'], queryFn: careerApi.list });
  const [company, setCompany] = useState('');
  const [domain, setDomain] = useState('');
  const [offset, setOffset] = useState(0);
  const validYear = /^[0-9]{4}$/.test(year) && Number(year) > 0 && Number(year) < 9999;
  const selectedMonth = month ? Number(month) : 1;
  const nextYear = month && selectedMonth < 12 ? Number(year) : Number(year) + 1;
  const nextMonth = month && selectedMonth < 12 ? selectedMonth + 1 : 1;
  const params = {
    start: validYear ? `${year}-${String(selectedMonth).padStart(2, '0')}-01` : undefined,
    end: validYear ? `${nextYear}-${String(nextMonth).padStart(2, '0')}-01` : undefined,
    domain: domain || undefined,
    company: company || undefined,
    project_id: project ? Number(project) : undefined,
    offset,
    limit: 100,
  };
  const timeline = useQuery({ queryKey: ['timeline', params], queryFn: () => careerApi.timeline(params) });
  return (
    <div className='flex flex-col gap-4 p-4'>
      <div className='flex justify-between'>
        <h1 className='text-xl font-semibold'>인생 기록</h1>
        <Link href='/career'>커리어 기록하기</Link>
      </div>
      <p className='text-sm text-muted-foreground'>
        원본 커리어·결정·목표·재무 변경 기록을 모아 보여줍니다. 월·연도만 알려진 시점은 정밀도를 유지합니다. 목표는 목표 기한에 표시합니다.
      </p>
      <div className='grid gap-3 sm:grid-cols-3'>
        <div>
          <Label htmlFor='timeline-year'>연도 (전체는 비움)</Label>
          <Input
            id='timeline-year'
            inputMode='numeric'
            maxLength={4}
            value={year}
            onChange={e => {
              setYear(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <div>
          <Label htmlFor='timeline-month'>월 (연도 선택 후)</Label>
          <NativeSelect
            id='timeline-month'
            disabled={!validYear}
            value={month}
            onChange={e => {
              setMonth(e.target.value);
              setOffset(0);
            }}>
            <option value=''>전체</option>
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}월
              </option>
            ))}
          </NativeSelect>
        </div>
        <div>
          <Label htmlFor='timeline-project'>프로젝트</Label>
          <NativeSelect
            id='timeline-project'
            value={project}
            onChange={e => {
              setProject(e.target.value);
              setOffset(0);
            }}>
            <option value=''>전체</option>
            {projects.data
              ?.filter(r => r.kind === 'project')
              .map(r => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
          </NativeSelect>
        </div>
        <div>
          <Label htmlFor='timeline-company'>회사 (정확한 이름)</Label>
          <Input
            id='timeline-company'
            value={company}
            onChange={e => {
              setCompany(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <div>
          <Label htmlFor='timeline-domain'>분야</Label>
          <NativeSelect
            id='timeline-domain'
            value={domain}
            onChange={e => {
              setDomain(e.target.value);
              setOffset(0);
            }}>
            <option value=''>전체</option>
            <option value='career'>커리어</option>
            <option value='decisions'>결정</option>
            <option value='goals'>목표</option>
            <option value='finance'>재무 변경</option>
          </NativeSelect>
        </div>
      </div>
      {timeline.isPending && <p>기록을 불러오는 중입니다.</p>}
      {timeline.error && <Alert variant='destructive'>{errorMessage(timeline.error)}</Alert>}
      {timeline.data && <p>총 {timeline.data.total}개 기록</p>}
      {timeline.data?.items.map(item => (
        <Card key={`${item.source_kind}-${item.source_id}`} className='p-4'>
          <p className='text-sm text-muted-foreground'>
            {item.occurred_on ?? '발생 시점 미기록'}
            {item.ended_on ? ` ~ ${item.ended_on}` : ''} · {NAMES[item.source_kind] ?? item.source_kind} {item.company}
          </p>
          <Link href={item.href} className='font-semibold underline'>
            {item.title}
          </Link>
          <p className='text-xs text-muted-foreground'>
            기록 시각 {item.recorded_at}
            {item.status === 'draft' ? ' · 확인 전 초안' : ''}
          </p>
        </Card>
      ))}
      {timeline.data?.total === 0 && <p>해당 기간의 기록이 없습니다.</p>}
      <div className='flex gap-2'>
        <Button disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 100))}>
          이전
        </Button>
        <Button disabled={!timeline.data || offset + 100 >= timeline.data.total} onClick={() => setOffset(v => v + 100)}>
          다음
        </Button>
      </div>
    </div>
  );
}
