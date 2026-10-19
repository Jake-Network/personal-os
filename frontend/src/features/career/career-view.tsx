'use client';

import { useMemo, useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, FolderTree, Plus, Search, Trash2 } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import { TabToolbar } from '@/components/area-layout';
import { useConfirm } from '@/components/confirm-dialog';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { ListSkeleton } from '@/components/skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { dateOnly } from '@/lib/utils/format';

import { DataForm } from '@/features/personal-data/components/data-form';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { type OpenApiSpec, schemaFields } from '@/features/personal-data/utils/schema-fields';

import { type CareerRecord, careerApi } from './api';

export const CAREER_KIND_LABEL: Record<string, string> = {
  employment: '재직',
  role: '역할 변화',
  project: '프로젝트',
  contribution: '본인 기여',
  achievement: '성과',
  feedback: '피드백·배운 점',
  evidence: '근거',
};
const ENUM_LABELS: Record<string, string> = {
  ...CAREER_KIND_LABEL,
  planned: '예정',
  active: '진행 중',
  completed: '완료',
  paused: '중단',
  cancelled: '취소',
};
const LABELS: Record<string, string> = {
  kind: '종류',
  progress: '진행 상태',
  parent_id: '상위 기록',
  organization: '조직',
  started_on: '시작 시점',
  ended_on: '종료 시점',
  description: '책임 범위·문제·목표',
  approach: '본인이 선택한 접근법',
  outcome: '성과·측정 기간·협업 범위',
  lessons: '배운 점·다음에 바꿀 점',
  evidence_url: '근거 링크',
  skills: '사용한 역량 (쉼표로 구분)',
  share_with_advisor: '상담에 공유',
};
const TEXT_FIELDS = new Set(['description', 'approach', 'outcome', 'lessons']);
const SOURCE_FIELDS = ['source', 'source_message_id', 'source_document_version_id'];

export const careerRecordsKey = ['career-records'] as const;

function period(r: CareerRecord): string {
  if (!r.started_on) return '시점 미기록';
  return r.ended_on ? `${r.started_on} – ${r.ended_on}` : `${r.started_on} –`;
}

interface Node {
  record: CareerRecord;
  children: Node[];
}

