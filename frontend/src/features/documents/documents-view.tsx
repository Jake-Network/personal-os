'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, MessagesSquare, Upload } from 'lucide-react';
import Link from 'next/link';

import { errorMessage } from '@/api-client/api-error';
import { useListGoals, useListJobApplications } from '@/api-client/generated/personal-data/personal-data';
import type { Category } from '@/api-client/model';
import { useConfirm } from '@/components/confirm-dialog';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { PageContainer, PageHeader, Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { CATEGORY_LABEL } from '@/lib/labels';
import { dateOnly, dateTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import { documentsApi, documentsKey, type PersonalDocument } from './api';

const TOPICS: Category[] = ['career', 'financial', 'investment', 'health', 'goals', 'calendar', 'profile'];
const ACCEPT = '.pdf,.md,.markdown,.txt';

export const DOCUMENT_KINDS: Record<string, string> = {
  resume: '이력서',
  job_posting: '채용 공고',
  portfolio: '포트폴리오',
  investment_policy: '투자 원칙',
  financial_statement: '금융 자료',
  workout_plan: '운동 계획',
  note: '메모',
  general: '기타',
};
const kindLabel = (kind: string) => DOCUMENT_KINDS[kind] ?? kind;

const STATUS: Record<string, { label: string; tone: NonNullable<BadgeProps['variant']> }> = {
  pending: { label: '처리 대기', tone: 'default' },
  queued: { label: '처리 대기', tone: 'default' },
  processing: { label: '처리 중', tone: 'accent' },
  ready: { label: '검색 가능', tone: 'success' },
  failed: { label: '처리 실패', tone: 'destructive' },
};
const IN_PROGRESS = new Set(['pending', 'queued', 'processing']);

function StatusLabel({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: 'default' as const };
  return <Badge variant={s.tone}>{s.label}</Badge>;
}

/** A replacement still processing while the previous version keeps answering searches. */
const replacing = (d: PersonalDocument) => d.active_version_id !== null && d.latest_version_id !== null && d.active_version_id !== d.latest_version_id;

function useDocumentAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (task: () => Promise<unknown>) => task(),
    onSuccess: () => client.invalidateQueries({ queryKey: documentsKey }),
    onError: notify.error,
  });
}

function TopicPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className='flex flex-wrap gap-1.5' role='group' aria-label='주제'>
      {TOPICS.map(c => {
        const on = value.includes(c);
        return (
          <button
            key={c}
            type='button'
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter(v => v !== c) : [...value, c])}
            className={cn(
              'inline-flex h-7 items-center rounded-full border px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              on ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted',
            )}>
            {CATEGORY_LABEL[c]}
          </button>
        );
      })}
    </div>
  );
}

