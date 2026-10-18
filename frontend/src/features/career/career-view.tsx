'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { customInstance } from '@/api-client/custom-client';
import { errorMessage } from '@/api-client/api-error';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DataForm } from '@/features/personal-data/components/data-form';
import { recordOptions } from '@/features/personal-data/utils/record-options';
import { type OpenApiSpec, schemaFields } from '@/features/personal-data/utils/schema-fields';

import { type CareerRecord, careerApi } from './api';

const KIND_LABELS: Record<string, string> = {
  employment: '재직',
  role: '역할 변화',
  project: '프로젝트',
  contribution: '본인 기여',
  achievement: '성과',
  feedback: '피드백·배운 점',
  evidence: '근거',
  planned: '예정',
  active: '진행 중',
  completed: '완료',
  paused: '중단',
  cancelled: '취소',
};
const LABELS: Record<string, string> = {
  progress: '진행 상태',
  parent_id: '상위 기록',
  organization: '조직',
  started_on: '시작·발생 시점 (YYYY / YYYY-MM / YYYY-MM-DD)',
  ended_on: '종료 시점 (같은 형식)',
  description: '책임 범위·문제·목표·피드백',
  approach: '본인이 선택한 접근법',
  outcome: '성과·측정 기간·협업 범위',
  lessons: '배운 점·다음에 바꿀 점',
  evidence_url: '근거 URL',
  skills: '사용한 역량 (쉼표로 구분)',
  share_with_advisor: '상담 공유 허용 (별도 상담 정책도 적용)',
};
const TEXT_FIELDS = new Set(['description', 'approach', 'outcome', 'lessons']);

export function CareerView() {
  const cache = useQueryClient();
  const list = useQuery({ queryKey: ['career-records'], queryFn: careerApi.list });
  const schema = useQuery({
    queryKey: ['/openapi.json'],
    queryFn: () => customInstance<OpenApiSpec>({ url: '/openapi.json' }),
    staleTime: Infinity,
    select: spec =>
      schemaFields({ ...spec, paths: { '/api/data/career': spec.paths?.['/api/career/records'] ?? {} } }, 'career')
        .filter(f => !['source', 'source_message_id', 'source_document_version_id'].includes(f.name))
        .map(f => (TEXT_FIELDS.has(f.name) ? { ...f, kind: 'longtext' as const } : f)),
  });
  const [editing, setEditing] = useState<CareerRecord | 'new' | null>(null);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const refresh = async () => {
    await Promise.all([cache.invalidateQueries({ queryKey: ['career-records'] }), cache.invalidateQueries({ queryKey: ['timeline'] })]);
  };
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    setPending(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(false);
    }
  };
  const save = async (payload: Record<string, unknown>) => {
    await careerApi.save(
      {
        ...payload,
        skills: String(payload.skills ?? '')
          .split(',')
          .map(s => s.trim())
          .filter(Boolean),
        ...(editing && editing !== 'new'
          ? { source: editing.source, source_message_id: editing.source_message_id, source_document_version_id: editing.source_document_version_id }
          : {}),
      },
      editing && editing !== 'new' ? editing.id : undefined,
    );
    await refresh();
    setEditing(null);
  };
  const rows = (list.data ?? []).filter(r => !filter || [r.title, r.company, ...r.skills].some(s => s?.toLowerCase().includes(filter.toLowerCase())));

  return (
    <div className='flex flex-col gap-4 p-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h1 className='text-xl font-semibold'>커리어 기록</h1>
        <div className='flex gap-2'>
          <Link href='/timeline'>인생 기록</Link>
          <Button variant='primary' onClick={() => setEditing('new')}>
            기록 추가
          </Button>
        </div>
      </div>
      <p className='text-sm text-muted-foreground'>
        재직 → 프로젝트 → 본인 기여 → 성과와 근거를 연결합니다. 시점을 월·연도까지만 알아도 그대로 기록하세요. AI·문서에서 추출한 기록은 확인 전
        초안입니다. 상담 공유는 상위 기록·원본 출처의 제한도 함께 따릅니다.
      </p>
      {(error || list.error || schema.error) && <Alert variant='destructive'>{error ?? errorMessage(list.error ?? schema.error)}</Alert>}
      {editing && schema.data && (
        <Card className='p-4'>
          <DataForm
            key={editing === 'new' ? 'new' : editing.id}
            fields={schema.data}
            labels={LABELS}
            enumLabels={KIND_LABELS}
            recordChoices={{ parent_id: recordOptions((list.data ?? []).filter(r => editing === 'new' || r.id !== editing.id)) }}
            current={editing === 'new' ? undefined : { ...editing, skills: editing.skills.join(', ') }}
            submitLabel='기록 저장'
            onSubmit={save}
            onCancel={() => setEditing(null)}
          />
        </Card>
      )}
      <div>
        <Label htmlFor='career-filter'>회사·제목·역량 검색</Label>
        <Input id='career-filter' value={filter} onChange={e => setFilter(e.target.value)} />
      </div>
      {list.isPending && <p>기록을 불러오는 중입니다.</p>}
      {!list.isPending && !list.error && rows.length === 0 && <p>아직 해당 기록이 없습니다. 재직 또는 프로젝트부터 추가하세요.</p>}
      {rows.map(r => (
        <Card id={`record-${r.id}`} key={r.id} className='p-4'>
          <div className='flex flex-wrap justify-between gap-2'>
            <h2 className='font-semibold'>
              #{r.id} · {KIND_LABELS[r.kind]} · {r.title} · {KIND_LABELS[r.progress]}
            </h2>
            <span>
              {r.status === 'draft' ? '확인 전 초안' : '확인됨'} · {r.share_with_advisor ? '공유 허용' : '로컬 전용'}
            </span>
          </div>
          <p className='text-sm text-muted-foreground'>
            {[r.company, r.organization, r.role].filter(Boolean).join(' · ')} · {r.started_on ?? '발생 시점 미기록'}
            {r.ended_on ? ` ~ ${r.ended_on}` : ''} · 기록 {r.recorded_at.slice(0, 10)}
          </p>
          {r.parent_id && (
            <p>
              상위 기록:{' '}
              <a href={`#record-${r.parent_id}`}>
                #{r.parent_id} {list.data?.find(x => x.id === r.parent_id)?.title}
              </a>
            </p>
          )}
          {(['description', 'approach', 'outcome', 'lessons'] as const).map(
            key =>
              r[key] && (
                <p key={key} className='whitespace-pre-wrap py-1'>
                  <strong>{LABELS[key]}: </strong>
                  {r[key]}
                </p>
              ),
          )}
          {r.evidence_url && (
            <a href={r.evidence_url} target='_blank' rel='noopener noreferrer' className='underline'>
              근거 열기
            </a>
          )}
          {r.skills.length > 0 && <p>역량: {r.skills.join(' · ')}</p>}
          <div className='mt-2 flex gap-2'>
            <Button onClick={() => setEditing(r)}>수정</Button>
            {r.status === 'draft' && (
              <Button disabled={pending} onClick={() => void act(() => careerApi.confirm(r.id))}>
                내용 확인·확정
              </Button>
            )}
            <Button
              disabled={pending}
              onClick={() => {
                if (confirm(`“${r.title}” 기록을 삭제할까요? 복구할 수 없습니다.`)) void act(() => careerApi.remove(r.id));
              }}>
              삭제
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}
