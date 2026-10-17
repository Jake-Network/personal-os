'use client';

import { useState } from 'react';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { useListGoals, useListJobApplications } from '@/api-client/generated/personal-data/personal-data';
import { errorMessage } from '@/api-client/api-error';
import type { Category } from '@/api-client/model';
import { CATEGORY_LABEL } from '@/lib/labels';

import { documentsApi, documentsKey, type PersonalDocument } from './api';

const TOPICS: Category[] = ['career', 'financial', 'investment', 'health', 'goals', 'calendar', 'profile'];
const STATUS: Record<string, string> = { pending: '처리 대기', processing: '처리 중', ready: '검색 가능', failed: '처리 실패', queued: '처리 대기' };

export function DocumentsView() {
  const client = useQueryClient();
  const applications = useListJobApplications();
  const goals = useListGoals();
  const query = useQuery({ queryKey: documentsKey, queryFn: documentsApi.list, refetchInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>(['career']);
  const [filter, setFilter] = useState('');
  async function perform(task: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await task();
      await client.invalidateQueries({ queryKey: documentsKey });
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <PageContainer>
      <PageHeader
        title='문서함'
        description='이력서, 채용공고, 투자 원칙, 운동 계획을 올리고 AI 상담에서 함께 참고하세요.'
        actions={
          <Button asChild>
            <Link href='/advisor'>문서로 상담하기</Link>
          </Button>
        }
      />
      {(error || query.error) && <Alert variant='destructive'>{error ?? errorMessage(query.error)}</Alert>}
      <form
        className='mb-6 grid gap-3 rounded-lg border bg-card p-4'
        onSubmit={async e => {
          e.preventDefault();
          const form = e.currentTarget;
          const data = new FormData(form);
          data.set('categories', JSON.stringify(categories));
          for (const key of ['as_of', 'application_id', 'goal_id']) if (!data.get(key)) data.delete(key);
          if (await perform(() => documentsApi.upload(data))) form.reset();
        }}>
        <h2>문서 올리기</h2>
        <label className='grid gap-1 text-sm'>
          파일 (텍스트 PDF · Markdown · TXT)
          <Input name='file' type='file' accept='.pdf,.md,.markdown,.txt' required disabled={busy} />
        </label>
        <label className='grid gap-1 text-sm'>
          제목
          <Input name='title' required maxLength={200} />
        </label>
        <fieldset className='flex flex-wrap gap-3'>
          <legend className='mb-1 text-sm'>주제 (여러 개 선택 가능)</legend>
          {TOPICS.map(c => (
            <label key={c} className='flex items-center gap-1 text-sm'>
              <input
                type='checkbox'
                checked={categories.includes(c)}
                onChange={e => setCategories(prev => (e.target.checked ? [...prev, c] : prev.filter(v => v !== c)))}
              />
              {CATEGORY_LABEL[c]}
            </label>
          ))}
        </fieldset>
        <div className='grid gap-3 sm:grid-cols-2'>
          <label className='grid gap-1 text-sm'>
            문서 종류
            <Input name='kind' placeholder='이력서, 공고, 투자 원칙 등' defaultValue='general' required />
          </label>
          <label className='grid gap-1 text-sm'>
            자료 기준일 (선택)
            <Input name='as_of' type='date' />
          </label>
          <label className='grid gap-1 text-sm'>
            연결할 채용 지원 (선택)
            <NativeSelect name='application_id'>
              <option value=''>연결 안 함</option>
              {applications.data?.map(a => (
                <option key={a.id} value={a.id}>
                  {a.company} · {a.role}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className='grid gap-1 text-sm'>
            연결할 목표 (선택)
            <NativeSelect name='goal_id'>
              <option value=''>연결 안 함</option>
              {goals.data?.map(g => (
                <option key={g.id} value={g.id}>
                  {g.title}
                </option>
              ))}
            </NativeSelect>
          </label>
        </div>
        <p className='text-xs text-faint'>
          공유가 켜진 문서의 관련 발췌문을 상담에 사용합니다. 외부 AI 제공자를 사용하면 발췌문이 해당 제공자에게 전달됩니다. 스캔 PDF와 복잡한 표는
          지원하지 않습니다.
        </p>
        <Button type='submit' variant='primary' disabled={busy || categories.length === 0}>
          {busy ? '처리 중…' : '업로드'}
        </Button>
      </form>
      <label className='mb-3 flex items-center gap-2 text-sm'>
        주제 필터
        <select className='rounded border bg-card p-1' value={filter} onChange={e => setFilter(e.target.value)}>
          <option value=''>전체</option>
          {TOPICS.map(c => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </select>
      </label>
      {query.isLoading && <p>문서를 불러오는 중…</p>}
      {query.data?.length === 0 && <p className='text-muted-foreground'>아직 업로드한 문서가 없습니다.</p>}
      <div className='grid gap-3'>
        {query.data
          ?.filter(d => !filter || d.categories.includes(filter))
          .map(doc => (
            <DocumentCard key={doc.id} doc={doc} busy={busy} perform={perform} />
          ))}
      </div>
    </PageContainer>
  );
}

function DocumentCard({ doc, busy, perform }: { doc: PersonalDocument; busy: boolean; perform: (task: () => Promise<unknown>) => Promise<boolean> }) {
  const [purge, setPurge] = useState(false);
  const [versionDate, setVersionDate] = useState('');
  const [showVersions, setShowVersions] = useState(false);
  const versions = useQuery({
    queryKey: [...documentsKey, doc.id, 'versions'],
    queryFn: () => documentsApi.versions(doc.id),
    enabled: showVersions,
    refetchInterval: showVersions ? 5000 : false,
  });
  return (
    <article className='grid gap-2 rounded-lg border bg-card p-4'>
      <h2>{doc.title}</h2>
      <p className='text-xs text-faint'>
        {doc.filename} · {doc.kind} · {doc.categories.map(c => CATEGORY_LABEL[c as Category] ?? c).join(', ')} ·{' '}
        {doc.as_of ? `기준일 ${doc.as_of}` : '기준일 없음'}
      </p>
      <p className='text-sm'>
        {STATUS[doc.status] ?? doc.status} · 버전 #{doc.latest_version_id ?? '—'}
        {doc.active_version_id && doc.active_version_id !== doc.latest_version_id ? ` · 기존 버전 #${doc.active_version_id} 검색 유지` : ''}
      </p>
      {doc.error && <Alert variant='destructive'>{doc.error}</Alert>}
      <label className='flex items-center gap-2 text-sm'>
        <input
          type='checkbox'
          checked={doc.sharing_enabled}
          disabled={busy}
          onChange={e => void perform(() => documentsApi.update(doc.id, { sharing_enabled: e.target.checked }))}
        />
        상담에 공유
      </label>
      <details className='text-sm'>
        <summary className='cursor-pointer'>제목·주제·종류 수정</summary>
        <form
          className='mt-2 grid gap-2'
          key={doc.updated_at}
          onSubmit={e => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            void perform(() =>
              documentsApi.update(doc.id, {
                title: String(data.get('title')),
                kind: String(data.get('kind')),
                categories: data.getAll('category').map(String),
              }),
            );
          }}>
          <label>
            제목
            <Input name='title' defaultValue={doc.title} required maxLength={200} />
          </label>
          <label>
            문서 종류
            <Input name='kind' defaultValue={doc.kind} required />
          </label>
          <fieldset className='flex flex-wrap gap-2'>
            <legend>주제</legend>
            {TOPICS.map(c => (
              <label key={c} className='flex items-center gap-1'>
                <input type='checkbox' name='category' value={c} defaultChecked={doc.categories.includes(c)} />
                {CATEGORY_LABEL[c]}
              </label>
            ))}
          </fieldset>
          <Button disabled={busy} type='submit'>
            저장
          </Button>
        </form>
      </details>
      <details className='text-sm' onToggle={e => setShowVersions(e.currentTarget.open)}>
        <summary className='cursor-pointer'>버전 이력</summary>
        {versions.isLoading && <p>불러오는 중…</p>}
        {versions.error && <p role='alert'>{errorMessage(versions.error)}</p>}
        {versions.data?.map(v => (
          <p key={v.id} className='my-1 text-xs'>
            #{v.id} · {v.filename} · {v.as_of ?? '기준일 없음'} · {STATUS[v.status] ?? v.status}
            {v.id === doc.active_version_id ? ' · 검색에 사용 중' : ''}
            {v.error ? ` · ${v.error}` : ''}
          </p>
        ))}
      </details>
      <div className='flex flex-wrap items-center gap-2'>
        {doc.status === 'failed' && (
          <Button disabled={busy} onClick={() => void perform(() => documentsApi.retry(doc.id))}>
            다시 처리
          </Button>
        )}
        <label className='text-xs'>
          새 버전 기준일
          <input className='ml-1 rounded border bg-card p-1' type='date' value={versionDate} onChange={e => setVersionDate(e.target.value)} />
        </label>
        <label className='text-sm'>
          새 버전 업로드
          <input
            className='ml-2 max-w-full text-xs'
            type='file'
            accept='.pdf,.md,.markdown,.txt'
            disabled={busy}
            aria-label={`${doc.title} 새 버전 업로드`}
            onChange={e => {
              const file = e.target.files?.[0];
              if (!file) return;
              const data = new FormData();
              data.set('file', file);
              if (versionDate) data.set('as_of', versionDate);
              void perform(() => documentsApi.replace(doc.id, data));
              e.target.value = '';
            }}
          />
        </label>
      </div>
      <div className='flex flex-wrap items-center gap-3 border-t pt-2'>
        <label className='flex items-center gap-1 text-xs'>
          <input type='checkbox' checked={purge} onChange={e => setPurge(e.target.checked)} />
          과거 상담에 저장된 문서 발췌문도 삭제
        </label>
        <Button
          variant='destructive'
          size='sm'
          disabled={busy}
          onClick={() => {
            if (
              confirm(
                purge
                  ? '문서와 과거 상담에 저장된 발췌문을 삭제할까요? 복구할 수 없습니다.'
                  : '문서를 삭제할까요? 과거 상담의 근거 발췌문은 유지됩니다.',
              )
            )
              void perform(() => documentsApi.remove(doc.id, purge));
          }}>
          삭제
        </Button>
      </div>
    </article>
  );
}