function KindSelect({ id, name, defaultValue }: { id: string; name: string; defaultValue?: string }) {
  const known = !defaultValue || defaultValue in DOCUMENT_KINDS;
  return (
    <NativeSelect id={id} name={name} required defaultValue={defaultValue ?? ''}>
      <option value='' disabled>
        선택
      </option>
      {!known && <option value={defaultValue}>{defaultValue}</option>}
      {Object.entries(DOCUMENT_KINDS).map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </NativeSelect>
  );
}

function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const applications = useListJobApplications({ query: { enabled: open } });
  const goals = useListGoals({ query: { enabled: open } });
  const [categories, setCategories] = useState<string[]>(['career']);
  const [title, setTitle] = useState('');
  const upload = useMutation({
    mutationFn: (data: FormData) => documentsApi.upload(data),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: documentsKey });
      notify.success('올렸습니다. 처리가 끝나면 상담에서 검색됩니다.');
      setTitle('');
      onClose();
    },
  });
  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>문서 올리기</DialogTitle>
        </DialogHeader>
        <form
          className='flex flex-col gap-3'
          onSubmit={e => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            data.set('categories', JSON.stringify(categories));
            for (const key of ['as_of', 'application_id', 'goal_id']) if (!data.get(key)) data.delete(key);
            upload.mutate(data);
          }}>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='doc-file'>파일</Label>
            <Input
              id='doc-file'
              name='file'
              type='file'
              accept={ACCEPT}
              required
              onChange={e => {
                const file = e.target.files?.[0];
                if (file && !title) setTitle(file.name.replace(/\.[^.]+$/, ''));
              }}
            />
            <span className='text-xs text-faint'>텍스트가 있는 PDF, Markdown, TXT. 스캔한 PDF와 복잡한 표는 읽지 못합니다.</span>
          </div>
          <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='doc-title'>제목</Label>
              <Input id='doc-title' name='title' required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='doc-kind'>종류</Label>
              <KindSelect id='doc-kind' name='kind' />
            </div>
          </div>
          <div className='flex flex-col gap-1.5'>
            <span className='text-ui font-medium'>주제</span>
            <TopicPicker value={categories} onChange={setCategories} />
          </div>
          <div className='grid grid-cols-1 gap-3 md:grid-cols-3'>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='doc-asof'>자료 기준일</Label>
              <Input id='doc-asof' name='as_of' type='date' />
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='doc-app'>관련 채용 지원</Label>
              <NativeSelect id='doc-app' name='application_id'>
                <option value=''>없음</option>
                {applications.data?.map(a => (
                  <option key={a.id} value={a.id}>
                    {a.company} · {a.role}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='doc-goal'>관련 목표</Label>
              <NativeSelect id='doc-goal' name='goal_id'>
                <option value=''>없음</option>
                {goals.data?.map(g => (
                  <option key={g.id} value={g.id}>
                    {g.title}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <p className='text-xs text-muted-foreground'>상담에 공유하면 질문과 관련된 발췌문이 설정한 AI 제공자에게 전달됩니다.</p>
          {upload.error && <Alert variant='destructive'>{errorMessage(upload.error)}</Alert>}
          <div className='flex justify-end gap-2'>
            <Button type='button' onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={upload.isPending || categories.length === 0}>
              {upload.isPending ? '올리는 중…' : '올리기'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DocumentSheet({ doc, onClose }: { doc: PersonalDocument; onClose: () => void }) {
  const confirmDialog = useConfirm();
  const action = useDocumentAction();
  const [categories, setCategories] = useState(doc.categories);
  const [versionDate, setVersionDate] = useState('');
  const [purge, setPurge] = useState<'keep' | 'purge'>('keep');
  const versions = useQuery({
    queryKey: [...documentsKey, doc.id, 'versions'],
    queryFn: () => documentsApi.versions(doc.id),
    refetchInterval: q => (q.state.data?.some(v => IN_PROGRESS.has(v.status)) ? 5000 : false),
  });
  const busy = action.isPending;

  const askRemove = async () => {
    const all = purge === 'purge';
    const ok = await confirmDialog({
      title: `“${doc.title}”을(를) 삭제할까요?`,
      description: (
        <span className='flex flex-col gap-1'>
          <span>원본 파일, 모든 버전, 본문과 검색 색인을 삭제합니다.</span>
          <span>{all ? '이 문서를 근거로 쓴 과거 상담의 근거 발췌와 그 분석 결과도 삭제합니다.' : '과거 상담에 저장된 근거 발췌는 남겨 둡니다.'}</span>
          <span>대화의 질문과 답변 텍스트는 남습니다. 대화까지 지우려면 상담에서 대화를 삭제하세요.</span>
        </span>
      ),
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok)
      action.mutate(() => documentsApi.remove(doc.id, all), {
        onSuccess: () => {
          notify.success('삭제했습니다');
          onClose();
        },
      });
  };

  return (
    <Sheet open onOpenChange={o => !o && onClose()}>
      <SheetContent side='right' className='w-[min(520px,100vw)] overflow-y-auto'>
        <div className='flex flex-col gap-5 p-5'>
          <div>
            <SheetTitle className='pr-8 text-title font-semibold'>{doc.title}</SheetTitle>
            <div className='mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
              <StatusLabel status={doc.status} />
              <span>{doc.filename}</span>
              {doc.as_of && <span>· 기준일 {dateOnly(doc.as_of)}</span>}
            </div>
            {replacing(doc) && <p className='mt-2 text-ui text-muted-foreground'>새 버전을 처리하는 동안에는 이전 버전으로 검색합니다.</p>}
            {doc.error && (
              <Alert variant='destructive' className='mt-2'>
                {doc.error}
              </Alert>
            )}
          </div>

          {doc.sharing_enabled && doc.active_version_id && (
            <Button asChild size='sm' className='self-start'>
              <Link href={`/advisor?document=${doc.id}`}>
                <MessagesSquare /> 이 문서로 상담하기
              </Link>
            </Button>
          )}

          <label className='flex items-center gap-3'>
            <span className='flex-1'>
              상담에 공유
              <span className='block text-xs text-muted-foreground'>끄면 이 문서를 근거로 한 과거 답변 내용도 다시 보내지 않습니다.</span>
            </span>
            <Switch
              aria-label='상담에 공유'
              checked={doc.sharing_enabled}
              disabled={busy}
              onCheckedChange={v => action.mutate(() => documentsApi.update(doc.id, { sharing_enabled: v }))}
            />
          </label>

          <form
            className='flex flex-col gap-3'
            key={doc.updated_at}
            onSubmit={e => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              action.mutate(() => documentsApi.update(doc.id, { title: String(data.get('title')), kind: String(data.get('kind')), categories }), {
                onSuccess: () => notify.success('저장했습니다'),
              });
            }}>
            <h3 className='border-b pb-1 text-ui font-semibold'>정보</h3>
            <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
              <div className='flex flex-col gap-1'>
                <Label htmlFor='edit-title'>제목</Label>
                <Input id='edit-title' name='title' defaultValue={doc.title} required maxLength={200} />
              </div>
              <div className='flex flex-col gap-1'>
                <Label htmlFor='edit-kind'>종류</Label>
                <KindSelect id='edit-kind' name='kind' defaultValue={doc.kind} />
              </div>
            </div>
            <TopicPicker value={categories} onChange={setCategories} />
            <Button type='submit' size='sm' className='self-start' disabled={busy || categories.length === 0}>
              저장
            </Button>
          </form>

          <section className='flex flex-col gap-2'>
            <h3 className='border-b pb-1 text-ui font-semibold'>버전</h3>
            <QueryStatus pending={versions.isPending} error={versions.error} retry={versions.refetch} label='버전' rows={2} />
            <ul className='flex flex-col gap-1.5'>
              {versions.data?.map(v => (
                <li key={v.id} className='flex flex-wrap items-center gap-2 text-ui'>
                  <span className='tabular-nums text-muted-foreground'>{dateTime(v.created_at)}</span>
                  <span className='min-w-0 truncate'>{v.filename}</span>
                  {v.as_of && <span className='text-xs text-faint'>기준일 {dateOnly(v.as_of)}</span>}
                  {v.id === doc.active_version_id ? <Badge variant='success'>검색에 사용 중</Badge> : <StatusLabel status={v.status} />}
                  {v.error && <span className='w-full text-xs text-destructive'>{v.error}</span>}
                </li>
              ))}
            </ul>
            <div className='mt-1 flex flex-wrap items-end gap-2 rounded-md border p-2.5'>
              <div className='flex flex-col gap-1'>
                <Label htmlFor='version-asof'>새 버전 기준일</Label>
                <Input id='version-asof' type='date' value={versionDate} onChange={e => setVersionDate(e.target.value)} />
              </div>
              <div className='flex min-w-0 flex-1 flex-col gap-1'>
                <Label htmlFor='version-file'>새 버전 파일</Label>
                <Input
                  id='version-file'
                  type='file'
                  accept={ACCEPT}
                  disabled={busy}
                  onChange={e => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const data = new FormData();
                    data.set('file', file);
                    if (versionDate) data.set('as_of', versionDate);
                    action.mutate(() => documentsApi.replace(doc.id, data), { onSuccess: () => notify.success('새 버전을 올렸습니다') });
                    e.target.value = '';
                  }}
                />
              </div>
            </div>
            <div className='flex flex-wrap gap-2'>
              {doc.status === 'ready' && (
                <Button size='sm' disabled={busy} onClick={() => action.mutate(() => documentsApi.reindex(doc.id))}>
                  다시 색인
                </Button>
              )}
              {doc.status === 'failed' && (
                <Button size='sm' disabled={busy} onClick={() => action.mutate(() => documentsApi.retry(doc.id))}>
                  다시 처리
                </Button>
              )}
            </div>
            {doc.status === 'ready' && <p className='text-xs text-faint'>문서 검색 설정을 바꾼 뒤에는 다시 색인하세요. 새 색인이 끝날 때까지 기존 색인으로 검색합니다.</p>}
          </section>

          <section className='flex flex-col gap-2'>
            <h3 className='border-b pb-1 text-ui font-semibold text-destructive'>삭제</h3>
            <RadioGroup value={purge} onValueChange={v => setPurge(v as 'keep' | 'purge')} aria-label='삭제 범위'>
              <label className='flex items-start gap-2'>
                <RadioGroupItem value='keep' className='mt-0.5' />
                <span>
                  문서만 삭제
                  <span className='block text-xs text-muted-foreground'>과거 상담에 저장된 근거 발췌는 남습니다.</span>
                </span>
              </label>
              <label className='flex items-start gap-2'>
                <RadioGroupItem value='purge' className='mt-0.5' />
                <span>
                  과거 상담 근거까지 삭제
                  <span className='block text-xs text-muted-foreground'>이 문서를 사용한 답변의 근거 발췌와 분석 결과도 지웁니다.</span>
                </span>
              </label>
            </RadioGroup>
            <Button variant='destructive' size='sm' className='self-start' disabled={busy} onClick={() => void askRemove()}>
              삭제
            </Button>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function DocumentsView() {
  const query = useQuery({
    queryKey: documentsKey,
    queryFn: documentsApi.list,
    refetchInterval: q => (q.state.data?.some(d => IN_PROGRESS.has(d.status) || replacing(d)) ? 5000 : false),
  });
  const [uploading, setUploading] = useState(false);
  const [filter, setFilter] = useState<string>('');
  const [openId, setOpenId] = useState<number | null>(null);
  const docs = (query.data ?? []).filter(d => !filter || d.categories.includes(filter));
  const open = openId !== null ? query.data?.find(d => d.id === openId) : undefined;

  return (
    <PageContainer>
      <PageHeader
        title='문서함'
        description='이력서, 채용 공고, 투자 원칙 같은 문서를 올려 두면 상담에서 근거로 찾아 씁니다.'
        actions={
          <>
            <Button asChild>
              <Link href='/advisor'>
                <MessagesSquare /> 문서로 상담하기
              </Link>
            </Button>
            <Button variant='primary' onClick={() => setUploading(true)}>
              <Upload /> 문서 올리기
            </Button>
          </>
        }
      />

      <Section
        title='문서'
        count={query.data?.length}
        actions={
          <NativeSelect aria-label='주제로 보기' className='h-7 w-auto text-xs' value={filter} onChange={e => setFilter(e.target.value)}>
            <option value=''>모든 주제</option>
            {TOPICS.map(c => (
              <option key={c} value={c}>
                {CATEGORY_LABEL[c]}
              </option>
            ))}
          </NativeSelect>
        }>
        <QueryStatus pending={query.isPending} error={query.error} retry={query.refetch} label='문서' />
        {query.data?.length === 0 && (
          <EmptyState
            icon={FileText}
            title='아직 올린 문서가 없습니다'
            action={
              <Button variant='primary' onClick={() => setUploading(true)}>
                <Upload /> 문서 올리기
              </Button>
            }>
            이력서나 관심 있는 채용 공고부터 올려 보세요.
          </EmptyState>
        )}
        {query.data && query.data.length > 0 && docs.length === 0 && <p className='py-3 text-ui text-muted-foreground'>이 주제의 문서가 없습니다.</p>}
        <ul className='divide-y'>
          {docs.map(doc => (
            <li key={doc.id}>
              <button type='button' onClick={() => setOpenId(doc.id)} className='flex w-full flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-left hover:bg-muted/40'>
                <FileText className='size-4 shrink-0 text-faint' aria-hidden />
                <span className='min-w-0 flex-1'>
                  <span className='block font-medium'>{doc.title}</span>
                  <span className='block text-xs text-muted-foreground'>
                    {kindLabel(doc.kind)} · {doc.categories.map(c => CATEGORY_LABEL[c as Category] ?? c).join(', ')}
                    {doc.as_of ? ` · 기준일 ${dateOnly(doc.as_of)}` : ''}
                  </span>
                </span>
                {replacing(doc) ? <Badge variant='accent'>새 버전 처리 중</Badge> : <StatusLabel status={doc.status} />}
                {doc.sharing_enabled ? <Badge variant='accent'>상담 공유</Badge> : <Badge>이 기기에서만</Badge>}
              </button>
            </li>
          ))}
        </ul>
      </Section>

      <UploadDialog open={uploading} onClose={() => setUploading(false)} />
      {open && <DocumentSheet key={open.id} doc={open} onClose={() => setOpenId(null)} />}
    </PageContainer>
  );
}