function buildTree(rows: CareerRecord[]): Node[] {
  const nodes = new Map(rows.map(r => [r.id, { record: r, children: [] as Node[] }]));
  const roots: Node[] = [];
  for (const node of nodes.values()) {
    const parent = node.record.parent_id ? nodes.get(node.record.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const order = (list: Node[]) => {
    list.sort((a, b) => String(b.record.started_on ?? '').localeCompare(String(a.record.started_on ?? '')) || a.record.title.localeCompare(b.record.title));
    list.forEach(n => order(n.children));
  };
  order(roots);
  return roots;
}

function matches(r: CareerRecord, q: string) {
  return [r.title, r.company, r.organization, r.role, ...(r.skills ?? [])].some(s => s?.toLowerCase().includes(q));
}

/** Keep a node when it or any descendant matches. */
function filterTree(nodes: Node[], q: string): Node[] {
  if (!q) return nodes;
  return nodes.flatMap(n => {
    const children = filterTree(n.children, q);
    return matches(n.record, q) || children.length ? [{ ...n, children }] : [];
  });
}

function TreeRow({ node, depth, collapsed, toggle, onOpen }: { node: Node; depth: number; collapsed: Set<number>; toggle: (id: number) => void; onOpen: (r: CareerRecord) => void }) {
  const r = node.record;
  const open = !collapsed.has(r.id);
  return (
    <li>
      <div className='flex items-center gap-1 border-b py-1.5' style={{ paddingLeft: depth * 20 }}>
        {node.children.length > 0 ? (
          <Button size='icon-sm' variant='ghost' aria-expanded={open} aria-label={open ? `${r.title} 접기` : `${r.title} 펼치기`} onClick={() => toggle(r.id)}>
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
        ) : (
          <span className='inline-block size-7 shrink-0' aria-hidden />
        )}
        <button type='button' onClick={() => onOpen(r)} className='flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md px-1 py-0.5 text-left hover:bg-muted/50'>
          <span className='text-xs text-faint'>{CAREER_KIND_LABEL[r.kind] ?? r.kind}</span>
          <span className='font-medium'>{r.title}</span>
          <span className='text-xs text-muted-foreground'>{[r.company, r.organization, r.role].filter(Boolean).join(' · ')}</span>
          <span className='text-xs tabular-nums text-faint'>{period(r)}</span>
          {r.status === 'draft' && <Badge variant='warning'>확인 전 초안</Badge>}
          {r.share_with_advisor && <Badge variant='accent'>상담 공유</Badge>}
        </button>
      </div>
      {open && node.children.length > 0 && (
        <ul>
          {node.children.map(c => (
            <TreeRow key={c.record.id} node={c} depth={depth + 1} collapsed={collapsed} toggle={toggle} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Employment → project → contribution → outcome, as a tree you can fold. */
export function CareerView({ recordId }: { recordId: number | null }) {
  const cache = useQueryClient();
  const confirmDialog = useConfirm();
  const list = useQuery({ queryKey: careerRecordsKey, queryFn: careerApi.list });
  const schema = useQuery({
    queryKey: ['/openapi.json'],
    queryFn: () => customInstance<OpenApiSpec>({ url: '/openapi.json' }),
    staleTime: Infinity,
    select: spec =>
      schemaFields({ ...spec, paths: { '/api/data/career': spec.paths?.['/api/career/records'] ?? {} } }, 'career')
        .filter(f => !SOURCE_FIELDS.includes(f.name))
        .map(f => (TEXT_FIELDS.has(f.name) ? { ...f, kind: 'longtext' as const } : f)),
  });
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState<{ parent_id?: number } | null>(null);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState('');

  const refresh = () =>
    Promise.all([
      cache.invalidateQueries({ queryKey: careerRecordsKey }),
      cache.invalidateQueries({ queryKey: ['/api/timeline'] }),
      cache.invalidateQueries({ queryKey: ['timeline'] }),
    ]);
  const rows = useMemo(() => list.data ?? [], [list.data]);
  const tree = useMemo(() => filterTree(buildTree(rows), filter.trim().toLowerCase()), [rows, filter]);
  const editing = creating === null && selected !== null ? (rows.find(r => r.id === selected) ?? null) : null;
  const open = creating !== null || editing !== null;
  const close = () => {
    setCreating(null);
    setSelected(null);
  };

  const confirm = useMutation({ mutationFn: (id: number) => careerApi.confirm(id), onSuccess: refresh, onError: notify.error });
  const remove = useMutation({
    mutationFn: (id: number) => careerApi.remove(id),
    onSuccess: async () => {
      close();
      notify.success('삭제했습니다');
      await refresh();
    },
    onError: notify.error,
  });

  const save = async (payload: Record<string, unknown>) => {
    await careerApi.save(
      {
        ...payload,
        skills: String(payload.skills ?? '')
          .split(',')
          .map(s => s.trim())
          .filter(Boolean),
        ...(editing ? { source: editing.source, source_message_id: editing.source_message_id, source_document_version_id: editing.source_document_version_id } : {}),
      },
      editing?.id,
    );
    await refresh();
    notify.success(editing ? '저장했습니다' : '추가했습니다');
    close();
  };

  const askRemove = async (r: CareerRecord) => {
    const ok = await confirmDialog({
      title: `“${r.title}” 기록을 삭제할까요?`,
      description: '하위 기록이 있으면 먼저 옮기거나 삭제해야 합니다. 삭제한 기록은 복구할 수 없습니다.',
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok) remove.mutate(r.id);
  };

  const toggle = (id: number) =>
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // A record never becomes its own ancestor.
  const descendants = (id: number): Set<number> => {
    const out = new Set<number>([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const r of rows) {
        if (r.parent_id && out.has(r.parent_id) && !out.has(r.id)) {
          out.add(r.id);
          grew = true;
        }
      }
    }
    return out;
  };
  const excluded = editing ? descendants(editing.id) : new Set<number>();
  const parentChoices = rows
    .filter(r => !excluded.has(r.id))
    .map(r => ({ value: String(r.id), label: [CAREER_KIND_LABEL[r.kind], r.title, r.company].filter(Boolean).join(' · ') }));

  return (
    <>
      <TabToolbar>
        <Button variant='primary' disabled={!schema.data} onClick={() => setCreating({})}>
          <Plus /> 기록 추가
        </Button>
        <div className='relative ml-auto w-full sm:w-64'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint' aria-hidden />
          <Input aria-label='회사·제목·역량 검색' placeholder='회사·제목·역량 검색' className='pl-8' value={filter} onChange={e => setFilter(e.target.value)} />
        </div>
      </TabToolbar>

      <QueryStatus pending={list.isPending} error={list.error ?? schema.error} retry={() => Promise.all([list.refetch(), schema.refetch()])} label='경력 기록' />
      {list.data && rows.length === 0 && (
        <EmptyState
          icon={FolderTree}
          title='아직 경력 기록이 없습니다'
          action={
            <Button variant='primary' disabled={!schema.data} onClick={() => setCreating({})}>
              <Plus /> 재직 또는 프로젝트 추가
            </Button>
          }>
          재직 아래에 프로젝트, 그 아래에 본인 기여와 성과를 이어 붙이세요.
        </EmptyState>
      )}
      {list.data && rows.length > 0 && tree.length === 0 && <p className='py-4 text-ui text-muted-foreground'>검색과 일치하는 기록이 없습니다.</p>}
      <ul aria-label='경력 기록'>
        {tree.map(n => (
          <TreeRow key={n.record.id} node={n} depth={0} collapsed={collapsed} toggle={toggle} onOpen={r => setSelected(r.id)} />
        ))}
      </ul>

      <Sheet open={open} onOpenChange={next => !next && close()}>
        <SheetContent side='right' className='w-[min(560px,100vw)] overflow-y-auto'>
          <div className='flex flex-col gap-3 p-5'>
            <SheetTitle className='pr-8 text-title font-semibold'>{editing ? editing.title : '경력 기록 추가'}</SheetTitle>
            {editing && (
              <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                <span>{CAREER_KIND_LABEL[editing.kind]}</span>
                <span>· 기록 {dateOnly(editing.recorded_at)}</span>
                {editing.evidence_url && (
                  <a href={editing.evidence_url} target='_blank' rel='noopener noreferrer' className='text-primary hover:underline'>
                    근거 열기
                  </a>
                )}
                {editing.status === 'draft' && (
                  <Button size='sm' variant='primary' disabled={confirm.isPending} onClick={() => confirm.mutate(editing.id)}>
                    내용 확인·확정
                  </Button>
                )}
                <Button size='sm' onClick={() => setCreating({ parent_id: editing.id })}>
                  <Plus /> 하위 기록
                </Button>
              </div>
            )}
            {editing?.status === 'draft' && <p className='text-ui text-warning'>상담이나 문서에서 추출한 초안입니다. 확인하기 전에는 상담에 확정된 사실로 쓰지 않습니다.</p>}
            <p className='text-xs text-faint'>시점은 아는 만큼 입력하세요: 연도(2024), 연월(2024-03), 날짜(2024-03-15).</p>
            {schema.isPending && <ListSkeleton rows={6} />}
            {schema.data && open && (
              <DataForm
                key={editing ? `edit-${editing.id}` : `new-${creating?.parent_id ?? ''}`}
                fields={schema.data}
                labels={LABELS}
                enumLabels={ENUM_LABELS}
                recordChoices={{ parent_id: parentChoices }}
                current={editing ? { ...editing, skills: editing.skills.join(', ') } : creating?.parent_id ? { parent_id: creating.parent_id } : undefined}
                submitLabel={editing ? '저장' : '추가'}
                onSubmit={save}
                onCancel={close}
                extraActions={
                  editing && (
                    <Button type='button' size='icon' variant='ghost-destructive' aria-label='삭제' disabled={remove.isPending} onClick={() => void askRemove(editing)}>
                      <Trash2 />
                    </Button>
                  )
                }
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

